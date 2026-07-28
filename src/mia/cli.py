from __future__ import annotations

import asyncio
import getpass
import json
import platform
import re
import shlex
import shutil
import sys
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.markup import escape
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from mia import __version__
from mia.assistant import InvestigationAssistant, write_analysis, write_summary
from mia.cache import ResultCache
from mia.config import (
    AppConfig,
    initialize_user_config,
    load_config,
    user_config_path,
)
from mia.db import ScanDatabase
from mia.deep_case import DeepCaseEngine, load_manifest, normalize_manifest, write_manifest
from mia.desktop import desktop_status, install_desktop_entries, remove_desktop_entries
from mia.exceptions import MIAError
from mia.graph import export_all_graph_formats
from mia.investigation import InvestigationEngine
from mia.knowledge import KnowledgeDatabase
from mia.logging_utils import configure_logging
from mia.models import (
    AnalysisDepth,
    CaseStatus,
    DeepCaseManifest,
    DeepCaseSeed,
    ReviewStatus,
    ScanProfile,
    TargetType,
)
from mia.orchestrator import Orchestrator
from mia.package_manager import (
    OperationResult,
    PackageError,
    PackageEvent,
    PackageManager,
    ToolPackage,
    host_summary,
)
from mia.platform_support import activate_managed_bin
from mia.plugin_sdk import CommunityPluginManager
from mia.registry import PluginRegistry
from mia.reports.dashboard import write_dashboard
from mia.secrets import SecretStore
from mia.targeting import classify_and_validate
from mia.utils import atomic_write_json, atomic_write_text
from mia.verification import IdentityClusterEngine, ProfileVerifier
from mia.workspace import CaseManager

console = Console()
error_console = Console(stderr=True)
app = typer.Typer(
    name="mia",
    help="MIA Core OSINT platform with Discover and Workbench interfaces.",
    no_args_is_help=True,
    invoke_without_command=True,
    rich_markup_mode="rich",
)
config_app = typer.Typer(help="Inspect or initialize MIA configuration.")
pkg_app = typer.Typer(
    help="Install, remove, update, and inspect optional OSINT tools.", no_args_is_help=True
)
case_app = typer.Typer(
    help="Create and manage persistent investigation cases.", no_args_is_help=True
)
api_app = typer.Typer(
    help="Configure API integrations without placing keys in YAML.", no_args_is_help=True
)
assistant_app = typer.Typer(
    help="Configure and inspect evidence-grounded AI assistant providers.", no_args_is_help=True
)
plugin_app = typer.Typer(
    help="Create, validate, install, and inspect community plugins.", no_args_is_help=True
)
knowledge_app = typer.Typer(
    help="Search the shared local investigation knowledge base.", no_args_is_help=True
)
cache_app = typer.Typer(
    help="Inspect or clear the local plugin-result cache.", no_args_is_help=True
)
desktop_app = typer.Typer(
    help="Install, inspect, or remove Linux desktop shortcuts.", no_args_is_help=True
)
discover_app = typer.Typer(
    help="Launch MIA Discover, the guided selector-search interface.",
    invoke_without_command=True,
)
workbench_app = typer.Typer(
    help="Launch MIA Workbench, the advanced investigation interface.",
    invoke_without_command=True,
)
app.add_typer(config_app, name="config")
app.add_typer(pkg_app, name="pkg")
app.add_typer(case_app, name="case")
app.add_typer(api_app, name="api")
app.add_typer(assistant_app, name="assistant")
app.add_typer(plugin_app, name="plugin")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(cache_app, name="cache")
app.add_typer(desktop_app, name="desktop")
app.add_typer(discover_app, name="discover")
app.add_typer(workbench_app, name="workbench")


@dataclass(slots=True)
class RuntimeOptions:
    config_path: Path | None
    verbose: bool


@app.callback()
def application(
    ctx: typer.Context,
    config_path: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Override the user configuration file."),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging."),
    ] = False,
    show_version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Print the MIA version and exit.",
            is_eager=True,
        ),
    ] = False,
) -> None:
    if show_version:
        console.print(__version__)
        raise typer.Exit()
    ctx.obj = RuntimeOptions(config_path=config_path, verbose=verbose)


def _services(ctx: typer.Context) -> tuple[AppConfig, PluginRegistry, ScanDatabase, Orchestrator]:
    options: RuntimeOptions = ctx.obj
    config = load_config(options.config_path)
    logger = configure_logging(config.paths.log_dir, options.verbose)
    registry = PluginRegistry.discover(config.paths.user_plugins_dir)
    database = ScanDatabase(config.paths.database_path)
    orchestrator = Orchestrator(config, registry, database, logger)
    return config, registry, database, orchestrator


def _render_scan_summary(result: object) -> None:
    table = Table(title=f"MIA scan {result.scan_id} · {result.profile.value} profile")
    table.add_column("Plugin")
    table.add_column("Status")
    table.add_column("Time", justify="right")
    table.add_column("Findings", justify="right")
    for run in result.plugin_runs:
        style = {
            "success": "green",
            "partial": "yellow",
            "failed": "red",
            "timed_out": "red",
            "unavailable": "red",
            "skipped": "dim",
            "cached": "cyan",
        }.get(run.status.value, "")
        table.add_row(
            run.plugin_name,
            f"[{style}]{run.status.value}[/{style}]" if style else run.status.value,
            f"{run.duration_seconds:.1f}s",
            str(len(run.findings)),
        )
    console.print(table)
    console.print(
        f"[bold green]{len(result.findings)} normalized findings[/bold green] in {result.duration_seconds:.1f}s"
    )
    if html := result.report_paths.get("html"):
        console.print(f"HTML report: [link=file://{html}]{html}[/link]")
    if json_path := result.report_paths.get("json"):
        console.print(f"JSON report: {json_path}")


def _resolve_profile(
    profile: ScanProfile | None,
    *,
    quick: bool,
    default_profile: bool,
    deep: bool,
    all_plugins: bool,
) -> ScanProfile:
    shortcuts = [
        selected
        for enabled, selected in (
            (quick, ScanProfile.QUICK),
            (default_profile, ScanProfile.DEFAULT),
            (deep, ScanProfile.DEEP),
            (all_plugins, ScanProfile.ALL),
        )
        if enabled
    ]
    if len(shortcuts) > 1:
        raise typer.BadParameter(
            "Choose only one of --quick, --default, --deep, or --all.",
            param_hint="scan profile",
        )
    if shortcuts and profile is not None:
        raise typer.BadParameter(
            "Use either --profile or one shortcut flag, not both.",
            param_hint="scan profile",
        )
    return shortcuts[0] if shortcuts else profile or ScanProfile.DEFAULT


def _execute_scan(
    ctx: typer.Context,
    target: str,
    target_type: TargetType,
    profile: ScanProfile,
    tools: list[str],
    exclude_tools: list[str],
    *,
    allow_empty: bool = False,
) -> None:
    try:
        validated_target, resolved_type = classify_and_validate(target, target_type)
        _, _, _, orchestrator = _services(ctx)
        tasks: dict[str, int] = {}
        with Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:

            def event(event_name: str, plugin_id: str, detail: str) -> None:
                if event_name == "start":
                    tasks[plugin_id] = progress.add_task(f"Running {detail}", total=None)
                elif plugin_id in tasks:
                    progress.update(tasks[plugin_id], description=f"{plugin_id}: {detail}")
                    progress.stop_task(tasks[plugin_id])

            result = asyncio.run(
                orchestrator.scan(
                    target=validated_target,
                    target_type=resolved_type,
                    profile=profile,
                    include=tools or None,
                    exclude=exclude_tools or None,
                    event_callback=event,
                )
            )
        _render_scan_summary(result)
        if result.successful_plugins == 0 and not allow_empty:
            error_console.print(
                "[bold red]Scan failed:[/bold red] no selected plugin completed successfully. "
                "Use --allow-empty only when this outcome is intentional."
            )
            raise typer.Exit(1)
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@app.command()
def scan(
    ctx: typer.Context,
    target: Annotated[
        str, typer.Argument(help="Username, email, domain, IP, phone, file, or hash.")
    ],
    target_type: Annotated[
        TargetType,
        typer.Option("--type", "-t", help="Target type. Defaults to automatic detection."),
    ] = TargetType.AUTO,
    profile: Annotated[
        ScanProfile | None,
        typer.Option(
            "--profile",
            "-p",
            help="Profile: quick, default, deep, or all. Defaults to default.",
        ),
    ] = None,
    quick: Annotated[bool, typer.Option("--quick", help="Use the fast quick profile.")] = False,
    default_profile: Annotated[
        bool,
        typer.Option("--default", help="Use the balanced default profile."),
    ] = False,
    deep: Annotated[bool, typer.Option("--deep", help="Use the broader deep profile.")] = False,
    all_plugins: Annotated[
        bool,
        typer.Option("--all", help="Use every compatible enabled plugin."),
    ] = False,
    tool: Annotated[
        list[str],
        typer.Option("--tool", help="Run only this plugin; repeat for multiple plugins."),
    ] = None,
    exclude_tool: Annotated[
        list[str],
        typer.Option("--exclude-tool", help="Exclude this plugin; repeat as needed."),
    ] = None,
    allow_empty: Annotated[
        bool,
        typer.Option(
            "--allow-empty",
            help="Exit successfully even when no plugin completes successfully.",
        ),
    ] = False,
) -> None:
    """Run a scan with automatic target classification."""
    if exclude_tool is None:
        exclude_tool = []
    if tool is None:
        tool = []
    selected_profile = _resolve_profile(
        profile,
        quick=quick,
        default_profile=default_profile,
        deep=deep,
        all_plugins=all_plugins,
    )
    _execute_scan(
        ctx,
        target,
        target_type,
        selected_profile,
        tool,
        exclude_tool,
        allow_empty=allow_empty,
    )


def _typed_scan_command(target_type: TargetType):
    def command(
        ctx: typer.Context,
        target: Annotated[str, typer.Argument()],
        profile: Annotated[
            ScanProfile | None,
            typer.Option(
                "--profile",
                "-p",
                help="Profile: quick, default, deep, or all. Defaults to default.",
            ),
        ] = None,
        quick: Annotated[bool, typer.Option("--quick", help="Use the fast quick profile.")] = False,
        default_profile: Annotated[
            bool,
            typer.Option("--default", help="Use the balanced default profile."),
        ] = False,
        deep: Annotated[bool, typer.Option("--deep", help="Use the broader deep profile.")] = False,
        all_plugins: Annotated[
            bool,
            typer.Option("--all", help="Use every compatible enabled plugin."),
        ] = False,
        tool: Annotated[list[str], typer.Option("--tool")] = None,
        exclude_tool: Annotated[list[str], typer.Option("--exclude-tool")] = None,
        allow_empty: Annotated[
            bool,
            typer.Option(
                "--allow-empty",
                help="Exit successfully even when no plugin completes successfully.",
            ),
        ] = False,
    ) -> None:
        if exclude_tool is None:
            exclude_tool = []
        if tool is None:
            tool = []
        selected_profile = _resolve_profile(
            profile,
            quick=quick,
            default_profile=default_profile,
            deep=deep,
            all_plugins=all_plugins,
        )
        _execute_scan(
            ctx,
            target,
            target_type,
            selected_profile,
            tool,
            exclude_tool,
            allow_empty=allow_empty,
        )

    return command


app.command("search", help="Search a username (compatibility alias).")(
    _typed_scan_command(TargetType.USERNAME)
)
app.command("username", help="Scan a username.")(_typed_scan_command(TargetType.USERNAME))
app.command("email", help="Scan an email address.")(_typed_scan_command(TargetType.EMAIL))
app.command("domain", help="Scan a domain name.")(_typed_scan_command(TargetType.DOMAIN))
app.command("ip", help="Scan an IP address.")(_typed_scan_command(TargetType.IP))
app.command("phone", help="Scan a phone number.")(_typed_scan_command(TargetType.PHONE))
app.command("image", help="Extract metadata from an image or media file.")(
    _typed_scan_command(TargetType.FILE)
)
app.command("file", help="Extract metadata from a file.")(_typed_scan_command(TargetType.FILE))
app.command("hash", help="Identify possible hash algorithms locally.")(
    _typed_scan_command(TargetType.HASH)
)


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _action_gerund(action: str) -> str:
    return {
        "install": "Installing",
        "uninstall": "Uninstalling",
        "update": "Updating",
    }.get(action, f"{action.title()}ing")


