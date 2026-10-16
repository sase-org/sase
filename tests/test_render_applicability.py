"""Regression checks for the applicability single-source (sase-1le.3).

The documented install command carries the ``install_command = floor``
decision: ``uv tool install "sase>=0.18"``. The site header release line
is generated from ``.release-please-manifest.json`` and must stay
truthful while the manifest version sits below the floor.
"""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import sys
from types import ModuleType

import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
TOOL_PATH = ROOT / "tools" / "render_applicability"
INSTALL_RENDERER_PATH = ROOT / "tools" / "render_install_command"
RENDER_DOCS_PATH = ROOT / "tools" / "render_docs"
MKDOCS_CONFIG = ROOT / "mkdocs.yml"
PDF_CONFIG = ROOT / "mkdocs-pdf.yml"
MAIN_HTML = ROOT / "docs" / "overrides" / "main.html"
JUSTFILE = ROOT / "Justfile"
WORKFLOW = ROOT / ".github" / "workflows" / "install-smoke.yml"


def _load_tool(name: str = "render_applicability_test") -> ModuleType:
    loader = SourceFileLoader(name, str(TOOL_PATH))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _load_install_renderer() -> ModuleType:
    loader = SourceFileLoader("render_install_command_test", str(INSTALL_RENDERER_PATH))
    spec = importlib.util.spec_from_loader("render_install_command_test", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def test_install_command_carries_version_floor() -> None:
    tool = _load_tool()
    assert tool.INSTALL_FLOOR == "0.18"
    assert tool.INSTALL_COMMAND == 'uv tool install "sase>=0.18"'


def test_pending_line_never_claims_an_unreleased_version() -> None:
    tool = _load_tool()
    text = tool.render_announce("0.17.1")
    assert "pending" in text
    assert "Latest release" not in text
    assert "v0.17.1" not in text


def test_released_line_names_the_manifest_version() -> None:
    tool = _load_tool()
    text = tool.render_announce("0.18.0")
    assert "Latest release" in text
    assert "v0.18.0" in text
    assert "pending" not in text


def test_documented_pages_carry_the_single_sourced_command(
    tmp_path: Path,
) -> None:
    tool = _load_tool()
    for relative in tool.DOCUMENTED_COMMAND_FILES:
        body = (ROOT / relative).read_text(encoding="utf-8")
        assert tool.INSTALL_COMMAND in body, relative

    manifest = tmp_path / "manifest.json"
    manifest.write_text('{" . ": "0.17.1"}'.replace(" ", ""), encoding="utf-8")
    partial = tmp_path / "release_announce.html"
    assert tool.check(manifest_path=manifest, partial_path=partial) != []
    tool.render(manifest_path=manifest, partial_path=partial)
    assert tool.check(manifest_path=manifest, partial_path=partial) == []


def test_announce_banner_renders_and_hides_from_pdf() -> None:
    body = MAIN_HTML.read_text(encoding="utf-8")
    assert "{% block announce %}" in body
    assert "generated/release_announce.html" in body
    assert "config.extra.pdf_handbook" in body

    config = yaml.safe_load(MKDOCS_CONFIG.read_text(encoding="utf-8"))
    assert "announce.dismiss" in config["theme"]["features"]


def test_smoke_workflow_reads_the_single_sourced_command() -> None:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = data[True]
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers

    steps = data["jobs"]["install-smoke"]["steps"]
    run_steps = " ".join(
        str(step.get("run", "")) for step in steps if isinstance(step, dict)
    )
    assert "tools/render_applicability --install-command" in run_steps
    assert "tools/render_applicability --check-installed" in run_steps
    assert "sase doctor -j" in run_steps
    assert "--strict" not in run_steps


def test_install_command_is_generated_in_start_and_homepage(tmp_path: Path) -> None:
    tool = _load_tool()
    renderer = _load_install_renderer()
    install_page = tmp_path.joinpath("docs", "start", "install.md")
    install_page.parent.mkdir(parents=True)
    install_page.write_text("## 1. Install SASE\n", encoding="utf-8")
    homepage = tmp_path.joinpath("docs", "index.md")
    homepage.write_text('    <div class="sase-actions">\n', encoding="utf-8")

    renderer.render(tmp_path)

    for path in (install_page, homepage):
        text = path.read_text(encoding="utf-8")
        assert "<!-- BEGIN GENERATED: install-command -->" in text
        assert tool.INSTALL_COMMAND in text
        assert "<!-- END GENERATED: install-command -->" in text
    assert "tutorial-test: skip installs the published package from PyPI" in (
        install_page.read_text(encoding="utf-8")
    )
    assert renderer.check(tmp_path) == []


def test_fmt_docs_recipes_cover_applicability() -> None:
    recipe = JUSTFILE.read_text(encoding="utf-8")
    assert "python tools/render_docs --format-only" in recipe
    assert "python tools/render_docs --format-only --check" in recipe
    runner = SourceFileLoader("render_docs_test", str(RENDER_DOCS_PATH))
    spec = importlib.util.spec_from_loader("render_docs_test", runner)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["render_docs_test"] = module
    runner.exec_module(module)
    assert any(
        source.name == "applicability"
        and source.script == "render_applicability"
        and not source.needs_sase
        for source in module.SOURCES
    )
    assert any(
        source.name == "install-command"
        and source.script == "render_install_command"
        and not source.needs_sase
        for source in module.SOURCES
    )
