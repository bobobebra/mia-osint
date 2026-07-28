from __future__ import annotations

import asyncio
import logging
import secrets
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from mia import __version__
from mia.account_discovery import LinkedAccountImporter
from mia.assistant import InvestigationAssistant, write_analysis
from mia.config import AppConfig, load_config, user_config_path
from mia.db import ScanDatabase
from mia.deep_case import DeepCaseEngine
from mia.graph import export_all_graph_formats
from mia.knowledge import KnowledgeDatabase
from mia.logging_utils import configure_logging
from mia.models import DeepCaseManifest, DeepCaseSeed
from mia.orchestrator import Orchestrator
from mia.package_manager import PackageEvent, PackageManager, load_catalog
from mia.registry import PluginRegistry
from mia.reports.dashboard import write_dashboard
from mia.secrets import SecretStore
from mia.utils import atomic_write_text
from mia.verification import IdentityClusterEngine, ProfileVerifier
from mia.web.operations import Operation, OperationManager
from mia.web.schemas import (
    AnalyzeRequest,
    ApiKeyRequest,
    DeepCaseRequest,
    GuidedReviewRequest,
    NoteRequest,
    PackageOperationRequest,
    ProviderConfigRequest,
    ReviewResolutionRequest,
)
from mia.workspace import CaseManager


class WebRuntime:
    def __init__(
        self,
        config_path: Path | None,
        *,
        allow_remote: bool = False,
        access_token: str | None = None,
    ) -> None:
        self.config_path = config_path
        self.allow_remote = allow_remote
        self.access_token = access_token
        self.operations = OperationManager()

    def config(self) -> AppConfig:
        return load_config(self.config_path)

    def case_manager(self) -> CaseManager:
        return CaseManager(self.config().paths.cases_dir)

    def knowledge(self) -> KnowledgeDatabase:
        config = self.config()
        return KnowledgeDatabase(config.paths.knowledge_database_path)

    def orchestrator(self) -> tuple[AppConfig, Orchestrator, logging.Logger]:
        config = self.config()
        logger = configure_logging(config.paths.log_dir, False)
        registry = PluginRegistry.discover(config.paths.user_plugins_dir)
        database = ScanDatabase(config.paths.database_path)
        return config, Orchestrator(config, registry, database, logger), logger


def _json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _provider_is_external(name: str, endpoint: str) -> bool:
    normalized = endpoint.strip().casefold()
    if name == "local" or normalized in {"", "offline"}:
        return False
    if any(marker in normalized for marker in ("127.0.0.1", "localhost", "[::1]", "0.0.0.0")):
        return False
    if name == "gemini":
        return True
    return normalized.startswith(("http://", "https://"))


def _bounded_profile_context(workspace: Any) -> list[dict[str, Any]]:
    """Build a small metadata-only profile context suitable for optional AI review."""

    allowed = {
        "username",
        "display_name",
        "bio",
        "location",
        "website",
        "canonical_url",
        "page_title",
        "identity_links",
        "created_at",
        "updated_at",
        "public_repos",
        "followers",
        "following",
        "account_type",
        "platform_limitations",
    }
    output: list[dict[str, Any]] = []
    for item in workspace.verifications()[:100]:
        payload = _json(item)
        extracted = payload.get("extracted") if isinstance(payload, dict) else {}
        safe: dict[str, Any] = {}
        if isinstance(extracted, dict):
            for key in allowed:
                value = extracted.get(key)
                if isinstance(value, str):
                    safe[key] = value[:2000]
                elif isinstance(value, list):
                    safe[key] = [str(entry)[:500] for entry in value[:20]]
                elif isinstance(value, (int, float, bool)) or value is None:
                    safe[key] = value
        output.append(
            {
                "node_id": payload.get("node_id"),
                "platform": payload.get("platform"),
                "url": payload.get("url"),
                "final_url": payload.get("final_url"),
                "status": payload.get("status"),
                "score": payload.get("score"),
                "reasons": list(payload.get("reasons") or [])[:20],
                "negative_reasons": list(payload.get("negative_reasons") or [])[:20],
                "metadata": safe,
            }
        )
    return output


