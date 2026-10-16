"""Tests for the venv-aware generated documentation source registry."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import sys
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "render_docs"


def _load_runner() -> ModuleType:
    loader = SourceFileLoader("render_docs_registry_test", str(TOOL_PATH))
    spec = importlib.util.spec_from_loader("render_docs_registry_test", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["render_docs_registry_test"] = module
    loader.exec_module(module)
    return module


def test_registry_wraps_existing_and_new_renderers() -> None:
    runner = _load_runner()

    assert runner.SOURCES[0].script == "render_model_docs"
    assert not runner.SOURCES[0].needs_sase
    assert {source.script for source in runner.SOURCES} >= {
        "render_model_docs",
        "render_applicability",
        "render_moves",
        "render_docs_map",
        "render_glossary",
        "render_design_decisions",
    }


def test_runner_selects_sources_by_environment_and_check_mode(tmp_path: Path) -> None:
    runner = _load_runner()
    for name in ("format", "application"):
        (tmp_path / "tools").mkdir(exist_ok=True)
        (tmp_path / "tools" / name).write_text(
            "from pathlib import Path\n"
            "def main(argv=None):\n"
            f"    Path({str(tmp_path / name)!r}).write_text(' '.join(argv or []))\n"
            "    return 0\n",
            encoding="utf-8",
        )
    sources = (
        runner.Source("format", "format", False),
        runner.Source("application", "application", True),
    )

    assert (
        runner.run(check=False, needs_sase=False, root=tmp_path, sources=sources) == 0
    )
    assert (tmp_path / "format").read_text(encoding="utf-8") == ""
    assert not (tmp_path / "application").exists()
    assert runner.run(check=True, needs_sase=True, root=tmp_path, sources=sources) == 0
    assert (tmp_path / "application").read_text(encoding="utf-8") == "--check"