class _PackageProgressDisplay:
    """Render package operations without making quiet builds look frozen."""

    def __init__(
        self,
        *,
        action: str,
        total: int,
        verbose: bool,
        quiet: bool,
    ) -> None:
        self.action = action
        self.total = total
        self.verbose = verbose
        self.quiet = quiet
        self.interactive = console.is_terminal
        self.current_index = 0
        self.current_name = ""
        self._last_plain_heartbeat = 0.0
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            TextColumn("{task.fields[detail]}", justify="left"),
            TimeElapsedColumn(),
            console=console,
            refresh_per_second=10,
            transient=False,
        )
        self.overall_task = self.progress.add_task(
            f"[bold]{_action_gerund(action)} OSINT tools[/bold]",
            total=total,
            detail=f"0/{total} complete",
        )
        self.current_task = self.progress.add_task(
            "Waiting",
            total=None,
            detail="",
            visible=not quiet,
        )

    def __enter__(self) -> _PackageProgressDisplay:
        if self.interactive:
            self.progress.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.interactive:
            self.progress.stop()

    @staticmethod
    def _clean(message: str, limit: int = 110) -> str:
        cleaned = _ANSI_RE.sub("", message).replace("\r", " ").strip()
        cleaned = " ".join(cleaned.split())
        if len(cleaned) > limit:
            cleaned = "…" + cleaned[-(limit - 1) :]
        return cleaned

    def begin_tool(self, index: int, tool: ToolPackage) -> None:
        self.current_index = index
        self.current_name = tool.name
        label = f"[{index}/{self.total}] {_action_gerund(self.action)} {tool.name}"
        if self.interactive:
            self.progress.update(
                self.current_task,
                description=label,
                total=None,
                completed=0,
                detail="Preparing…",
                visible=not self.quiet,
            )
        elif not self.quiet:
            console.print(f"[bold cyan]{label}[/bold cyan]")

    def handle_event(self, event: PackageEvent) -> None:
        detail = self._clean(event.message)
        if event.kind == "command_start" and event.command:
            detail = self._clean(f"Running {shlex.join(event.command)}")
        elif event.kind == "heartbeat":
            detail = f"Still working… {event.elapsed_seconds:.0f}s elapsed"
        elif event.kind == "command_end" and event.return_code == 0:
            detail = "Command completed"
        elif event.kind == "command_end" and event.return_code not in (None, 0):
            detail = f"Command failed (exit {event.return_code})"

        if self.interactive:
            if not self.quiet and detail:
                self.progress.update(self.current_task, detail=escape(detail))
            if self.verbose and event.kind == "output" and detail:
                self.progress.console.print(
                    f"[dim]{escape(event.tool_id or self.current_name)}[/dim] {escape(detail)}"
                )
            return

        if self.verbose and event.kind == "output" and detail:
            console.print(
                f"[dim]{escape(event.tool_id or self.current_name)}[/dim] {escape(detail)}"
            )
        elif event.kind == "heartbeat" and not self.quiet:
            now = time.monotonic()
            if now - self._last_plain_heartbeat >= 3:
                console.print(f"  [dim]{escape(detail)}[/dim]")
                self._last_plain_heartbeat = now

    def finish_tool(self, result: OperationResult) -> None:
        icon = "[green]✓[/green]" if result.success else "[red]✗[/red]"
        detail = self._clean(result.message)
        if self.interactive:
            self.progress.advance(self.overall_task, 1)
            completed = int(self.progress.tasks[self.overall_task].completed)
            self.progress.update(
                self.overall_task,
                detail=f"{completed}/{self.total} complete",
            )
            if not self.quiet:
                self.progress.update(
                    self.current_task,
                    description=f"{icon} [{self.current_index}/{self.total}] {self.current_name}",
                    total=1,
                    completed=1,
                    detail=escape(detail),
                )
        elif not self.quiet:
            console.print(f"  {icon} {escape(detail)} ({result.duration_seconds:.1f}s)")


def _pkg_manager(
    *,
    dry_run: bool = False,
    no_system: bool = False,
    package_manager: str | None = None,
) -> PackageManager:
    return PackageManager(
        dry_run=dry_run,
        allow_system=not no_system,
        package_manager=package_manager,
    )


def _select_packages(
    manager: PackageManager,
    tools: list[str],
    groups: list[str],
    all_tools: bool,
    include_mixed: bool,
) -> list[ToolPackage]:
    if all_tools:
        if tools or groups:
            raise PackageError("--all cannot be combined with explicit tools or --group")
        return manager.all_tools(include_mixed=include_mixed)
    return manager.resolve(tools, groups)


def _render_package_results(results: list[OperationResult], *, show_commands: bool = False) -> None:
    table = Table(title="MIA package operations")
    table.add_column("Tool")
    table.add_column("Action")
    table.add_column("Result")
    table.add_column("Duration", justify="right")
    table.add_column("Message")
    for result in results:
        outcome_styles = {
            "installed": "green",
            "updated": "green",
            "removed": "green",
            "already-present": "cyan",
            "planned": "cyan",
            "skipped": "yellow",
            "preserved": "yellow",
            "interrupted": "yellow",
            "failed": "red",
        }
        style = outcome_styles.get(result.outcome, "green" if result.success else "red")
        table.add_row(
            result.tool_id,
            result.action,
            f"[{style}]{escape(result.outcome)}[/{style}]",
            f"{result.duration_seconds:.1f}s",
            escape(result.message),
        )
    console.print(table)
    counts: dict[str, int] = {}
    for result in results:
        counts[result.outcome] = counts.get(result.outcome, 0) + 1
    summary = " · ".join(f"{name}: {count}" for name, count in sorted(counts.items()))
    if summary:
        console.print(f"[bold]Summary:[/bold] {summary}")
    logs = {result.log_path for result in results if result.log_path}
    if logs:
        common = Path(next(iter(logs))).parent
        console.print(f"Detailed package logs: [cyan]{common}[/cyan]")
    if show_commands:
        for result in results:
            commands = getattr(result, "commands", [])
            if not commands:
                continue
            console.print(f"[bold]{result.tool_id}[/bold] planned commands:")
            for command in commands:
                console.print(f"  [dim]{shlex.join(command)}[/dim]", soft_wrap=True)