def _provider_rows(config: AppConfig) -> list[dict[str, Any]]:
    store = SecretStore(config)
    rows: list[dict[str, Any]] = [
        {
            "provider": "local",
            "default": config.assistant.provider in {"local", "off", "none"},
            "model": "deterministic",
            "endpoint": "offline",
            "thinking_level": "deterministic",
            "credential": "not required",
            "ready": True,
            "external": False,
            "may_charge": False,
            "automatic": False,
            "data_destination": "this computer",
        }
    ]
    for name in ("openai-compatible", "gemini", "ollama"):
        settings = config.assistant.settings(name)
        credential = (
            store.source(settings.api_service) if settings.api_service else "not configured"
        )
        has_key = bool(store.get(settings.api_service)) if settings.api_service else False
        rows.append(
            {
                "provider": name,
                "default": InvestigationAssistant.normalize_provider(config.assistant.provider)
                == name,
                "model": settings.model or "not configured",
                "endpoint": settings.endpoint,
                "thinking_level": settings.thinking_level or "provider default",
                "credential": credential
                if settings.requires_key or has_key
                else "not required (local)",
                "ready": bool(settings.model.strip()) and (not settings.requires_key or has_key),
                "external": _provider_is_external(name, settings.endpoint),
                "may_charge": _provider_is_external(name, settings.endpoint),
                "automatic": False,
                "data_destination": settings.endpoint or name,
            }
        )
    return rows


def _resolve_ai_provider(
    config: AppConfig,
    requested_provider: str | None,
    *,
    endpoint_override: str | None = None,
    confirm_external_cost: bool = False,
) -> str:
    rows = _provider_rows(config)
    default_row = next((item for item in rows if item["default"]), rows[0])
    normalized = InvestigationAssistant.normalize_provider(
        requested_provider or str(default_row["provider"])
    )
    selected = next((item for item in rows if item["provider"] == normalized), None)
    if selected is None or not selected["ready"]:
        raise HTTPException(status_code=400, detail=f"AI provider '{normalized}' is not ready")
    endpoint = endpoint_override if endpoint_override is not None else str(selected["endpoint"])
    if _provider_is_external(normalized, endpoint) and not confirm_external_cost:
        raise HTTPException(
            status_code=400,
            detail=(
                f"External AI provider '{normalized}' requires confirm_external_cost=true. "
                "It may use API quota or create charges on the configured provider account."
            ),
        )
    return normalized


def _config_write_path(runtime: WebRuntime) -> Path:
    return (runtime.config_path or user_config_path()).expanduser()


def _load_user_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("configuration root must be a mapping")
    return payload


def _save_provider(runtime: WebRuntime, request: ProviderConfigRequest) -> Path:
    path = _config_write_path(runtime)
    data = _load_user_config(path)
    assistant = data.setdefault("assistant", {})
    if not isinstance(assistant, dict):
        raise ValueError("configuration key 'assistant' must be a mapping")
    if request.provider == "local":
        if request.set_default:
            assistant["provider"] = "local"
    else:
        providers = assistant.setdefault("providers", {})
        if not isinstance(providers, dict):
            raise ValueError("configuration key 'assistant.providers' must be a mapping")
        provider = providers.setdefault(request.provider, {})
        if not isinstance(provider, dict):
            raise ValueError(
                f"configuration key 'assistant.providers.{request.provider}' must be a mapping"
            )
        if request.model is not None:
            provider["model"] = request.model.strip()
        if request.endpoint is not None:
            provider["endpoint"] = request.endpoint.strip()
        if request.thinking_level is not None:
            provider["thinking_level"] = request.thinking_level
        if request.set_default:
            assistant["provider"] = request.provider
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write_text(path, yaml.safe_dump(data, sort_keys=False), mode=0o600)
    return path


