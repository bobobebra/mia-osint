from __future__ import annotations

from mia.models import ScanResult


def render_text(result: ScanResult) -> str:
    lines = [
        "MIA OSINT REPORT",
        "=" * 72,
        f"Scan ID: {result.scan_id}",
        f"Target: {result.target}",
        f"Type: {result.target_type.value}",
        f"Profile: {result.profile.value}",
        f"Started: {result.started_at.isoformat()}",
        f"Finished: {result.finished_at.isoformat() if result.finished_at else 'incomplete'}",
        f"Findings: {len(result.findings)}",
        "",
        "PLUGIN RUNS",
        "-" * 72,
    ]
    for run in result.plugin_runs:
        detail = f"{run.plugin_name}: {run.status.value} ({run.duration_seconds:.1f}s, {len(run.findings)} findings)"
        if run.error:
            detail += f" — {run.error}"
        lines.append(detail)

    lines.extend(["", "NORMALIZED FINDINGS", "-" * 72])
    if not result.findings:
        lines.append("No positive normalized findings were produced.")
    for index, finding in enumerate(result.findings, start=1):
        lines.append(
            f"{index}. [{finding.confidence_label} {finding.confidence:.0%}] {finding.title}"
        )
        lines.append(f"   Category: {finding.category}")
        lines.append(f"   Value: {finding.value}")
        if finding.url:
            lines.append(f"   URL: {finding.url}")
        lines.append(f"   Sources: {', '.join(finding.sources)}")
        lines.append(f"   Occurrences: {finding.occurrences}")
        for reason in finding.confidence_reasons:
            lines.append(f"   - {reason}")
        lines.append("")

    lines.extend(
        [
            "RESPONSIBLE USE",
            "-" * 72,
            "Results are leads, not proof of identity. Verify findings manually and use MIA only where you have a lawful, authorized purpose.",
            "",
        ]
    )
    return "\n".join(lines)


def render_markdown(result: ScanResult) -> str:
    lines = [
        "# MIA OSINT report",
        "",
        f"- **Scan ID:** `{result.scan_id}`",
        f"- **Target:** `{result.target}`",
        f"- **Type:** {result.target_type.value}",
        f"- **Profile:** {result.profile.value}",
        f"- **Findings:** {len(result.findings)}",
        "",
        "## Plugin runs",
        "",
        "| Plugin | Status | Duration | Findings |",
        "|---|---:|---:|---:|",
    ]
    for run in result.plugin_runs:
        lines.append(
            f"| {run.plugin_name} | {run.status.value} | {run.duration_seconds:.1f}s | {len(run.findings)} |"
        )
    lines.extend(["", "## Findings", ""])
    if not result.findings:
        lines.append("No positive normalized findings were produced.")
    for finding in result.findings:
        title = f"[{finding.title}]({finding.url})" if finding.url else finding.title
        lines.extend(
            [
                f"### {title}",
                "",
                f"- **Confidence:** {finding.confidence_label} ({finding.confidence:.0%})",
                f"- **Category:** {finding.category}",
                f"- **Value:** `{finding.value}`",
                f"- **Sources:** {', '.join(finding.sources)}",
                f"- **Occurrences:** {finding.occurrences}",
                "",
            ]
        )
        if finding.attributes:
            lines.append("**Attributes**")
            lines.append("")
            for key, value in finding.attributes.items():
                lines.append(f"- `{key}`: `{value}`")
            lines.append("")
    lines.extend(
        [
            "## Responsible-use notice",
            "",
            "Results are investigative leads, not proof that accounts or records belong to the same person. Verify manually and comply with applicable law, platform terms, and authorization requirements.",
            "",
        ]
    )
    return "\n".join(lines)