@pkg_app.command("list")
def pkg_list(
    installed: Annotated[
        bool, typer.Option("--installed", help="Show only available tools.")
    ] = False,
    group: Annotated[
        str | None, typer.Option("--group", "-g", help="Filter by catalog group.")
    ] = None,
    integrated: Annotated[
        bool, typer.Option("--integrated", help="Hide managed-only tools.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    """List the optional OSINT tool catalog and installation state."""
    try:
        manager = _pkg_manager()
        rows = manager.inventory()
        if group:
            allowed = {tool.tool_id for tool in manager.resolve(groups=[group])}
            rows = [row for row in rows if row["id"] in allowed]
        if installed:
            rows = [row for row in rows if row["installed"]]
        if integrated:
            rows = [row for row in rows if row["integration"] != "managed-only"]
        if as_json:
            console.print_json(json.dumps(rows))
            return
        table = Table(title=f"MIA OSINT package catalog ({len(rows)} tools)")
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Categories")
        table.add_column("Integration")
        table.add_column("Risk")
        table.add_column("Installed")
        table.add_column("Setup")
        for row in rows:
            setup = []
            if row["setup_required"]:
                setup.append("manual")
            if row["api_keys"]:
                setup.append("API key")
            if row["unmaintained"]:
                setup.append("unmaintained")
            table.add_row(
                row["id"],
                row["name"],
                ", ".join(row["categories"]),
                row["integration"],
                row["risk"],
                "[green]yes[/green]" if row["installed"] else "[dim]no[/dim]",
                ", ".join(setup) or "—",
            )
        console.print(table)
        console.print("Use [bold]mia pkg info TOOL[/bold] for details and upstream links.")
    except PackageError as exc:
        error_console.print(f"[bold red]Package error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@pkg_app.command("groups")
def pkg_groups() -> None:
    """List curated package groups."""
    manager = _pkg_manager()
    table = Table(title="MIA package groups")
    table.add_column("Group")
    table.add_column("Tools", justify="right")
    table.add_column("Members")
    for name, members in sorted(manager.catalog.groups.items()):
        table.add_row(name, str(len(members)), ", ".join(members))
    console.print(table)


@pkg_app.command("info")
def pkg_info(
    tool_id: Annotated[str, typer.Argument(help="Catalog tool ID.")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show installation, integration, risk, and setup details for one tool."""
    try:
        manager = _pkg_manager()
        tool = manager.resolve([tool_id])[0]
        installed, executable, source = manager.status(tool)
        payload = {
            **tool.model_dump(mode="json"),
            "installed": installed,
            "detected_executable": executable,
            "detected_via": source,
        }
        if as_json:
            console.print_json(json.dumps(payload))
            return
        console.print(f"[bold]{tool.name}[/bold] ([cyan]{tool.tool_id}[/cyan])")
        console.print(tool.description)
        console.print(f"Homepage: {tool.homepage}")
        console.print(f"License: {tool.license}")
        console.print(f"Categories: {', '.join(tool.categories)}")
        console.print(f"Targets: {', '.join(tool.target_types) or 'standalone framework'}")
        console.print(f"MIA integration: {tool.integration}")
        console.print(f"Network behavior: {tool.risk}")
        console.print(f"Install method: {tool.install.kind}")
        console.print(
            f"Installed: {'yes' if installed else 'no'}{f' ({executable})' if executable else ''}"
        )
        if tool.api_keys:
            console.print(f"API credentials commonly used: {', '.join(tool.api_keys)}")
        if tool.setup_required:
            console.print(
                "[yellow]Additional upstream setup or authentication is required.[/yellow]"
            )
        if tool.unmaintained:
            console.print(
                "[yellow]Upstream currently describes this project as unmaintained.[/yellow]"
            )
    except PackageError as exc:
        error_console.print(f"[bold red]Package error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


def _package_operation(
    ctx: typer.Context,
    action: str,
    tools: list[str],
    groups: list[str],
    all_tools: bool,
    include_mixed: bool,
    yes: bool,
    dry_run: bool,
    no_system: bool,
    package_manager: str | None,
    quiet: bool,
    remove_system_packages: bool = False,
) -> None:
    try:
        manager = _pkg_manager(
            dry_run=dry_run, no_system=no_system, package_manager=package_manager
        )
        selected = _select_packages(manager, tools, groups, all_tools, include_mixed)
        mixed = [tool.tool_id for tool in selected if tool.risk == "mixed"]
        if mixed and not include_mixed:
            raise PackageError(
                "mixed/direct-request tools require --include-mixed: " + ", ".join(mixed)
            )
        if not yes and not dry_run:
            console.print(
                f"Selected {len(selected)} tool(s): {', '.join(tool.tool_id for tool in selected)}"
            )
            if mixed:
                console.print(
                    "[yellow]Mixed tools can make direct DNS/HTTP requests: "
                    + ", ".join(mixed)
                    + "[/yellow]"
                )
            if not typer.confirm(f"Proceed with package {action}?"):
                raise typer.Abort()
        options: RuntimeOptions = ctx.obj
        if quiet and options.verbose:
            raise PackageError("--quiet cannot be combined with the global --verbose option")
        results: list[OperationResult] = []
        interrupted = False
        with _PackageProgressDisplay(
            action=action,
            total=len(selected),
            verbose=options.verbose,
            quiet=quiet,
        ) as display:
            manager.set_event_handler(display.handle_event)
            for index, tool in enumerate(selected, start=1):
                display.begin_tool(index, tool)
                started = time.monotonic()
                try:
                    if action == "install":
                        result = manager.install(tool)
                    elif action == "uninstall":
                        result = manager.uninstall(tool, remove_system=remove_system_packages)
                    elif action == "update":
                        result = manager.update(tool)
                    else:
                        raise PackageError(f"unsupported package action: {action}")
                except KeyboardInterrupt:
                    result = OperationResult(
                        tool_id=tool.tool_id,
                        action=action,
                        success=False,
                        message="interrupted by user",
                        outcome="interrupted",
                        log_path=(
                            str(manager.active_log_path) if manager.active_log_path else None
                        ),
                    )
                    interrupted = True
                except PackageError as exc:
                    result = OperationResult(
                        tool_id=tool.tool_id,
                        action=action,
                        success=False,
                        message=str(exc),
                        outcome="failed",
                        log_path=(
                            str(manager.active_log_path) if manager.active_log_path else None
                        ),
                    )
                result.duration_seconds = time.monotonic() - started
                results.append(result)
                display.finish_tool(result)
                if interrupted:
                    for skipped in selected[index:]:
                        skipped_result = OperationResult(
                            tool_id=skipped.tool_id,
                            action=action,
                            success=False,
                            message="not started because the operation was interrupted",
                            outcome="skipped",
                        )
                        results.append(skipped_result)
                        display.begin_tool(len(results), skipped)
                        display.finish_tool(skipped_result)
                    break
        _render_package_results(results, show_commands=dry_run)
        if dry_run:
            console.print("[cyan]Dry run only; no files or packages were changed.[/cyan]")
        if any(not result.success for result in results):
            raise typer.Exit(130 if interrupted else 1)
    except PackageError as exc:
        error_console.print(f"[bold red]Package error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@pkg_app.command("install")
def pkg_install(
    ctx: typer.Context,
    tools: Annotated[list[str], typer.Argument(help="Tool IDs to install.")] = None,
    group: Annotated[
        list[str], typer.Option("--group", "-g", help="Install a curated group.")
    ] = None,
    all_tools: Annotated[
        bool, typer.Option("--all", help="Install all local/passive tools.")
    ] = False,
    include_mixed: Annotated[
        bool,
        typer.Option("--include-mixed", help="Include tools that make broader active requests."),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    no_system: Annotated[
        bool, typer.Option("--no-system", help="Do not use sudo or a system package manager.")
    ] = False,
    package_manager: Annotated[
        str | None,
        typer.Option("--package-manager", help="Override apt/dnf/pacman/zypper/apk/brew."),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Show only overall progress and the final summary."),
    ] = False,
) -> None:
    """Install selected OSINT tools into isolated, user-owned locations."""
    _package_operation(
        ctx,
        "install",
        tools or [],
        group or [],
        all_tools,
        include_mixed,
        yes,
        dry_run,
        no_system,
        package_manager,
        quiet,
    )


@pkg_app.command("uninstall")
def pkg_uninstall(
    ctx: typer.Context,
    tools: Annotated[list[str], typer.Argument(help="Tool IDs to remove.")] = None,
    group: Annotated[list[str], typer.Option("--group", "-g")] = None,
    all_tools: Annotated[bool, typer.Option("--all", help="Remove all MIA-managed tools.")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    remove_system_packages: Annotated[
        bool,
        typer.Option(
            "--remove-system-packages",
            help="Also remove packages installed through the host package manager.",
        ),
    ] = False,
    package_manager: Annotated[str | None, typer.Option("--package-manager")] = None,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Show only overall progress and the final summary."),
    ] = False,
) -> None:
    """Remove MIA-managed tool environments; preserve system packages by default."""
    _package_operation(
        ctx,
        "uninstall",
        tools or [],
        group or [],
        all_tools,
        True,
        yes,
        dry_run,
        False,
        package_manager,
        quiet,
        remove_system_packages,
    )


@pkg_app.command("update")
def pkg_update(
    ctx: typer.Context,
    tools: Annotated[list[str], typer.Argument(help="Tool IDs to reinstall/update.")] = None,
    group: Annotated[list[str], typer.Option("--group", "-g")] = None,
    all_tools: Annotated[bool, typer.Option("--all")] = False,
    include_mixed: Annotated[bool, typer.Option("--include-mixed")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    no_system: Annotated[bool, typer.Option("--no-system")] = False,
    package_manager: Annotated[str | None, typer.Option("--package-manager")] = None,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Show only overall progress and the final summary."),
    ] = False,
) -> None:
    """Update selected MIA-managed tools using their catalog recipes."""
    _package_operation(
        ctx,
        "update",
        tools or [],
        group or [],
        all_tools,
        include_mixed,
        yes,
        dry_run,
        no_system,
        package_manager,
        quiet,
    )


@pkg_app.command("doctor")
def pkg_doctor(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Diagnose package runtimes, state, and all catalog entries."""
    manager = _pkg_manager()
    payload = {
        "host": host_summary(),
        "state": str(manager.state_path),
        "tools": manager.inventory(),
    }
    if as_json:
        console.print_json(json.dumps(payload))
        return
    console.print(f"Package manager: [bold]{manager.package_manager}[/bold]")
    console.print(f"Managed state: {manager.state_path}")
    console.print(f"Managed tools: {manager.tools_dir}")
    console.print(f"Command links: {manager.bin_dir}")
    ready = sum(1 for row in payload["tools"] if row["installed"])
    console.print(f"Available catalog tools: [green]{ready}[/green] / {len(payload['tools'])}")
    missing_runtimes = [name for name in ("git", "go", "cargo", "uv") if shutil.which(name) is None]
    if missing_runtimes:
        console.print(f"Optional runtimes not currently on PATH: {', '.join(missing_runtimes)}")
    console.print("Run [bold]mia pkg list --installed[/bold] for the installed inventory.")


@desktop_app.command("install")
def desktop_install(
    command: Annotated[
        Path | None,
        typer.Option(
            "--command",
            help="Absolute mia launcher path. Normally detected automatically.",
        ),
    ] = None,
) -> None:
    """Install Discover and Workbench launchers for the current Linux user."""
    try:
        status = install_desktop_entries(command)
        console.print(f"[green]Installed desktop shortcuts[/green] in {status.applications_dir}")
        console.print(
            "Open [bold]MIA Discover[/bold] or [bold]MIA Workbench[/bold] from your application menu."
        )
    except (OSError, RuntimeError) as exc:
        error_console.print(f"[bold red]Desktop integration error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@desktop_app.command("status")
def desktop_show_status(
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    """Show whether the Linux application-menu shortcuts are installed."""
    status = desktop_status()
    payload = {
        "supported": status.supported,
        "applications_dir": str(status.applications_dir),
        "icons_dir": str(status.icons_dir),
        "command": str(status.command) if status.command else None,
        "discover_installed": status.discover_installed,
        "workbench_installed": status.workbench_installed,
    }
    if as_json:
        console.print_json(json.dumps(payload))
        return
    console.print(f"Desktop integration supported: {'yes' if status.supported else 'no'}")
    console.print(
        f"MIA Discover shortcut: {'[green]installed[/green]' if status.discover_installed else '[yellow]missing[/yellow]'}"
    )
    console.print(
        f"MIA Workbench shortcut: {'[green]installed[/green]' if status.workbench_installed else '[yellow]missing[/yellow]'}"
    )
    console.print(f"Application entries: {status.applications_dir}")


@desktop_app.command("remove")
def desktop_remove() -> None:
    """Remove MIA's application-menu shortcuts without removing MIA or its cases."""
    try:
        remove_desktop_entries()
        console.print("[green]Removed MIA desktop shortcuts.[/green]")
    except OSError as exc:
        error_console.print(f"[bold red]Desktop integration error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@app.command("repair")
def repair_installation(
    ctx: typer.Context,
    install_tools: Annotated[
        bool,
        typer.Option(
            "--install-tools",
            help="Install or repair the recommended core OSINT tool group.",
        ),
    ] = False,
    desktop: Annotated[
        bool,
        typer.Option(
            "--desktop/--no-desktop",
            help="Repair Linux application-menu shortcuts.",
        ),
    ] = True,
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    no_system: Annotated[
        bool,
        typer.Option("--no-system", help="Do not use sudo or a system package manager."),
    ] = False,
    package_manager: Annotated[
        str | None, typer.Option("--package-manager", help="Override the detected package manager.")
    ] = None,
) -> None:
    """Repair launchers and optionally reinstall MIA's recommended tool set."""
    failures: list[str] = []
    try:
        config, registry, database, _ = _services(ctx)
        for path in (config.paths.state_dir, config.paths.log_dir, config.paths.cases_dir):
            path.mkdir(parents=True, exist_ok=True)
        with database.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        from importlib.resources import files

        for relative in (
            "web/static_discover/index.html",
            "web/static_workbench/index.html",
            "web/static_discover/mia-discover-icon.svg",
            "web/static_workbench/mia-workbench-icon.svg",
        ):
            if not files("mia").joinpath(relative).is_file():
                failures.append(f"missing packaged asset: {relative}")
        if desktop and sys.platform.startswith("linux"):
            install_desktop_entries()
            console.print("[green]Desktop shortcuts repaired.[/green]")
        statuses = {plugin.plugin_id: plugin.detect(config).available for plugin in registry.all()}
        ready = sum(1 for value in statuses.values() if value)
        console.print(
            f"Core application: [green]ready[/green] · integrated plugins ready: {ready}/{len(statuses)}"
        )
    except (MIAError, OSError, RuntimeError) as exc:
        failures.append(str(exc))

    if install_tools:
        _package_operation(
            ctx,
            "install",
            [],
            ["windows-core" if sys.platform.startswith("win") else "core"],
            False,
            False,
            yes,
            False,
            no_system,
            package_manager,
            False,
        )

    if failures:
        for failure in failures:
            error_console.print(f"[red]Repair check failed:[/red] {failure}")
        raise typer.Exit(1)
    console.print("[bold green]MIA installation check completed.[/bold green]")
    if not install_tools:
        console.print(
            "Run [bold]mia repair --install-tools --yes[/bold] to repair recommended scanners too."
        )


@app.command("profiles")
def list_profiles(ctx: typer.Context) -> None:
    """Show scan profiles, their purpose, and configured plugin sets."""
    try:
        config, _, _, _ = _services(ctx)
        table = Table(title="MIA scan profiles")
        table.add_column("Profile")
        table.add_column("Purpose")
        table.add_column("Configured plugins")
        for profile in ScanProfile:
            configured = config.profiles.get(profile.value, ["*"])
            table.add_row(profile.value, profile.description, ", ".join(configured))
        console.print(table)
        console.print(
            "Examples: [bold]mia scan TARGET --quick[/bold], "
            "[bold]mia scan TARGET[/bold], or [bold]mia scan TARGET --deep[/bold]"
        )
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@app.command("plugins")
def list_plugins(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    """List discovered plugins and dependency status."""
    try:
        config, registry, _, _ = _services(ctx)
        statuses = [plugin.detect(config) for plugin in registry.all()]
        if as_json:
            console.print_json(json.dumps([item.model_dump(mode="json") for item in statuses]))
            return
        table = Table(title="MIA plugins")
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Targets")
        table.add_column("Available")
        table.add_column("Version / note")
        for plugin, status in zip(registry.all(), statuses, strict=True):
            table.add_row(
                plugin.plugin_id,
                plugin.name,
                ", ".join(sorted(item.value for item in plugin.target_types)),
                "[green]yes[/green]" if status.available else "[red]no[/red]",
                status.version or status.message,
            )
        console.print(table)
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Check MIA paths, Python, database, and external tool availability."""
    try:
        config, registry, database, _ = _services(ctx)
        console.print(f"MIA version: [bold]{__version__}[/bold]")
        console.print(f"Python: {platform.python_version()} ({sys.executable})")
        console.print(f"Configuration: {config.loaded_from or '[packaged defaults]'}")
        console.print(f"Legacy reports: {config.paths.output_dir}")
        console.print(f"Cases: {config.paths.cases_dir}")
        console.print(f"Scan database: {database.path}")
        console.print(f"Knowledge database: {config.paths.knowledge_database_path}")
        console.print(f"Cache database: {config.paths.cache_database_path}")
        console.print(f"Community plugins: {config.paths.user_plugins_dir}")
        table = Table(title="Tool diagnostics")
        table.add_column("Plugin")
        table.add_column("Status")
        table.add_column("Executable")
        table.add_column("Version / guidance")
        for plugin in registry.all():
            status = plugin.detect(config)
            table.add_row(
                plugin.plugin_id,
                "[green]ready[/green]"
                if status.available
                else "[yellow]optional / unavailable[/yellow]",
                status.executable or "—",
                status.version or status.message or status.install_hint or "—",
            )
        console.print(table)
        api_table = Table(title="Passive API integrations")
        api_table.add_column("Service")
        api_table.add_column("Enabled")
        api_table.add_column("Credential source")
        store = SecretStore(config)
        for service, settings in sorted(config.apis.items()):
            api_table.add_row(
                service,
                "[green]yes[/green]" if settings.enabled else "[dim]no[/dim]",
                store.source(service),
            )
        console.print(api_table)
        console.print(
            "Unavailable external tools and disabled APIs are optional; scans use only compatible configured plugins."
        )
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@app.command()
def history(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, max=500)] = 20,
    target: Annotated[
        str | None, typer.Option("--target", help="Filter by target substring.")
    ] = None,
) -> None:
    """Show stored scan history."""
    try:
        _, _, database, _ = _services(ctx)
        rows = database.history(limit=limit, target=target)
        table = Table(title="MIA scan history")
        table.add_column("Scan ID")
        table.add_column("Started")
        table.add_column("Target")
        table.add_column("Type")
        table.add_column("Profile")
        table.add_column("Findings", justify="right")
        for row in rows:
            table.add_row(
                row["scan_id"],
                row["started_at"],
                row["target"],
                row["target_type"],
                row["profile"],
                str(row["finding_count"]),
            )
        console.print(table)
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@app.command()
def show(
    ctx: typer.Context,
    scan_id: Annotated[str, typer.Argument(help="Full scan ID or an unambiguous prefix.")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show a stored scan."""
    try:
        _, _, database, _ = _services(ctx)
        result = database.load(scan_id)
        if as_json:
            console.print_json(result.model_dump_json())
        else:
            _render_scan_summary(result)
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@app.command()
def compare(
    ctx: typer.Context,
    first_scan: Annotated[str, typer.Argument()],
    second_scan: Annotated[str, typer.Argument()],
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Compare normalized findings from two stored scans."""
    try:
        _, _, database, _ = _services(ctx)
        diff = database.compare(first_scan, second_scan)
        if output:
            atomic_write_json(output.expanduser(), diff)
            console.print(f"Comparison written to {output.expanduser()}")
        table = Table(title=f"{diff['first_scan']} → {diff['second_scan']}")
        table.add_column("Change")
        table.add_column("Count", justify="right")
        table.add_row("Added", str(len(diff["added"])))
        table.add_row("Removed", str(len(diff["removed"])))
        table.add_row("Changed corroboration/confidence", str(len(diff["changed"])))
        table.add_row("Unchanged", str(diff["unchanged_count"]))
        console.print(table)
        if not diff["target_matches"]:
            console.print("[yellow]Warning: the scans have different targets.[/yellow]")
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@app.command()
def update(ctx: typer.Context) -> None:
    """Show installed tool versions and safe update guidance without modifying the system."""
    try:
        config, registry, _, _ = _services(ctx)
        table = Table(title="External tool update guidance")
        table.add_column("Tool")
        table.add_column("Installed version")
        table.add_column("Guidance")
        for plugin in registry.all():
            status = plugin.detect(config)
            if plugin.network_required or status.executable:
                table.add_row(
                    plugin.name,
                    status.version or ("installed" if status.available else "not detected"),
                    status.install_hint
                    or "Follow the upstream project's documented update procedure.",
                )
        console.print(table)
        console.print(
            "Use 'mia pkg update TOOL' for catalog-managed tools. MIA never updates them silently."
        )
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


def _case_services(
    ctx: typer.Context,
) -> tuple[AppConfig, CaseManager, KnowledgeDatabase, InvestigationEngine]:
    config, _, _, orchestrator = _services(ctx)
    options: RuntimeOptions = ctx.obj
    logger = configure_logging(config.paths.log_dir, options.verbose)
    manager = CaseManager(config.paths.cases_dir)
    knowledge = KnowledgeDatabase(config.paths.knowledge_database_path)
    engine = InvestigationEngine(config, orchestrator, knowledge, logger)
    return config, manager, knowledge, engine


def _progress_callback(progress: Progress, tasks: dict[str, int]):
    def event(event_name: str, plugin_id: str, detail: str) -> None:
        if event_name == "start":
            tasks[plugin_id] = progress.add_task(f"Running {detail}", total=None)
        elif plugin_id in tasks:
            progress.update(tasks[plugin_id], description=f"{plugin_id}: {detail}")
            progress.stop_task(tasks[plugin_id])

    return event


@app.command()
def investigate(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="Root target for a persistent investigation case.")],
    target_type: Annotated[
        TargetType,
        typer.Option("--type", "-t", help="Target type. Defaults to automatic detection."),
    ] = TargetType.AUTO,
    case: Annotated[
        str | None,
        typer.Option("--case", help="Append to an existing case ID, prefix, slug, or exact name."),
    ] = None,
    name: Annotated[
        str | None,
        typer.Option("--name", help="Name for a newly created case."),
    ] = None,
    profile: Annotated[
        ScanProfile,
        typer.Option("--profile", "-p", help="Root scan profile."),
    ] = ScanProfile.DEFAULT,
    pivot: Annotated[
        bool,
        typer.Option("--pivot", help="Enable automatic investigation of explicit indicators."),
    ] = False,
    no_pivot: Annotated[
        bool,
        typer.Option("--no-pivot", help="Disable pivoting even when enabled in configuration."),
    ] = False,
    max_depth: Annotated[
        int | None,
        typer.Option("--max-depth", min=0, max=8, help="Maximum automatic-pivot depth."),
    ] = None,
    max_targets: Annotated[
        int | None,
        typer.Option("--max-targets", min=1, max=500, help="Maximum unique automatic targets."),
    ] = None,
    tool: Annotated[
        list[str], typer.Option("--tool", help="Restrict the root scan to a plugin.")
    ] = None,
    exclude_tool: Annotated[
        list[str], typer.Option("--exclude-tool", help="Exclude a plugin from all scans.")
    ] = None,
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Do not read or write plugin result cache entries.")
    ] = False,
) -> None:
    """Create or update a case, build its graph, timeline, correlations, and dashboard."""
    try:
        if case is not None and not case.strip():
            raise typer.BadParameter("--case cannot be blank", param_hint="--case")
        if pivot and no_pivot:
            raise typer.BadParameter("choose either --pivot or --no-pivot, not both")
        pivot_override = True if pivot else False if no_pivot else None
        validated_target, resolved_type = classify_and_validate(target, target_type)
        _, _, _, engine = _case_services(ctx)
        tasks: dict[str, int] = {}
        with Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            result = asyncio.run(
                engine.investigate(
                    validated_target,
                    resolved_type,
                    profile,
                    case_identifier=case,
                    case_name=name,
                    enable_pivoting=pivot_override,
                    max_depth=max_depth,
                    max_targets=max_targets,
                    include=tool or None,
                    exclude=exclude_tool or None,
                    event_callback=_progress_callback(progress, tasks),
                    use_cache=False if no_cache else None,
                )
            )
        workspace = result.workspace
        console.print(
            f"[bold green]Case updated:[/bold green] {workspace.record.name} "
            f"([cyan]{workspace.record.case_id}[/cyan])"
        )
        console.print(
            f"Scans: {len(result.scans)} · Nodes: {len(workspace.nodes())} · "
            f"Edges: {len(workspace.edges())} · Correlations: {len(result.correlations)}"
        )
        if result.skipped_pivots:
            console.print(f"[yellow]Skipped pivots:[/yellow] {len(result.skipped_pivots)}")
        if result.dashboard_path:
            console.print(
                f"Dashboard: [link=file://{result.dashboard_path}]{result.dashboard_path}[/link]"
            )
        console.print(f"Workspace: {workspace.root}")
    except (MIAError, ValueError) as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


def _deep_seed_values(values: list[str] | None, target_type: TargetType) -> list[DeepCaseSeed]:
    return [
        DeepCaseSeed(target=value, target_type=target_type)
        for value in (values or [])
        if value.strip()
    ]


async def _run_deep_case(
    ctx: typer.Context,
    manifest: DeepCaseManifest,
    *,
    case_identifier: str | None,
    profile: ScanProfile,
    no_verify: bool,
    no_pivot: bool,
    max_depth: int | None,
    max_targets: int | None,
    tools: list[str] | None,
    exclude_tools: list[str] | None,
    no_cache: bool,
):
    config, registry, database, orchestrator = _services(ctx)
    logger = configure_logging(config.paths.log_dir, ctx.obj.verbose)
    knowledge = KnowledgeDatabase(config.paths.knowledge_database_path)
    engine = DeepCaseEngine(config, orchestrator, knowledge, logger)
    tasks: dict[str, int] = {}
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        return await engine.run(
            manifest,
            case_identifier=case_identifier,
            profile=profile,
            verify_profiles=not no_verify,
            enable_pivoting=not no_pivot,
            max_depth=max_depth,
            max_targets=max_targets,
            include=tools or None,
            exclude=exclude_tools or None,
            event_callback=_progress_callback(progress, tasks),
            use_cache=False if no_cache else None,
        )


@app.command("deeps")
def deeps(
    ctx: typer.Context,
    manifest_path: Annotated[
        Path | None,
        typer.Argument(help="Optional YAML/JSON deep-case manifest."),
    ] = None,
    name: Annotated[str | None, typer.Option("--name", help="Case name.")] = None,
    case_identifier: Annotated[
        str | None,
        typer.Option("--case", help="Append this batch of seeds to an existing case."),
    ] = None,
    description: Annotated[str, typer.Option("--description")] = "",
    workflow: Annotated[
        str | None,
        typer.Option(
            "--workflow", help="identity, general, email-enrichment, domain-recon, or timeline."
        ),
    ] = None,
    write_template_path: Annotated[
        Path | None,
        typer.Option(
            "--write-template",
            help="Write an annotated starter YAML manifest and exit.",
        ),
    ] = None,
    username: Annotated[
        list[str], typer.Option("--username", help="Username seed; repeatable.")
    ] = None,
    email: Annotated[list[str], typer.Option("--email", help="Email seed; repeatable.")] = None,
    domain: Annotated[list[str], typer.Option("--domain", help="Domain seed; repeatable.")] = None,
    ip: Annotated[list[str], typer.Option("--ip", help="IP seed; repeatable.")] = None,
    phone: Annotated[list[str], typer.Option("--phone", help="Phone seed; repeatable.")] = None,
    person: Annotated[
        list[str], typer.Option("--person", help="Person/name seed; repeatable.")
    ] = None,
    company: Annotated[
        list[str], typer.Option("--company", help="Company seed; repeatable.")
    ] = None,
    address: Annotated[
        list[str], typer.Option("--address", help="Potential physical address context; repeatable.")
    ] = None,
    location: Annotated[
        list[str], typer.Option("--location", help="Location context; repeatable.")
    ] = None,
    url: Annotated[list[str], typer.Option("--url", help="URL/profile seed; repeatable.")] = None,
    hash_value: Annotated[list[str], typer.Option("--hash", help="Hash seed; repeatable.")] = None,
    certificate: Annotated[
        list[str], typer.Option("--certificate", help="Certificate fingerprint seed; repeatable.")
    ] = None,
    seed: Annotated[
        list[str], typer.Option("--seed", help="Generic TYPE=VALUE seed; repeatable.")
    ] = None,
    file: Annotated[
        list[Path],
        typer.Option("--file", exists=True, dir_okay=False, help="File seed; repeatable."),
    ] = None,
    hypothesis: Annotated[
        list[str], typer.Option("--hypothesis", help="Unverified hypothesis; repeatable.")
    ] = None,
    note: Annotated[str, typer.Option("--note", help="Initial case note.")] = "",
    tag: Annotated[list[str], typer.Option("--tag")] = None,
    profile: Annotated[ScanProfile, typer.Option("--profile", "-p")] = ScanProfile.DEEP,
    no_verify: Annotated[
        bool, typer.Option("--no-verify", help="Skip passive profile verification.")
    ] = False,
    no_pivot: Annotated[bool, typer.Option("--no-pivot", help="Disable automatic pivots.")] = False,
    max_depth: Annotated[int | None, typer.Option("--max-depth", min=0, max=8)] = None,
    max_targets: Annotated[int | None, typer.Option("--max-targets", min=1, max=1000)] = None,
    tool: Annotated[
        list[str], typer.Option("--tool", help="Restrict scans to selected plugins.")
    ] = None,
    exclude_tool: Annotated[list[str], typer.Option("--exclude-tool")] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache")] = False,
    analyze: Annotated[
        bool,
        typer.Option(
            "--analyze", help="Run the configured multi-pass AI analysis after collection."
        ),
    ] = False,
    analysis_depth: Annotated[
        AnalysisDepth, typer.Option("--analysis-depth")
    ] = AnalysisDepth.THOROUGH,
    thinking_level: Annotated[
        str | None,
        typer.Option(
            "--thinking-level",
            help="Provider reasoning effort: minimal, low, medium, or high.",
        ),
    ] = None,
    provider: Annotated[
        str | None, typer.Option("--provider", help="AI provider for --analyze.")
    ] = None,
    model: Annotated[str | None, typer.Option("--model", help="AI model override.")] = None,
) -> None:
    """Create one persistent deep case from many heterogeneous seeds."""
    try:
        if write_template_path:
            sample = DeepCaseManifest(
                name="Example multi-seed investigation",
                workflow="identity",
                description=(
                    "Replace the sample values with lawful, authorized investigation inputs. "
                    "Supplying multiple seeds records context; it does not prove common ownership."
                ),
                tags=["example"],
                hypotheses=["The supplied accounts may be related; this remains unverified."],
                notes="Record scope, authorization, and any known limitations here.",
                seeds=[
                    DeepCaseSeed(
                        target="example_handle",
                        target_type=TargetType.USERNAME,
                        label="Known username",
                    ),
                    DeepCaseSeed(
                        target="person@example.com",
                        target_type=TargetType.EMAIL,
                        label="Potential email",
                    ),
                    DeepCaseSeed(
                        target="example.com",
                        target_type=TargetType.DOMAIN,
                        label="Related domain",
                    ),
                    DeepCaseSeed(
                        target="Example City",
                        target_type=TargetType.LOCATION,
                        label="Context only",
                        confidence=0.5,
                        notes="A location lead is context, not identity proof.",
                    ),
                ],
            )
            destination = write_template_path.expanduser()
            write_manifest(destination, sample)
            console.print(f"Deep-case template written to {destination}")
            return
        if manifest_path:
            manifest = load_manifest(manifest_path)
            if name:
                manifest.name = name
            if description:
                manifest.description = description
            manifest.tags = sorted(set(manifest.tags + (tag or [])))
            if workflow is not None:
                manifest.workflow = workflow
            manifest.hypotheses.extend(hypothesis or [])
            if note:
                manifest.notes = f"{manifest.notes}\n{note}".strip()
        else:
            if not name and not case_identifier:
                raise typer.BadParameter(
                    "--name is required when no manifest or --case is supplied"
                )
            existing_workflow = None
            existing_description = ""
            existing_tags: list[str] = []
            existing_name = "Existing deep case"
            if case_identifier:
                config = load_config(ctx.obj.config_path)
                existing_workspace = CaseManager(config.paths.cases_dir).resolve(case_identifier)
                existing_name = existing_workspace.record.name
                existing_description = existing_workspace.record.description
                existing_tags = existing_workspace.record.tags
                existing_manifest_path = existing_workspace.root / "deep-case.yaml"
                if existing_manifest_path.exists():
                    existing_manifest = load_manifest(existing_manifest_path)
                    existing_workflow = existing_manifest.workflow
                    existing_description = existing_manifest.description or existing_description
                    existing_tags = sorted(set(existing_tags) | set(existing_manifest.tags))
            manifest = DeepCaseManifest(
                name=name or existing_name,
                workflow=workflow or existing_workflow or "identity",
                description=description or existing_description,
                tags=sorted(set(existing_tags) | set(tag or [])),
                hypotheses=hypothesis or [],
                notes=note,
            )
        manifest.seeds.extend(_deep_seed_values(username, TargetType.USERNAME))
        manifest.seeds.extend(_deep_seed_values(email, TargetType.EMAIL))
        manifest.seeds.extend(_deep_seed_values(domain, TargetType.DOMAIN))
        manifest.seeds.extend(_deep_seed_values(ip, TargetType.IP))
        manifest.seeds.extend(_deep_seed_values(phone, TargetType.PHONE))
        manifest.seeds.extend(_deep_seed_values(person, TargetType.PERSON))
        manifest.seeds.extend(_deep_seed_values(company, TargetType.COMPANY))
        manifest.seeds.extend(_deep_seed_values(address, TargetType.ADDRESS))
        manifest.seeds.extend(_deep_seed_values(location, TargetType.LOCATION))
        manifest.seeds.extend(_deep_seed_values(url, TargetType.URL))
        manifest.seeds.extend(_deep_seed_values(hash_value, TargetType.HASH))
        manifest.seeds.extend(_deep_seed_values(certificate, TargetType.CERTIFICATE))
        for raw_seed in seed or []:
            if "=" not in raw_seed:
                raise typer.BadParameter(
                    "--seed must use TYPE=VALUE, for example email=alice@example.com"
                )
            raw_type, raw_value = raw_seed.split("=", 1)
            try:
                target_type = TargetType(raw_type.strip().lower())
            except ValueError as exc:
                allowed = ", ".join(item.value for item in TargetType if item != TargetType.AUTO)
                raise typer.BadParameter(
                    f"unknown --seed type {raw_type!r}; choose from {allowed}"
                ) from exc
            manifest.seeds.extend(_deep_seed_values([raw_value], target_type))
        manifest.seeds.extend(
            DeepCaseSeed(target=str(item.expanduser().resolve()), target_type=TargetType.FILE)
            for item in (file or [])
        )
        if manifest.workflow not in {
            "identity",
            "general",
            "email-enrichment",
            "domain-recon",
            "timeline",
        }:
            raise typer.BadParameter(
                "--workflow must be identity, general, email-enrichment, domain-recon, or timeline"
            )
        if thinking_level is not None and thinking_level not in {
            "minimal",
            "low",
            "medium",
            "high",
        }:
            raise typer.BadParameter("--thinking-level must be minimal, low, medium, or high")
        manifest = normalize_manifest(manifest)
        result = asyncio.run(
            _run_deep_case(
                ctx,
                manifest,
                case_identifier=case_identifier,
                profile=profile,
                no_verify=no_verify,
                no_pivot=no_pivot,
                max_depth=max_depth,
                max_targets=max_targets,
                tools=tool or None,
                exclude_tools=exclude_tool or None,
                no_cache=no_cache,
            )
        )
        workspace = result.workspace
        console.print(
            f"[bold green]Deep case {'updated' if case_identifier else 'created'}:[/bold green] {workspace.record.name} "
            f"([cyan]{workspace.record.case_id}[/cyan])"
        )
        console.print(
            f"Seeds: {result.total_seed_count} total"
            + (f" · {result.new_seed_count} new" if case_identifier else "")
            + f" · Scans: {len(result.scans)} · Verified profiles: {result.verifications} · "
            f"Clusters: {len(result.clusters)} · Review tasks: {len(result.review_tasks)}"
        )
        if result.failed_seeds:
            console.print(f"[yellow]Seed/pivot failures:[/yellow] {len(result.failed_seeds)}")
            for item in result.failed_seeds[:10]:
                console.print(f"  - {escape(item)}")
        if result.skipped_seeds:
            console.print(
                f"[dim]Context-only or unavailable seeds: {len(result.skipped_seeds)}[/dim]"
            )
        if analyze:
            config, manager, knowledge, _ = _case_services(ctx)
            workspace = manager.resolve(workspace.record.case_id)
            analysis = asyncio.run(
                InvestigationAssistant(config).analyze(
                    workspace.nodes(),
                    workspace.edges(),
                    context={
                        "seeds": workspace.deep_seeds(),
                        "clusters": [item.model_dump(mode="json") for item in workspace.clusters()],
                        "review_tasks": [
                            item.model_dump(mode="json") for item in workspace.review_tasks()
                        ],
                        "verifications": [
                            item.model_dump(mode="json") for item in workspace.verifications()
                        ],
                    },
                    provider=provider,
                    model=model,
                    depth=analysis_depth,
                    thinking_level=thinking_level,
                )
            )
            paths = write_analysis(workspace.reports_dir, analysis)
            workspace.save_analysis(analysis)
            _rebuild_case_outputs(config, workspace, knowledge)
            console.print(f"Analysis: {paths['markdown']}")
        console.print(
            f"Dashboard: [link=file://{result.dashboard_path}]{result.dashboard_path}[/link]"
        )
        console.print(f"Workspace: {workspace.root}")
    except (MIAError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@app.command("workflows")
def workflows() -> None:
    """Explain Deep Case collection workflows and AI analysis depths."""
    table = Table(title="MIA Deep Case workflows")
    table.add_column("Workflow")
    table.add_column("Purpose")
    table.add_column("Default behavior")
    rows = [
        (
            "identity",
            "Verify and compare candidate public accounts around one or more possible identities.",
            "Deep collection, bounded pivots, profile verification, clustering, contradictions, and review tasks.",
        ),
        (
            "general",
            "Keep mixed indicators and context in one case without assuming one identity.",
            "Deep collection and bounded pivots; compatible public profiles can be verified.",
        ),
        (
            "email-enrichment",
            "Investigate supplied email indicators and related public accounts/domains.",
            "Collection and pivots; profile verification is skipped unless explicitly requested.",
        ),
        (
            "domain-recon",
            "Correlate domains, hosts, certificates, URLs, organizations, and public metadata.",
            "Collection and pivots; identity-profile verification is skipped by default.",
        ),
        (
            "timeline",
            "Build one chronological case from known entities, files, and dated findings.",
            "Collection with timeline extraction; profile verification is skipped by default.",
        ),
    ]
    for row in rows:
        table.add_row(*row)
    console.print(table)
    analysis = Table(title="Evidence-grounded analysis depths")
    analysis.add_column("Depth")
    analysis.add_column("Passes")
    analysis.add_column("Intended use")
    analysis.add_row(
        "quick",
        "Analyst",
        "Fast prioritization of the strongest links and obvious false positives.",
    )
    analysis.add_row(
        "standard", "Analyst → Skeptic → Planner", "Routine evidence review with a challenge pass."
    )
    analysis.add_row(
        "thorough",
        "Analyst → Profile reviewer → Skeptic → Verifier → Planner",
        "Profile-by-profile review, contradictions, citation audit, and next steps.",
    )
    analysis.add_row(
        "exhaustive",
        "Thorough + cluster critic + final synthesizer",
        "Maximum bounded multi-pass review; slower and potentially more expensive remotely.",
    )
    console.print(analysis)


@app.command("deep-case", hidden=True)
def deep_case_alias(
    ctx: typer.Context,
    manifest_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Compatibility alias for `mia deeps MANIFEST`."""
    ctx.invoke(deeps, manifest_path=manifest_path)


@case_app.command("verify")
def case_verify(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument()],
) -> None:
    """Passively verify candidate profile pages and preserve bounded snapshots."""
    try:
        config, manager, knowledge, _ = _case_services(ctx)
        workspace = manager.resolve(identifier)
        results = asyncio.run(ProfileVerifier(config).verify_case(workspace))
        clusters, tasks, _ = IdentityClusterEngine(config).run(workspace)
        _rebuild_case_outputs(config, workspace, knowledge)
        counts: dict[str, int] = {}
        for item in results:
            counts[item.status.value] = counts.get(item.status.value, 0) + 1
        console.print(
            f"Verified {len(results)} profile candidates · Clusters: {len(clusters)} · Review tasks: {len(tasks)}"
        )
        if counts:
            console.print(" · ".join(f"{key}: {value}" for key, value in sorted(counts.items())))
    except (MIAError, ValueError) as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@case_app.command("cluster")
def case_cluster(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument()],
) -> None:
    """Recompute explainable identity clusters and contradictions."""
    try:
        config, manager, knowledge, _ = _case_services(ctx)
        workspace = manager.resolve(identifier)
        clusters, tasks, edges = IdentityClusterEngine(config).run(workspace)
        _rebuild_case_outputs(config, workspace, knowledge)
        table = Table(title=f"Identity clusters · {workspace.record.name}")
        table.add_column("Cluster")
        table.add_column("Profiles", justify="right")
        table.add_column("Confidence")
        table.add_column("Contradictions", justify="right")
        for cluster in clusters:
            table.add_row(
                cluster.label,
                str(len(cluster.node_ids)),
                f"{cluster.confidence:.0%}",
                str(len(cluster.contradictions)),
            )
        console.print(table)
        console.print(f"Comparison edges: {len(edges)} · Review tasks: {len(tasks)}")
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@case_app.command("review")
def case_review(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument()],
    task_id: Annotated[
        str | None, typer.Option("--task", help="Resolve a task by ID/prefix.")
    ] = None,
    status: Annotated[ReviewStatus | None, typer.Option("--status")] = None,
    note: Annotated[str, typer.Option("--note")] = "",
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show or resolve the prioritized manual-review queue."""
    try:
        config, manager, knowledge, _ = _case_services(ctx)
        workspace = manager.resolve(identifier)
        if task_id:
            if status is None or status == ReviewStatus.PENDING:
                raise typer.BadParameter("--task requires --status accepted, rejected, or deferred")
            task = workspace.resolve_review_task(task_id, status, note)
            _rebuild_case_outputs(config, workspace, knowledge)
            console.print(f"Review task {task.task_id}: {task.status.value}")
            return
        tasks = workspace.review_tasks(status)
        if as_json:
            console.print_json(json.dumps([item.model_dump(mode="json") for item in tasks]))
            return
        table = Table(title=f"Manual review queue · {workspace.record.name}")
        table.add_column("Task ID")
        table.add_column("Priority")
        table.add_column("Status")
        table.add_column("Task")
        table.add_column("Evidence")
        for item in tasks:
            table.add_row(
                item.task_id,
                item.priority,
                item.status.value,
                item.title,
                str(len(item.evidence_ids)),
            )
        console.print(table)
    except (MIAError, ValueError) as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@case_app.command("analyze")
def case_analyze(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument()],
    depth: Annotated[AnalysisDepth, typer.Option("--depth")] = AnalysisDepth.THOROUGH,
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    model: Annotated[str | None, typer.Option("--model")] = None,
    endpoint: Annotated[str | None, typer.Option("--endpoint")] = None,
    thinking_level: Annotated[
        str | None,
        typer.Option(
            "--thinking-level",
            help="Provider reasoning effort: minimal, low, medium, or high.",
        ),
    ] = None,
) -> None:
    """Run an evidence-cited analyst/skeptic/verifier/planner workflow."""
    try:
        if thinking_level is not None and thinking_level not in {
            "minimal",
            "low",
            "medium",
            "high",
        }:
            raise typer.BadParameter("--thinking-level must be minimal, low, medium, or high")
        config, manager, knowledge, _ = _case_services(ctx)
        workspace = manager.resolve(identifier)
        analysis = asyncio.run(
            InvestigationAssistant(config).analyze(
                workspace.nodes(),
                workspace.edges(),
                context={
                    "seeds": workspace.deep_seeds(),
                    "clusters": [item.model_dump(mode="json") for item in workspace.clusters()],
                    "review_tasks": [
                        item.model_dump(mode="json") for item in workspace.review_tasks()
                    ],
                    "verifications": [
                        item.model_dump(mode="json") for item in workspace.verifications()
                    ],
                    "notes": workspace.notes_path.read_text(encoding="utf-8")
                    if workspace.notes_path.exists()
                    else "",
                },
                provider=provider,
                model=model,
                endpoint=endpoint,
                depth=depth,
                thinking_level=thinking_level,
            )
        )
        paths = write_analysis(workspace.reports_dir, analysis)
        workspace.save_analysis(analysis)
        _rebuild_case_outputs(config, workspace, knowledge)
        console.print(
            f"Analysis written: {paths['markdown']} · Passes: {len(analysis.passes)} · "
            f"Rejected ungrounded: {analysis.rejected_ungrounded_statements}"
        )
    except (MIAError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@case_app.command("create")
def case_create(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Human-readable case name.")],
    description: Annotated[str, typer.Option("--description", "-d")] = "",
    tag: Annotated[list[str], typer.Option("--tag")] = None,
) -> None:
    """Create an empty persistent case workspace."""
    try:
        config, manager, knowledge, _ = _case_services(ctx)
        del config
        workspace = manager.create(name, description=description, tags=tag or [])
        knowledge.ingest(workspace.record, [])
        console.print(f"Created [bold]{workspace.record.case_id}[/bold] at {workspace.root}")
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@case_app.command("list")
def case_list(
    ctx: typer.Context,
    archived: Annotated[bool, typer.Option("--archived", help="Include archived cases.")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List persistent investigation cases."""
    try:
        _, manager, _, _ = _case_services(ctx)
        records = manager.list(include_archived=archived)
        if as_json:
            console.print_json(json.dumps([record.model_dump(mode="json") for record in records]))
            return
        table = Table(title="MIA investigation cases")
        table.add_column("Case ID")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Updated")
        table.add_column("Tags")
        for record in records:
            table.add_row(
                record.case_id,
                record.name,
                record.status.value,
                record.updated_at.isoformat(timespec="seconds"),
                ", ".join(record.tags) or "—",
            )
        console.print(table)
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@case_app.command("show")
def case_show(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument(help="Case ID, prefix, slug, or exact name.")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show case metadata and investigation statistics."""
    try:
        _, manager, _, _ = _case_services(ctx)
        workspace = manager.resolve(identifier)
        payload = {
            **workspace.record.model_dump(mode="json"),
            "scan_count": len(workspace.scans()),
            "node_count": len(workspace.nodes()),
            "edge_count": len(workspace.edges()),
            "timeline_count": len(workspace.timeline()),
            "dashboard": str(workspace.reports_dir / "index.html"),
        }
        if as_json:
            console.print_json(json.dumps(payload))
            return
        console.print(f"[bold]{workspace.record.name}[/bold] ({workspace.record.case_id})")
        console.print(f"Status: {workspace.record.status.value}")
        console.print(f"Description: {workspace.record.description or '—'}")
        console.print(f"Workspace: {workspace.root}")
        console.print(
            f"Scans: {payload['scan_count']} · Nodes: {payload['node_count']} · "
            f"Edges: {payload['edge_count']} · Timeline events: {payload['timeline_count']}"
        )
        dashboard = Path(payload["dashboard"])
        if dashboard.exists():
            console.print(f"Dashboard: [link=file://{dashboard}]{dashboard}[/link]")
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@case_app.command("note")
def case_note(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument()],
    text: Annotated[str | None, typer.Argument(help="Note text; omit to read from stdin.")] = None,
) -> None:
    """Append a timestamped note to a case."""
    try:
        config, manager, knowledge, _ = _case_services(ctx)
        workspace = manager.resolve(identifier)
        note = text if text is not None else sys.stdin.read()
        if not note.strip():
            raise typer.BadParameter("note text cannot be empty")
        workspace.append_note(note)
        if config.workspaces.auto_update_dashboard:
            _rebuild_case_outputs(config, workspace, knowledge)
        console.print(f"Note appended to {workspace.notes_path}")
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


def _rebuild_case_outputs(config: AppConfig, workspace: object, knowledge: KnowledgeDatabase):
    nodes = workspace.nodes()
    edges = workspace.edges()
    export_all_graph_formats(workspace.graph_dir, nodes, edges)
    workspace.export_payload()
    knowledge.ingest(workspace.record, nodes)
    correlations = knowledge.correlations_for_case(workspace.record.case_id)
    summary = InvestigationAssistant(config).local_summary(nodes, edges, correlations)
    write_summary(workspace.reports_dir, summary)
    dashboard = write_dashboard(
        workspace,
        raw_excerpt_bytes=config.reports.dashboard_raw_excerpt_bytes,
        assistant_summary=summary,
        correlations=correlations,
        max_nodes=config.workspaces.graph_max_nodes_in_dashboard,
    )
    return dashboard, correlations, summary


@case_app.command("add-evidence")
def case_add_evidence(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument()],
    source: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    note: Annotated[str, typer.Option("--note")] = "",
) -> None:
    """Copy a file into the case evidence store and record its SHA-256 digest."""
    try:
        config, manager, knowledge, _ = _case_services(ctx)
        workspace = manager.resolve(identifier)
        attachment = workspace.add_attachment(source, kind="evidence", note=note)
        if config.workspaces.auto_update_dashboard:
            _rebuild_case_outputs(config, workspace, knowledge)
        console.print(f"Evidence added: {attachment.filename} · SHA-256 {attachment.sha256}")
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@case_app.command("add-screenshot")
def case_add_screenshot(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument()],
    source: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    note: Annotated[str, typer.Option("--note")] = "",
) -> None:
    """Copy an image into the screenshot store and record its SHA-256 digest."""
    try:
        if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            raise typer.BadParameter("screenshot must be PNG, JPEG, WebP, or GIF")
        config, manager, knowledge, _ = _case_services(ctx)
        workspace = manager.resolve(identifier)
        attachment = workspace.add_attachment(source, kind="screenshot", note=note)
        if config.workspaces.auto_update_dashboard:
            _rebuild_case_outputs(config, workspace, knowledge)
        console.print(f"Screenshot added: {attachment.filename} · SHA-256 {attachment.sha256}")
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@case_app.command("dashboard")
def case_dashboard(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument()],
) -> None:
    """Rebuild an offline interactive case dashboard and graph exports."""
    try:
        config, manager, knowledge, _ = _case_services(ctx)
        workspace = manager.resolve(identifier)
        dashboard, correlations, _ = _rebuild_case_outputs(config, workspace, knowledge)
        console.print(f"Dashboard rebuilt with {len(correlations)} correlations:")
        console.print(f"[link=file://{dashboard}]{dashboard}[/link]")
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@case_app.command("summarize")
def case_summarize(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument()],
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            help=(
                "local, openai-compatible, gemini, or ollama; omit to use the configured default"
            ),
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Override the configured model for this summary."),
    ] = None,
    endpoint: Annotated[
        str | None,
        typer.Option(
            "--endpoint", help="Override the configured provider endpoint for this summary."
        ),
    ] = None,
) -> None:
    """Generate an evidence-grounded summary; ungrounded model statements are discarded."""
    try:
        config, manager, knowledge, _ = _case_services(ctx)
        workspace = manager.resolve(identifier)
        correlations = knowledge.correlations_for_case(workspace.record.case_id)
        summary = asyncio.run(
            InvestigationAssistant(config).summarize(
                workspace.nodes(),
                workspace.edges(),
                correlations,
                provider=provider,
                model=model,
                endpoint=endpoint,
            )
        )
        paths = write_summary(workspace.reports_dir, summary)
        write_dashboard(
            workspace,
            raw_excerpt_bytes=config.reports.dashboard_raw_excerpt_bytes,
            assistant_summary=summary,
            correlations=correlations,
            max_nodes=config.workspaces.graph_max_nodes_in_dashboard,
        )
        console.print(f"Summary written: {paths['markdown']}")
        if summary.rejected_ungrounded_statements:
            console.print(
                f"[yellow]Rejected {summary.rejected_ungrounded_statements} ungrounded statements.[/yellow]"
            )
    except (MIAError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@case_app.command("correlations")
def case_correlations(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument()],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show exact normalized entities shared with other cases."""
    try:
        _, manager, knowledge, _ = _case_services(ctx)
        workspace = manager.resolve(identifier)
        correlations = knowledge.correlations_for_case(workspace.record.case_id)
        if as_json:
            console.print_json(json.dumps([item.model_dump(mode="json") for item in correlations]))
            return
        table = Table(title=f"Cross-case correlations · {workspace.record.name}")
        table.add_column("Type")
        table.add_column("Entity")
        table.add_column("Cases")
        table.add_column("Reason")
        for item in correlations:
            table.add_row(
                item.entity_type,
                item.canonical_value,
                ", ".join(item.case_names),
                item.reason,
            )
        console.print(table)
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@case_app.command("archive")
def case_archive(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument()],
    reopen: Annotated[bool, typer.Option("--reopen", help="Reopen instead of archive.")] = False,
) -> None:
    """Archive or reopen a case without deleting evidence."""
    try:
        _, manager, knowledge, _ = _case_services(ctx)
        workspace = manager.resolve(identifier)
        workspace.record.status = CaseStatus.OPEN if reopen else CaseStatus.ARCHIVED
        workspace.write_manifest()
        knowledge.ingest(workspace.record, workspace.nodes())
        console.print(f"Case status: {workspace.record.status.value}")
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


def _config_override_path(ctx: typer.Context) -> Path:
    options: RuntimeOptions = ctx.obj
    return (options.config_path or user_config_path()).expanduser()


def _validated_api_service(ctx: typer.Context, service: str) -> tuple[AppConfig, str]:
    config = load_config(ctx.obj.config_path)
    normalized = service.strip().lower()
    if not normalized or normalized not in config.apis:
        supported = ", ".join(sorted(config.apis))
        raise typer.BadParameter(
            f"unknown API service: {service}; supported services: {supported}",
            param_hint="service",
        )
    return config, normalized


def _set_api_enabled(ctx: typer.Context, service: str, enabled: bool) -> Path:
    _, service = _validated_api_service(ctx, service)
    path = _config_override_path(ctx)
    data: dict[str, object] = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise MIAError(f"configuration root must be a mapping: {path}")
        data = loaded
    apis = data.setdefault("apis", {})
    if not isinstance(apis, dict):
        raise MIAError("configuration key 'apis' must be a mapping")
    service_config = apis.setdefault(service, {})
    if not isinstance(service_config, dict):
        raise MIAError(f"configuration key 'apis.{service}' must be a mapping")
    service_config["enabled"] = enabled
    atomic_write_text(path, yaml.safe_dump(data, sort_keys=False), mode=0o600)
    return path


@api_app.command("list")
def api_list(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List supported API integrations, enablement, and credential source."""
    try:
        config = load_config(ctx.obj.config_path)
        store = SecretStore(config)
        rows = [
            {
                "service": name,
                "enabled": service.enabled,
                "endpoint": service.endpoint,
                "credential_source": store.source(name),
                "environment_variable": store.env_name(name),
            }
            for name, service in sorted(config.apis.items())
        ]
        if as_json:
            console.print_json(json.dumps(rows))
            return
        table = Table(title="MIA API integrations")
        table.add_column("Service")
        table.add_column("Enabled")
        table.add_column("Thinking")
        table.add_column("Credential")
        table.add_column("Environment variable")
        for row in rows:
            table.add_row(
                row["service"],
                "[green]yes[/green]" if row["enabled"] else "[dim]no[/dim]",
                row["credential_source"],
                row["environment_variable"],
            )
        console.print(table)
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@api_app.command("set")
def api_set(
    ctx: typer.Context,
    service: Annotated[
        str,
        typer.Argument(
            help=(
                "shodan, virustotal, hibp, securitytrails, censys, intelx, "
                "assistant, gemini, or ollama"
            )
        ),
    ],
    key: Annotated[
        str | None,
        typer.Option("--key", help="Avoid this option in shared shell history; prompt is safer."),
    ] = None,
    insecure_file: Annotated[
        bool,
        typer.Option(
            "--insecure-file", help="Use a chmod-0600 plaintext fallback instead of an OS keyring."
        ),
    ] = False,
    no_enable: Annotated[bool, typer.Option("--no-enable")] = False,
) -> None:
    """Store a credential in the OS keyring or explicit 0600 fallback, never in YAML."""
    try:
        config, service = _validated_api_service(ctx, service)
        secret = key or getpass.getpass(f"API key/token for {service}: ")
        location = SecretStore(config).set(service, secret, insecure_file=insecure_file)
        path = None if no_enable else _set_api_enabled(ctx, service, True)
        console.print(f"Credential stored in {location}.")
        if path:
            console.print(f"Enabled {service} in {path}")
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@api_app.command("delete")
def api_delete(
    ctx: typer.Context,
    service: Annotated[str, typer.Argument()],
    disable: Annotated[bool, typer.Option("--disable/--keep-enabled")] = True,
) -> None:
    """Remove a stored credential and optionally disable its integration."""
    try:
        config, service = _validated_api_service(ctx, service)
        removed = SecretStore(config).delete(service)
        if disable:
            _set_api_enabled(ctx, service, False)
        console.print("Credential removed." if removed else "No stored credential was found.")
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@api_app.command("enable")
def api_enable(ctx: typer.Context, service: Annotated[str, typer.Argument()]) -> None:
    """Enable an API integration in the user configuration."""
    try:
        _, service = _validated_api_service(ctx, service)
        console.print(f"Enabled in {_set_api_enabled(ctx, service, True)}")
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@api_app.command("disable")
def api_disable(ctx: typer.Context, service: Annotated[str, typer.Argument()]) -> None:
    """Disable an API integration without deleting its credential."""
    try:
        _, service = _validated_api_service(ctx, service)
        console.print(f"Disabled in {_set_api_enabled(ctx, service, False)}")
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


def _write_assistant_provider_config(
    ctx: typer.Context,
    provider: str,
    *,
    model: str | None,
    endpoint: str | None,
    set_default: bool,
    thinking_level: str | None = None,
) -> Path:
    normalized = InvestigationAssistant.normalize_provider(provider)
    if normalized not in {"local", "openai-compatible", "gemini", "ollama"}:
        raise typer.BadParameter("provider must be local, openai-compatible, gemini, or ollama")
    path = _config_override_path(ctx)
    data: dict[str, object] = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise MIAError(f"configuration root must be a mapping: {path}")
        data = loaded
    assistant = data.setdefault("assistant", {})
    if not isinstance(assistant, dict):
        raise MIAError("configuration key 'assistant' must be a mapping")
    if normalized == "local":
        if model is not None or endpoint is not None or thinking_level is not None:
            raise typer.BadParameter(
                "the local provider does not accept --model, --endpoint, or --thinking-level"
            )
        if set_default:
            assistant["provider"] = "local"
    else:
        providers = assistant.setdefault("providers", {})
        if not isinstance(providers, dict):
            raise MIAError("configuration key 'assistant.providers' must be a mapping")
        provider_config = providers.setdefault(normalized, {})
        if not isinstance(provider_config, dict):
            raise MIAError(
                f"configuration key 'assistant.providers.{normalized}' must be a mapping"
            )
        if model is not None:
            provider_config["model"] = model.strip()
        if endpoint is not None:
            provider_config["endpoint"] = endpoint.strip()
        if thinking_level is not None:
            level = thinking_level.strip().lower()
            if level not in {"minimal", "low", "medium", "high"}:
                raise typer.BadParameter("--thinking-level must be minimal, low, medium, or high")
            provider_config["thinking_level"] = level
        if set_default:
            assistant["provider"] = normalized
    atomic_write_text(path, yaml.safe_dump(data, sort_keys=False), mode=0o600)
    return path


@assistant_app.command("providers")
def assistant_providers(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List local, OpenAI-compatible, Gemini, and Ollama assistant settings."""
    try:
        config = load_config(ctx.obj.config_path)
        store = SecretStore(config)
        rows: list[dict[str, object]] = [
            {
                "provider": "local",
                "default": config.assistant.provider in {"local", "off", "none"},
                "model": "deterministic",
                "endpoint": "offline",
                "thinking_level": "deterministic",
                "credential": "not required",
                "ready": True,
            }
        ]
        for name in ("openai-compatible", "gemini", "ollama"):
            settings = config.assistant.settings(name)
            credential = (
                store.source(settings.api_service) if settings.api_service else "not configured"
            )
            has_key = bool(store.get(settings.api_service)) if settings.api_service else False
            ready = bool(settings.model.strip()) and (not settings.requires_key or has_key)
            rows.append(
                {
                    "provider": name,
                    "default": InvestigationAssistant.normalize_provider(config.assistant.provider)
                    == name,
                    "model": settings.model or "not configured",
                    "endpoint": settings.endpoint,
                    "thinking_level": settings.thinking_level or "provider default",
                    "credential": (
                        credential if settings.requires_key or has_key else "not required (local)"
                    ),
                    "ready": ready,
                }
            )
        if as_json:
            console.print_json(json.dumps(rows))
            return
        table = Table(title="MIA assistant providers")
        table.add_column("Provider")
        table.add_column("Default")
        table.add_column("Model")
        table.add_column("Thinking")
        table.add_column("Credential")
        table.add_column("Ready")
        for row in rows:
            table.add_row(
                str(row["provider"]),
                "yes" if row["default"] else "",
                str(row["model"]),
                str(row.get("thinking_level", "deterministic")),
                str(row["credential"]),
                "[green]yes[/green]" if row["ready"] else "[yellow]configure[/yellow]",
            )
        console.print(table)
    except (MIAError, ValueError) as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@assistant_app.command("configure")
def assistant_configure(
    ctx: typer.Context,
    provider: Annotated[str, typer.Argument(help="local, openai-compatible, gemini, or ollama")],
    model: Annotated[str | None, typer.Option("--model", help="Provider model name.")] = None,
    endpoint: Annotated[
        str | None, typer.Option("--endpoint", help="Provider API base URL.")
    ] = None,
    thinking_level: Annotated[
        str | None,
        typer.Option(
            "--thinking-level",
            help="Gemini/Ollama reasoning effort: minimal, low, medium, or high.",
        ),
    ] = None,
    set_default: Annotated[
        bool, typer.Option("--default/--no-default", help="Make this the default provider.")
    ] = True,
) -> None:
    """Write non-secret assistant provider settings to the user configuration."""
    try:
        if model is None and endpoint is None and thinking_level is None and not set_default:
            raise typer.BadParameter("provide --model, --endpoint, --thinking-level, or --default")
        path = _write_assistant_provider_config(
            ctx,
            provider,
            model=model,
            endpoint=endpoint,
            set_default=set_default,
            thinking_level=thinking_level,
        )
        console.print(f"Assistant provider configuration updated in {path}")
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@plugin_app.command("create")
def plugin_create(
    ctx: typer.Context,
    plugin_id: Annotated[str, typer.Argument(help="Lowercase plugin identifier.")],
    destination: Annotated[Path | None, typer.Option("--path", "--destination")] = None,
) -> None:
    """Scaffold a documented community plugin with a manifest and tests."""
    try:
        config = load_config(ctx.obj.config_path)
        path = CommunityPluginManager(config.paths.user_plugins_dir).create(plugin_id, destination)
        console.print(f"Plugin scaffold created at {path}")
    except (MIAError, ValueError) as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@plugin_app.command("list")
def plugin_list(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List installed community plugins."""
    try:
        config = load_config(ctx.obj.config_path)
        rows = CommunityPluginManager(config.paths.user_plugins_dir).list()
        if as_json:
            console.print_json(
                json.dumps(
                    [
                        {**manifest.model_dump(mode="json"), "path": str(path)}
                        for manifest, path in rows
                    ]
                )
            )
            return
        table = Table(title="MIA community plugins")
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Version")
        table.add_column("Targets")
        table.add_column("Path")
        for manifest, path in rows:
            table.add_row(
                manifest.plugin_id,
                manifest.name,
                manifest.version,
                ", ".join(manifest.target_types),
                str(path),
            )
        console.print(table)
    except (MIAError, ValueError) as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@plugin_app.command("validate")
def plugin_validate(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate a community plugin manifest and import contract."""
    try:
        config = load_config(ctx.obj.config_path)
        result = CommunityPluginManager(config.paths.user_plugins_dir).validate(source)
        if as_json:
            console.print_json(json.dumps(result))
        else:
            console.print("[green]Valid[/green]" if result["valid"] else "[red]Invalid[/red]")
            for warning in result["warnings"]:
                console.print(f"[yellow]Warning:[/yellow] {warning}")
            for error in result["errors"]:
                console.print(f"[red]Error:[/red] {error}")
        if not result["valid"]:
            raise typer.Exit(1)
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@plugin_app.command("install")
def plugin_install(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    replace: Annotated[bool, typer.Option("--replace")] = False,
    install_dependencies: Annotated[
        bool,
        typer.Option(
            "--install-dependencies",
            help="Install declared MIA package-catalog dependencies before copying the plugin.",
        ),
    ] = False,
    include_mixed: Annotated[
        bool,
        typer.Option("--include-mixed", help="Allow declared mixed/direct-request tools."),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
) -> None:
    """Install a local community plugin after validation."""
    try:
        config = load_config(ctx.obj.config_path)
        community = CommunityPluginManager(config.paths.user_plugins_dir)
        manifest = community.load_manifest(source)
        if install_dependencies and manifest.package_dependencies:
            package_manager = PackageManager()
            dependencies = package_manager.resolve(manifest.package_dependencies)
            mixed = [tool.tool_id for tool in dependencies if tool.risk == "mixed"]
            if mixed and not include_mixed:
                raise PackageError(
                    "plugin dependencies include mixed tools; repeat with --include-mixed: "
                    + ", ".join(mixed)
                )
            if not yes:
                console.print(
                    "Declared package dependencies: "
                    + ", ".join(tool.tool_id for tool in dependencies)
                )
                if not typer.confirm("Install these package dependencies?"):
                    raise typer.Abort()
            results = [package_manager.install(tool) for tool in dependencies]
            _render_package_results(results)
            if any(not result.success for result in results):
                raise PackageError("one or more plugin package dependencies failed to install")
        destination = community.install(source, replace=replace)
        console.print(f"Installed plugin at {destination}")
        dependency_status = community.dependency_status(manifest)
        missing_python = [
            item["requirement"] for item in dependency_status["python"] if not item["satisfied"]
        ]
        if missing_python:
            console.print(
                "[yellow]Python dependencies still require review in MIA's environment:[/yellow] "
                + ", ".join(missing_python)
            )
    except (MIAError, PackageError) as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@plugin_app.command("doctor")
def plugin_doctor(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Check community plugin compatibility, dependencies, APIs, and import health."""
    try:
        config = load_config(ctx.obj.config_path)
        community = CommunityPluginManager(config.paths.user_plugins_dir)
        package_manager = PackageManager()
        secret_store = SecretStore(config)
        rows = []
        for manifest, path in community.list():
            validation = community.validate(path)
            package_rows = []
            for package_id in manifest.package_dependencies:
                try:
                    tool = package_manager.resolve([package_id])[0]
                    installed, executable, source_name = package_manager.status(tool)
                    package_rows.append(
                        {
                            "id": package_id,
                            "installed": installed,
                            "executable": executable,
                            "source": source_name,
                        }
                    )
                except PackageError as exc:
                    package_rows.append({"id": package_id, "installed": False, "error": str(exc)})
            api_rows = [
                {
                    "service": service,
                    "enabled": config.api(service).enabled,
                    "credential_source": secret_store.source(service),
                }
                for service in manifest.api_services
            ]
            rows.append(
                {
                    "plugin_id": manifest.plugin_id,
                    "version": manifest.version,
                    "path": str(path),
                    "valid": validation["valid"],
                    "errors": validation["errors"],
                    "warnings": validation["warnings"],
                    "dependencies": validation["dependencies"],
                    "packages": package_rows,
                    "apis": api_rows,
                }
            )
        if as_json:
            console.print_json(json.dumps(rows))
            return
        table = Table(title="MIA community plugin health")
        table.add_column("Plugin")
        table.add_column("Version")
        table.add_column("Import")
        table.add_column("MIA")
        table.add_column("Dependencies")
        for row in rows:
            dependencies = row["dependencies"]
            missing_python = sum(not item["satisfied"] for item in dependencies["python"])
            missing_packages = sum(not item.get("installed", False) for item in row["packages"])
            missing_apis = sum(
                not item["enabled"] or item["credential_source"] == "not configured"
                for item in row["apis"]
            )
            table.add_row(
                row["plugin_id"],
                row["version"],
                "[green]valid[/green]" if row["valid"] else "[red]failed[/red]",
                "[green]compatible[/green]"
                if dependencies["mia_compatible"]
                else "[red]incompatible[/red]",
                f"Python {missing_python} · tools {missing_packages} · APIs {missing_apis}",
            )
        console.print(table)
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@plugin_app.command("uninstall")
def plugin_uninstall(
    ctx: typer.Context,
    plugin_id: Annotated[str, typer.Argument()],
) -> None:
    """Remove a MIA community plugin directory."""
    config = load_config(ctx.obj.config_path)
    removed = CommunityPluginManager(config.paths.user_plugins_dir).uninstall(plugin_id)
    console.print("Plugin removed." if removed else "Plugin was not installed.")


@knowledge_app.command("search")
def knowledge_search(
    ctx: typer.Context,
    value: Annotated[str, typer.Argument(help="Full or partial normalized entity value.")],
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, max=500)] = 50,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Search entities observed across all local cases."""
    try:
        config = load_config(ctx.obj.config_path)
        rows = KnowledgeDatabase(config.paths.knowledge_database_path).search(value, limit)
        if as_json:
            console.print_json(json.dumps(rows))
            return
        table = Table(title=f"Knowledge search · {value}")
        table.add_column("Type")
        table.add_column("Entity")
        table.add_column("Case")
        table.add_column("Confidence")
        table.add_column("Last seen")
        for row in rows:
            table.add_row(
                row["entity_type"],
                row["canonical_value"],
                row["case_name"],
                f"{row['confidence']:.0%}",
                row["last_seen"],
            )
        console.print(table)
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@cache_app.command("status")
def cache_status(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show cache size, age range, and per-plugin entry counts."""
    config = load_config(ctx.obj.config_path)
    stats = ResultCache(config.paths.cache_database_path).stats()
    if as_json:
        console.print_json(json.dumps(stats))
        return
    console.print(f"Cache: {stats['path']}")
    console.print(
        f"Entries: {stats['entries']} · Oldest: {stats['oldest'] or '—'} · Newest: {stats['newest'] or '—'}"
    )
    table = Table(title="Cached plugin results")
    table.add_column("Plugin")
    table.add_column("Entries", justify="right")
    for row in stats["by_plugin"]:
        table.add_row(row["plugin_id"], str(row["entries"]))
    console.print(table)


@cache_app.command("clear")
def cache_clear(
    ctx: typer.Context,
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
) -> None:
    """Clear cached plugin results without deleting cases or scan history."""
    config = load_config(ctx.obj.config_path)
    if not yes and not typer.confirm("Clear all MIA plugin cache entries?"):
        raise typer.Abort()
    count = ResultCache(config.paths.cache_database_path).clear()
    console.print(f"Cleared {count} cache entries.")


def _launch_web_ui(
    ctx: typer.Context,
    *,
    host: str,
    port: int,
    open_browser: bool,
    allow_remote: bool,
    token: str | None,
    ui_variant: str,
) -> None:
    if allow_remote and not token:
        raise typer.BadParameter("--allow-remote requires --token", param_hint="--token")
    if host not in {"127.0.0.1", "localhost", "::1"} and not allow_remote:
        raise typer.BadParameter(
            "non-local bind addresses require --allow-remote and --token", param_hint="--host"
        )
    try:
        import uvicorn
        import websockets  # noqa: F401 - validates Uvicorn's live-update backend

        from mia.web import create_app
    except ImportError as exc:
        error_console.print(
            "[bold red]Error:[/bold red] UI live-update dependencies are missing. "
            "Run [bold]mia repair[/bold], or reinstall MIA using the current installer."
        )
        raise typer.Exit(2) from exc
    options: RuntimeOptions = ctx.obj
    application = create_app(
        options.config_path,
        allow_remote=allow_remote,
        access_token=token,
        ui_variant=ui_variant,
    )
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{display_host}:{port}"
    label = "MIA Discover" if ui_variant == "discover" else "MIA Workbench"
    console.print(f"[bold cyan]{label}[/bold cyan] → [link={url}]{url}[/link]")
    console.print(
        "Press Ctrl+C to stop. The server is localhost-only unless remote mode was explicitly enabled."
    )
    if open_browser:
        import threading

        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(
        application,
        host=host,
        port=port,
        log_level="debug" if options.verbose else "warning",
    )


def _launch_interface_from_options(
    ctx: typer.Context,
    *,
    variant: str,
    host: str,
    port: int,
    open_browser: bool,
    allow_remote: bool,
    token: str | None,
) -> None:
    _launch_web_ui(
        ctx,
        host=host,
        port=port,
        open_browser=open_browser,
        allow_remote=allow_remote,
        token=token,
        ui_variant=variant,
    )


@workbench_app.callback(invoke_without_command=True)
def workbench_root(
    ctx: typer.Context,
    host: Annotated[
        str, typer.Option("--host", help="Bind address. Defaults to localhost only.")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8765,
    open_browser: Annotated[
        bool,
        typer.Option("--browser/--no-browser", help="Open MIA Workbench in your default browser."),
    ] = True,
    allow_remote: Annotated[
        bool, typer.Option("--allow-remote", help="Allow non-local clients. Requires --token.")
    ] = False,
    token: Annotated[
        str | None,
        typer.Option("--token", help="Access token required for remote mode.", hide_input=True),
    ] = None,
) -> None:
    """Launch MIA Workbench directly when no subcommand is supplied."""
    if ctx.invoked_subcommand is None:
        _launch_interface_from_options(
            ctx,
            variant="workbench",
            host=host,
            port=port,
            open_browser=open_browser,
            allow_remote=allow_remote,
            token=token,
        )


@discover_app.callback(invoke_without_command=True)
def discover_root(
    ctx: typer.Context,
    host: Annotated[
        str, typer.Option("--host", help="Bind address. Defaults to localhost only.")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8766,
    open_browser: Annotated[
        bool,
        typer.Option("--browser/--no-browser", help="Open MIA Discover in your default browser."),
    ] = True,
    allow_remote: Annotated[
        bool, typer.Option("--allow-remote", help="Allow non-local clients. Requires --token.")
    ] = False,
    token: Annotated[
        str | None,
        typer.Option("--token", help="Access token required for remote mode.", hide_input=True),
    ] = None,
) -> None:
    """Launch MIA Discover directly when no subcommand is supplied."""
    if ctx.invoked_subcommand is None:
        _launch_interface_from_options(
            ctx,
            variant="discover",
            host=host,
            port=port,
            open_browser=open_browser,
            allow_remote=allow_remote,
            token=token,
        )


@app.command()
def about() -> None:
    """Explain project status, authorship disclosure, and safety boundaries."""
    console.print("[bold]MIA Core with Discover and Workbench — public alpha[/bold]")
    console.print(f"Version: {__version__}")
    console.print(
        "Status: [yellow]early alpha[/yellow]. The project was substantially "
        "vibe-coded with AI assistance and has not received a professional security audit."
    )
    console.print(
        "MIA combines separately installed tools and passive APIs into persistent evidence graphs. "
        "Results are leads, not identity proof. Review raw evidence and use only for lawful, "
        "authorized work."
    )
    console.print(
        "The optional package catalog contains third-party installation recipes; catalog "
        "presence is not an audit, endorsement, or guarantee of scan integration."
    )
    console.print("Read: README.md, AI_DISCLOSURE.md, SECURITY.md, and docs/RESPONSIBLE_USE.md")


@app.command()
def version() -> None:
    """Print the MIA version."""
    console.print(__version__)


@config_app.command("init")
def config_init(
    destination: Annotated[Path | None, typer.Option("--path", "--destination")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Create an editable user configuration file."""
    try:
        path = initialize_user_config(destination, force=force)
        console.print(f"Configuration written to {path}")
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@config_app.command("path")
def config_path() -> None:
    """Print the default user configuration path."""
    console.print(user_config_path())


@config_app.command("show")
def config_show(ctx: typer.Context) -> None:
    """Print the effective merged configuration as JSON."""
    try:
        config = load_config(ctx.obj.config_path)
        console.print_json(config.model_dump_json(exclude={"loaded_from"}, by_alias=True))
    except MIAError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


def main() -> None:
    activate_managed_bin()
    app()
