"""Tests for the extensionless model-alias docs renderer."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import sys
from types import ModuleType

from sase.llm_provider.model_alias_policy import (
    implicit_alias_targets,
    role_alias_descriptions,
    role_alias_fallbacks,
)

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "render_model_alias_docs"


def _load_renderer(name: str = "render_model_alias_docs_test") -> ModuleType:
    loader = SourceFileLoader(name, str(TOOL_PATH))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_renderer_import_does_not_load_llm_provider_runtime_modules() -> None:
    removed = {
        name: module
        for name, module in list(sys.modules.items())
        if name.startswith("sase.llm_provider")
    }
    for name in removed:
        sys.modules.pop(name, None)
    try:
        _load_renderer("render_model_alias_docs_no_runtime")
        assert not [
            name for name in sys.modules if name.startswith("sase.llm_provider")
        ]
    finally:
        sys.modules.update(removed)


def test_renderer_table_matches_runtime_loaded_defaults(
    real_model_alias_defaults: None,
) -> None:
    renderer = _load_renderer("render_model_alias_docs_parity")
    table = renderer._render_table()
    targets = implicit_alias_targets()
    fallbacks = role_alias_fallbacks()

    for alias, description in role_alias_descriptions().items():
        assert f"`@{alias}`" in table
        assert renderer._cell(description) in table
        if alias in targets:
            assert renderer._cell(f"`{targets[alias]}`") in table
        if alias in fallbacks:
            assert renderer._cell(f"`{fallbacks[alias]}`") in table


def test_renderer_rejects_malformed_alias_input(tmp_path: Path) -> None:
    renderer = _load_renderer("render_model_alias_docs_malformed")
    defaults = tmp_path / "model_alias_defaults.yml"
    defaults.write_text(
        "aliases:\n  small:\n    description: Small alias.\n    target: 12\n",
        encoding="utf-8",
    )

    try:
        renderer._declared_aliases(defaults)
    except ValueError as exc:
        assert "non-string target" in str(exc)
    else:
        raise AssertionError("malformed renderer input was accepted")
