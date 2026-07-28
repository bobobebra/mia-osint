from __future__ import annotations

from importlib.resources import files

from jinja2 import Environment, FileSystemLoader

from mia.display import safe_finding_title
from mia.models import ScanResult


def render_html(result: ScanResult) -> str:
    template_dir = files("mia").joinpath("templates")
    environment = Environment(
        loader=FileSystemLoader(str(template_dir)),
        # The template filename ends in .html.j2, so extension-based autoescape
        # would otherwise see only ".j2". Reports contain untrusted tool output;
        # always escape it explicitly.
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["percent"] = lambda value: f"{float(value):.0%}"
    environment.filters["finding_title"] = safe_finding_title
    template = environment.get_template("report.html.j2")
    categories: dict[str, list[object]] = {}
    for finding in result.findings:
        categories.setdefault(finding.category, []).append(finding)
    return template.render(result=result, categories=categories)
