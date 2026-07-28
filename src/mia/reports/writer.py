from __future__ import annotations

from pathlib import Path

from mia.config import ReportsConfig
from mia.models import ScanResult
from mia.reports.html import render_html
from mia.reports.text import render_markdown, render_text
from mia.utils import atomic_write_json, atomic_write_text


class ReportWriter:
    def __init__(self, config: ReportsConfig) -> None:
        self.config = config

    def write(self, result: ScanResult) -> dict[str, str]:
        output_dir = Path(result.output_dir)
        paths: dict[str, Path] = {}
        if self.config.html:
            paths["html"] = output_dir / "report.html"
        if self.config.json_report:
            paths["json"] = output_dir / "report.json"
        if self.config.text:
            paths["text"] = output_dir / "report.txt"
        if self.config.markdown:
            paths["markdown"] = output_dir / "report.md"

        result.report_paths = {name: str(path) for name, path in paths.items()}
        if "html" in paths:
            atomic_write_text(paths["html"], render_html(result))
        if "text" in paths:
            atomic_write_text(paths["text"], render_text(result))
        if "markdown" in paths:
            atomic_write_text(paths["markdown"], render_markdown(result))
        if "json" in paths:
            atomic_write_json(paths["json"], result.model_dump(mode="json"))
        return result.report_paths