def _rebuild_case(config: AppConfig, workspace: Any) -> None:
    nodes, edges = workspace.nodes(), workspace.edges()
    export_all_graph_formats(workspace.graph_dir, nodes, edges)
    workspace.export_payload()
    knowledge = KnowledgeDatabase(config.paths.knowledge_database_path)
    knowledge.ingest(workspace.record, nodes)
    correlations = knowledge.correlations_for_case(workspace.record.case_id)
    summary = InvestigationAssistant(config).local_summary(nodes, edges, correlations)
    write_dashboard(
        workspace,
        raw_excerpt_bytes=config.reports.dashboard_raw_excerpt_bytes,
        assistant_summary=summary,
        correlations=correlations,
        max_nodes=config.workspaces.graph_max_nodes_in_dashboard,
    )


def create_app(
    config_path: Path | None = None,
    *,
    allow_remote: bool = False,
    access_token: str | None = None,
    ui_variant: str = "workbench",
) -> FastAPI:
    if ui_variant not in {"workbench", "discover"}:
        raise ValueError("ui_variant must be workbench or discover")
    runtime = WebRuntime(config_path, allow_remote=allow_remote, access_token=access_token)
    app = FastAPI(
        title="MIA Discover Local API" if ui_variant == "discover" else "MIA Workbench Local API",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.runtime = runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def local_only(request: Request, call_next):  # type: ignore[no-untyped-def]
        client = request.client.host if request.client else ""
        if not runtime.allow_remote and client not in {
            "127.0.0.1",
            "::1",
            "localhost",
            "testclient",
        }:
            return JSONResponse({"detail": "MIA Core UI is localhost-only"}, status_code=403)
        if runtime.access_token and request.url.path.startswith("/api/"):
            supplied = request.headers.get("x-mia-token") or request.query_params.get("token")
            if not secrets.compare_digest(supplied or "", runtime.access_token):
                return JSONResponse({"detail": "invalid MIA Core UI token"}, status_code=401)
        return await call_next(request)

    def resolve_case(identifier: str):
        try:
            return runtime.case_manager().resolve(identifier)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        config = runtime.config()
        return {
            "status": "ok",
            "version": __version__,
            "localhost_only": not runtime.allow_remote,
            "cases_dir": str(config.paths.cases_dir),
            "state_dir": str(config.paths.state_dir),
        }

    @app.get("/api/overview")
    async def overview() -> dict[str, Any]:
        config = runtime.config()
        manager = CaseManager(config.paths.cases_dir)
        records = manager.list(include_archived=True)
        package_manager = PackageManager(state_dir=config.paths.state_dir)
        inventory = package_manager.inventory()
        open_cases = [record for record in records if record.status.value == "open"]
        total_nodes = total_edges = pending_reviews = 0
        recent: list[dict[str, Any]] = []
        for record in records[:12]:
            workspace = manager.resolve(record.case_id)
            nodes = len(workspace.nodes())
            edges = len(workspace.edges())
            pending = len(
                [task for task in workspace.review_tasks() if task.status.value == "pending"]
            )
            total_nodes += nodes
            total_edges += edges
            pending_reviews += pending
            recent.append(
                {
                    **record.model_dump(mode="json"),
                    "nodes": nodes,
                    "edges": edges,
                    "pending_reviews": pending,
                }
            )
        return {
            "stats": {
                "cases": len(records),
                "open_cases": len(open_cases),
                "nodes": total_nodes,
                "edges": total_edges,
                "pending_reviews": pending_reviews,
                "installed_tools": sum(bool(item["installed"]) for item in inventory),
                "catalog_tools": len(inventory),
            },
            "recent_cases": recent,
            "providers": _provider_rows(config),
            "operations": [item.payload() for item in runtime.operations.list()[:8]],
        }

    @app.get("/api/cases")
    async def cases(include_archived: bool = True) -> list[dict[str, Any]]:
        manager = runtime.case_manager()
        rows: list[dict[str, Any]] = []
        for record in manager.list(include_archived=include_archived):
            workspace = manager.resolve(record.case_id)
            rows.append(
                {
                    **record.model_dump(mode="json"),
                    "node_count": len(workspace.nodes()),
                    "edge_count": len(workspace.edges()),
                    "scan_count": len(workspace.scans()),
                    "review_count": len(workspace.review_tasks()),
                }
            )
        return rows

    @app.get("/api/cases/{identifier}")
    async def case_detail(identifier: str) -> dict[str, Any]:
        workspace = resolve_case(identifier)
        return workspace.graph_payload()

    @app.post("/api/cases/deep")
    async def create_deep_case(request: DeepCaseRequest) -> dict[str, Any]:
        async def runner(operation: Operation) -> dict[str, Any]:
            config, orchestrator, logger = runtime.orchestrator()
            knowledge = KnowledgeDatabase(config.paths.knowledge_database_path)
            engine = DeepCaseEngine(config, orchestrator, knowledge, logger)
            manifest = DeepCaseManifest(
                name=request.name,
                workflow=request.workflow,
                description=request.description,
                tags=request.tags,
                hypotheses=request.hypotheses,
                notes=request.notes,
                seeds=[DeepCaseSeed(**seed.model_dump()) for seed in request.seeds],
            )
            total = max(1, len(request.seeds))
            started: set[str] = set()

            loop = asyncio.get_running_loop()

            def progress_event(event_name: str, plugin_id: str, detail: str) -> None:
                if event_name == "start":
                    started.add(plugin_id)
                fraction = min(0.88, len(started) / total * 0.75)
                asyncio.run_coroutine_threadsafe(
                    runtime.operations.emit(
                        operation,
                        "progress",
                        current=f"{plugin_id}: {detail}",
                        message=detail,
                        progress=fraction,
                    ),
                    loop,
                )

            await runtime.operations.emit(
                operation, "progress", current="Preparing case", progress=0.03
            )
            result = await engine.run(
                manifest,
                case_identifier=request.case_identifier,
                profile=request.profile,
                verify_profiles=request.verify_profiles,
                enable_pivoting=request.enable_pivoting,
                max_depth=request.max_depth,
                max_targets=request.max_targets,
                include=request.include_tools or None,
                exclude=request.exclude_tools or None,
                event_callback=progress_event,
                use_cache=request.use_cache,
            )
            await runtime.operations.emit(
                operation, "progress", current="Building workspace", progress=0.94
            )
            return {
                "case_id": result.workspace.record.case_id,
                "case_name": result.workspace.record.name,
                "workspace": str(result.workspace.root),
                "dashboard": str(result.dashboard_path) if result.dashboard_path else None,
                "scans": len(result.scans),
                "nodes": len(result.workspace.nodes()),
                "edges": len(result.workspace.edges()),
                "verifications": result.verifications,
                "generated_account_leads": result.generated_account_leads,
                "clusters": len(result.clusters),
                "review_tasks": len(result.review_tasks),
                "failed_seeds": result.failed_seeds,
            }

        operation = await runtime.operations.create(
            "deep-case", f"Investigating {request.name}", runner
        )
        return {"operation_id": operation.operation_id}

    @app.post("/api/cases/{identifier}/notes")
    async def add_note(identifier: str, request: NoteRequest) -> dict[str, Any]:
        workspace = resolve_case(identifier)
        workspace.append_note(request.text)
        _rebuild_case(runtime.config(), workspace)
        return {"ok": True, "notes": workspace.notes_path.read_text(encoding="utf-8")}

    @app.post("/api/cases/{identifier}/verify")
    async def verify_case(identifier: str) -> dict[str, Any]:
        async def runner(operation: Operation) -> dict[str, Any]:
            config = runtime.config()
            workspace = resolve_case(identifier)
            await runtime.operations.emit(
                operation, "progress", current="Verifying candidate profiles", progress=0.08
            )
            verifier = ProfileVerifier(config)
            results = await verifier.verify_case(workspace)
            if (
                config.account_discovery.enabled
                and config.account_discovery.follow_public_profile_links
            ):
                importer = LinkedAccountImporter()
                for _ in range(config.account_discovery.max_link_hops):
                    linked_nodes = importer.import_from_verifications(workspace)
                    if not linked_nodes:
                        break
                    results.extend(await verifier.verify_nodes(workspace, linked_nodes))
            await runtime.operations.emit(
                operation, "progress", current="Clustering identities", progress=0.72
            )
            clusters, tasks, edges = IdentityClusterEngine(config).run(workspace)
            _rebuild_case(config, workspace)
            return {
                "case_id": workspace.record.case_id,
                "verifications": len(results),
                "clusters": len(clusters),
                "review_tasks": len(tasks),
                "comparison_edges": len(edges),
            }

        operation = await runtime.operations.create("verify", f"Verify {identifier}", runner)
        return {"operation_id": operation.operation_id}

    @app.post("/api/cases/{identifier}/cluster")
    async def cluster_case(identifier: str) -> dict[str, Any]:
        async def runner(operation: Operation) -> dict[str, Any]:
            config = runtime.config()
            workspace = resolve_case(identifier)
            await runtime.operations.emit(
                operation, "progress", current="Comparing profiles", progress=0.25
            )
            clusters, tasks, edges = await asyncio.to_thread(
                IdentityClusterEngine(config).run, workspace
            )
            _rebuild_case(config, workspace)
            return {
                "clusters": len(clusters),
                "review_tasks": len(tasks),
                "comparison_edges": len(edges),
            }

        operation = await runtime.operations.create("cluster", f"Cluster {identifier}", runner)
        return {"operation_id": operation.operation_id}

    @app.post("/api/cases/{identifier}/analyze")
    async def analyze_case(identifier: str, request: AnalyzeRequest) -> dict[str, Any]:
        selected_provider = _resolve_ai_provider(
            runtime.config(),
            request.provider,
            endpoint_override=request.endpoint,
            confirm_external_cost=request.confirm_external_cost,
        )

        async def runner(operation: Operation) -> dict[str, Any]:
            config = runtime.config()
            workspace = resolve_case(identifier)
            await runtime.operations.emit(
                operation, "progress", current="Preparing bounded evidence", progress=0.05
            )
            analysis = await InvestigationAssistant(config).analyze(
                workspace.nodes(),
                workspace.edges(),
                context={
                    "seeds": workspace.deep_seeds(),
                    "clusters": [_json(item) for item in workspace.clusters()],
                    "review_tasks": [_json(item) for item in workspace.review_tasks()],
                    "verifications": [_json(item) for item in workspace.verifications()],
                    "profile_pages": _bounded_profile_context(workspace),
                    "notes": workspace.notes_path.read_text(encoding="utf-8")
                    if workspace.notes_path.exists()
                    else "",
                },
                provider=selected_provider,
                model=request.model,
                endpoint=request.endpoint,
                depth=request.depth,
                thinking_level=request.thinking_level,
            )
            await runtime.operations.emit(
                operation, "progress", current="Validating evidence citations", progress=0.86
            )
            paths = write_analysis(workspace.reports_dir, analysis)
            workspace.save_analysis(analysis)
            _rebuild_case(config, workspace)
            return {
                "case_id": workspace.record.case_id,
                "passes": len(analysis.passes),
                "rejected_ungrounded": analysis.rejected_ungrounded_statements,
                "markdown": paths["markdown"],
            }

        operation = await runtime.operations.create("analysis", f"Analyze {identifier}", runner)
        return {"operation_id": operation.operation_id}

    @app.post("/api/cases/{identifier}/guided-review")
    async def guided_review(identifier: str, request: GuidedReviewRequest) -> dict[str, Any]:
        """Verify and compare a case; external AI requires an explicit per-run confirmation."""

        selected_provider = "none"
        if request.use_ai:
            selected_provider = _resolve_ai_provider(
                runtime.config(),
                request.provider,
                confirm_external_cost=request.confirm_external_cost,
            )

        async def runner(operation: Operation) -> dict[str, Any]:
            config = runtime.config()
            workspace = resolve_case(identifier)
            await runtime.operations.emit(
                operation,
                "progress",
                current="Checking which profiles are real",
                message="Verifying candidate pages and filtering generic matches",
                progress=0.08,
            )
            results = await ProfileVerifier(config).verify_case(workspace)
            await runtime.operations.emit(
                operation,
                "progress",
                current="Comparing the profiles",
                message="Looking for shared details and contradictions",
                progress=0.43,
            )
            clusters, tasks, edges = await asyncio.to_thread(
                IdentityClusterEngine(config).run, workspace
            )
            provider_used = "none"
            ai_warning: str | None = None
            analysis_paths: dict[str, str] = {}
            if request.use_ai:
                provider_used = selected_provider
                await runtime.operations.emit(
                    operation,
                    "progress",
                    current="Writing a plain-language explanation",
                    message=(
                        f"Using {provider_used} with evidence citations"
                        if provider_used != "local"
                        else "Using MIA's private offline summary because no external AI is ready"
                    ),
                    progress=0.68,
                )
                analysis_context = {
                    "seeds": workspace.deep_seeds(),
                    "clusters": [_json(item) for item in workspace.clusters()],
                    "review_tasks": [_json(item) for item in workspace.review_tasks()],
                    "verifications": [_json(item) for item in workspace.verifications()],
                    "notes": workspace.notes_path.read_text(encoding="utf-8")
                    if workspace.notes_path.exists()
                    else "",
                }
                try:
                    analysis = await InvestigationAssistant(config).analyze(
                        workspace.nodes(),
                        workspace.edges(),
                        context=analysis_context,
                        provider=provider_used,
                        depth=request.depth,
                        thinking_level=(
                            request.thinking_level if provider_used != "local" else None
                        ),
                    )
                except Exception as exc:
                    if provider_used == "local":
                        raise
                    ai_warning = str(exc)
                    provider_used = "local"
                    await runtime.operations.emit(
                        operation,
                        "progress",
                        current="AI unavailable — using private explanation",
                        message="The configured AI could not finish, so MIA is using its offline evidence summary instead.",
                        progress=0.79,
                    )
                    analysis = await InvestigationAssistant(config).analyze(
                        workspace.nodes(),
                        workspace.edges(),
                        context=analysis_context,
                        provider="local",
                        depth=request.depth,
                    )
                analysis_paths = write_analysis(workspace.reports_dir, analysis)
                workspace.save_analysis(analysis)
            await runtime.operations.emit(
                operation,
                "progress",
                current="Refreshing the case",
                message="Saving the review, connections, and explanation",
                progress=0.93,
            )
            _rebuild_case(config, workspace)
            return {
                "case_id": workspace.record.case_id,
                "verifications": len(results),
                "clusters": len(clusters),
                "review_tasks": len(tasks),
                "comparison_edges": len(edges),
                "provider": provider_used,
                "ai_warning": ai_warning,
                "analysis": analysis_paths,
            }

        operation = await runtime.operations.create(
            "guided-review", f"Review and explain {identifier}", runner
        )
        return {"operation_id": operation.operation_id}

    @app.post("/api/cases/{identifier}/review/{task_id}")
    async def resolve_review(
        identifier: str, task_id: str, request: ReviewResolutionRequest
    ) -> dict[str, Any]:
        workspace = resolve_case(identifier)
        task = workspace.resolve_review_task(task_id, request.status, request.note)
        _rebuild_case(runtime.config(), workspace)
        return task.model_dump(mode="json")

    @app.post("/api/cases/{identifier}/attachments")
    async def add_attachment(
        identifier: str,
        upload: Annotated[UploadFile, File(...)],
        kind: str = "evidence",
        note: str = "",
    ) -> dict[str, Any]:
        if kind not in {"evidence", "screenshot"}:
            raise HTTPException(status_code=400, detail="kind must be evidence or screenshot")
        workspace = resolve_case(identifier)
        temp = (
            workspace.root
            / f".upload-{secrets.token_hex(4)}-{Path(upload.filename or 'file').name}"
        )
        try:
            size = 0
            with temp.open("wb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > 50 * 1024 * 1024:
                        raise HTTPException(status_code=413, detail="upload exceeds 50 MiB")
                    handle.write(chunk)
            attachment = workspace.add_attachment(temp, kind=kind, note=note)
            _rebuild_case(runtime.config(), workspace)
            return attachment.model_dump(mode="json")
        finally:
            temp.unlink(missing_ok=True)

    @app.get("/api/packages")
    async def packages() -> dict[str, Any]:
        config = runtime.config()
        manager = PackageManager(state_dir=config.paths.state_dir)
        return {
            "package_manager": manager.package_manager,
            "groups": manager.catalog.groups,
            "tools": manager.inventory(),
        }

    @app.post("/api/packages/operations")
    async def package_operation(request: PackageOperationRequest) -> dict[str, Any]:
        catalog = load_catalog()
        unknown = [tool for tool in request.tools if tool not in catalog.tools]
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown tools: {', '.join(unknown)}")
        mixed = [tool for tool in request.tools if catalog.tools[tool].risk == "mixed"]
        if mixed and not request.include_mixed:
            raise HTTPException(
                status_code=400, detail=f"mixed tools require confirmation: {', '.join(mixed)}"
            )

        async def runner(operation: Operation) -> dict[str, Any]:
            config = runtime.config()
            loop = asyncio.get_running_loop()
            total = len(request.tools)
            completed = 0
            active_tool = request.tools[0]

            def handler(event: PackageEvent) -> None:
                nonlocal active_tool
                active_tool = event.tool_id or active_tool
                if event.kind == "output":
                    text = (
                        event.message.strip().splitlines()[-1]
                        if event.message.strip()
                        else "Working…"
                    )
                elif event.kind == "heartbeat":
                    text = event.message or "Still working…"
                elif event.kind == "command_start":
                    text = event.message or "Running installer"
                else:
                    text = event.message or "Step complete"
                asyncio.run_coroutine_threadsafe(
                    runtime.operations.emit(
                        operation,
                        "package-progress",
                        current=f"{active_tool}: {text[:160]}",
                        message=text[:300],
                        progress=min(0.98, completed / total),
                        data={"tool": active_tool, "event": event.kind},
                    ),
                    loop,
                )

            manager = PackageManager(state_dir=config.paths.state_dir, event_handler=handler)
            results: list[dict[str, Any]] = []
            for index, tool_id in enumerate(request.tools, 1):
                tool = catalog.tools[tool_id]
                await runtime.operations.emit(
                    operation,
                    "tool-start",
                    current=f"{request.action.title()}ing {tool.name}",
                    progress=(index - 1) / total,
                    data={"tool": tool_id, "index": index, "total": total},
                )
                if request.action == "install":
                    result = await asyncio.to_thread(manager.install, tool)
                elif request.action == "update":
                    result = await asyncio.to_thread(manager.update, tool)
                else:
                    result = await asyncio.to_thread(
                        manager.uninstall, tool, remove_system=request.remove_system
                    )
                completed += 1
                results.append(result.model_dump(mode="json"))
                await runtime.operations.emit(
                    operation,
                    "tool-finish",
                    current=f"{tool.name}: {result.outcome}",
                    message=result.message,
                    progress=completed / total,
                    data={"tool": tool_id, "success": result.success, "outcome": result.outcome},
                )
            return {
                "results": results,
                "succeeded": sum(bool(item["success"]) for item in results),
                "failed": sum(not bool(item["success"]) for item in results),
            }

        operation = await runtime.operations.create(
            f"package-{request.action}",
            f"{request.action.title()} {len(request.tools)} tools",
            runner,
        )
        return {"operation_id": operation.operation_id}

    @app.get("/api/providers")
    async def providers() -> list[dict[str, Any]]:
        return _provider_rows(runtime.config())

    @app.post("/api/providers/configure")
    async def configure_provider(request: ProviderConfigRequest) -> dict[str, Any]:
        try:
            path = _save_provider(runtime, request)
            return {"ok": True, "path": str(path), "providers": _provider_rows(runtime.config())}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/providers/key")
    async def set_provider_key(request: ApiKeyRequest) -> dict[str, Any]:
        allowed = set(runtime.config().apis) | {"assistant", "gemini", "ollama"}
        if request.service not in allowed:
            raise HTTPException(status_code=400, detail=f"unknown API service: {request.service}")
        destination = SecretStore(runtime.config()).set(request.service, request.value)
        return {"ok": True, "destination": destination}

    @app.get("/api/operations")
    async def operations() -> list[dict[str, Any]]:
        return [item.payload() for item in runtime.operations.list()]

    @app.get("/api/operations/{operation_id}")
    async def operation_detail(operation_id: str) -> dict[str, Any]:
        operation = runtime.operations.get(operation_id)
        if not operation:
            raise HTTPException(status_code=404, detail="operation not found")
        return operation.payload()

    @app.post("/api/operations/{operation_id}/cancel")
    async def cancel_operation(operation_id: str) -> dict[str, Any]:
        return {"cancelled": await runtime.operations.cancel(operation_id)}

    @app.websocket("/ws/operations/{operation_id}")
    async def operation_socket(
        websocket: WebSocket, operation_id: str, token: str | None = None
    ) -> None:
        client = websocket.client.host if websocket.client else ""
        if not runtime.allow_remote and client not in {
            "127.0.0.1",
            "::1",
            "localhost",
            "testclient",
        }:
            await websocket.close(code=4403)
            return
        if runtime.access_token and not secrets.compare_digest(token or "", runtime.access_token):
            await websocket.close(code=4401)
            return
        operation = runtime.operations.get(operation_id)
        if not operation:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        queue = runtime.operations.subscribe(operation)
        try:
            await websocket.send_json({"type": "snapshot", "operation": operation.payload()})
            while True:
                event = await queue.get()
                await websocket.send_json(event)
                if operation.status in {"completed", "failed", "cancelled"} and queue.empty():
                    await websocket.send_json(
                        {"type": "snapshot", "operation": operation.payload()}
                    )
                    break
        except WebSocketDisconnect:
            pass
        finally:
            runtime.operations.unsubscribe(operation, queue)

    static_dir = Path(__file__).with_name(
        "static_discover" if ui_variant == "discover" else "static_workbench"
    )
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):  # type: ignore[no-untyped-def]
        if full_path.startswith("api/") or full_path.startswith("ws/"):
            raise HTTPException(status_code=404)

        # Vite places favicons and the web manifest at the static root rather
        # than under /assets. Serve a real file when one was requested, while
        # keeping path traversal outside the packaged UI directory impossible.
        static_root = static_dir.resolve()
        requested = (static_root / full_path).resolve()
        try:
            requested.relative_to(static_root)
        except ValueError:
            raise HTTPException(status_code=404) from None
        if full_path and requested.is_file():
            return FileResponse(requested)

        index = static_dir / "index.html"
        if not index.exists():
            return JSONResponse(
                {
                    "detail": f"{'MIA Discover' if ui_variant == 'discover' else 'MIA Workbench'} assets are not built. Run npm --prefix frontend-{ui_variant} run build."
                },
                status_code=503,
            )
        return FileResponse(index)

    return app
