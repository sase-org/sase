"""Glossary and design-decision renderers emit Prettier-stable Markdown."""

from __future__ import annotations

import importlib.util
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

PRETTIER = ROOT / "node_modules" / ".bin" / "prettier"

needs_repo_prettier = pytest.mark.skipif(
    not PRETTIER.is_file(), reason="repo Prettier is unavailable"
)


def _load(name: str, path: Path) -> ModuleType:
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def _generated_outputs() -> dict[str, str]:
    glossary = _load("render_glossary_prettier_test", TOOLS / "render_glossary")
    decisions = _load(
        "render_design_decisions_prettier_test", TOOLS / "render_design_decisions"
    )
    outputs: dict[str, str] = {}
    for path, content in glossary.generated_outputs().items():
        outputs[path.relative_to(ROOT).as_posix()] = content
    for path, content in decisions.generated_outputs().items():
        outputs[path.relative_to(ROOT).as_posix()] = content
    return outputs


@needs_repo_prettier
def test_renderer_outputs_survive_repo_prettier_unchanged() -> None:
    """Generated glossary/decision pages must already be Prettier-formatted.

    ``just fix`` renders before its Prettier pass, so any rewrite Prettier
    performs shows up as ``fmt-docs-check`` drift. This fails loudly if a
    renderer change reintroduces unstable emphasis or unwrapped prose.
    """
    outputs = _generated_outputs()
    assert outputs, "expected glossary and design-decision outputs"
    for relative, content in sorted(outputs.items()):
        proc = subprocess.run(
            [str(PRETTIER), "--stdin-filepath", relative],
            input=content,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(ROOT),
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == content, f"{relative} is not Prettier-stable"


def test_format_with_prettier_falls_back_without_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkout without the repo Prettier keeps the raw renderer text."""
    import docs_webs

    monkeypatch.setattr(docs_webs, "REPO_ROOT", tmp_path)
    assert docs_webs.format_with_prettier("untouched\n", "docs/x.md") == "untouched\n"
