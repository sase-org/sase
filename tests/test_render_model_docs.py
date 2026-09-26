"""Tests for the extensionless model-docs renderer."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import sys
from types import ModuleType

import pytest

from sase.llm_provider import model_manifest
from sase.llm_provider.model_alias_policy import (
    implicit_alias_targets,
    role_alias_descriptions,
    role_alias_fallbacks,
)
from sase.llm_provider.model_policy import validate_manifest_policy

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "render_model_docs"


def _load_renderer(name: str = "render_model_docs_test") -> ModuleType:
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
        _load_renderer("render_model_docs_no_runtime")
        assert not [
            name for name in sys.modules if name.startswith("sase.llm_provider")
        ]
    finally:
        sys.modules.update(removed)


def test_renderer_alias_table_matches_runtime_loaded_defaults(
    real_model_alias_defaults: None,
) -> None:
    renderer = _load_renderer("render_model_docs_alias_parity")
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


def test_renderer_catalog_tables_match_manifest_accessors(
    real_model_alias_defaults: None,
) -> None:
    renderer = _load_renderer("render_model_docs_catalog_parity")
    known = renderer._render_known_models_table()
    shorthands = renderer._render_short_alias_table()
    tiers = renderer._render_tier_defaults_table()

    for provider in model_manifest.manifest_provider_names():
        assert provider in known
        for model in model_manifest.provider_model_names(provider):
            assert f"`{model}`" in known
        for model, short in model_manifest.provider_short_aliases(provider).items():
            assert f"`{model}` → `{short}`" in shorthands
        for tier in ("large", "small"):
            assert f"`{model_manifest.provider_tier_model(provider, tier)}`" in tiers
        provider_block = renderer._render_provider_tier_table(None, provider)
        assert f"`{model_manifest.provider_tier_model(provider, 'large')}`" in (
            provider_block
        )
        assert f"`{model_manifest.provider_tier_model(provider, 'small')}`" in (
            provider_block
        )


def _synthetic_manifest_text() -> str:
    return """schema_version: 1
providers:
  claude:
    models: [c-large, c-small]
    tiers: {large: c-large, small: c-small}
    short_aliases: {c-large: cl}
  codex:
    models: [x-big, x-small]
    tiers: {large: x-big, small: x-small}
aliases:
  xlarge:
    target: "claude/c-large@xhigh || codex/x-big@xhigh"
    description: Extra-large launch alias.
  large:
    target: "claude/c-large@high | codex/x-big@xhigh"
    description: Large launch alias.
  medium:
    target: "claude/c-small@xhigh | codex/x-small@xhigh"
    description: Medium launch alias.
  small:
    target: "claude/c-small@high | codex/x-small@high"
    description: Small launch alias.
  xsmall:
    target: "claude/c-small@medium | codex/x-small@medium"
    description: Extra-small launch alias.
"""


def _write_synthetic_tree(tmp_path: Path) -> tuple[Path, Path]:
    manifest = tmp_path / "models.yml"
    manifest.write_text(_synthetic_manifest_text(), encoding="utf-8")
    docs = tmp_path / "llms.md"
    renderer = _load_renderer("render_model_docs_synthetic_markers")
    parts = ["# Models"]
    for marker, _render in renderer._block_renderers(manifest):
        begin, end = renderer._block_markers(marker)
        parts.append(f"{begin}\n\nstale\n\n{end}")
    docs.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    return docs, manifest


def test_synthetic_manifest_update_regenerates_cleanly(tmp_path: Path) -> None:
    """One hand-edited manifest regenerates every block with no policy breach."""
    renderer = _load_renderer("render_model_docs_synthetic")
    docs, manifest = _write_synthetic_tree(tmp_path)

    # The synthetic bundle is policy-clean on its own.
    parsed = model_manifest._parse_model_manifest(
        manifest.read_text(encoding="utf-8"), source="synthetic test manifest"
    )
    assert validate_manifest_policy(parsed) == ()

    assert renderer.render_docs(docs, manifest) is True
    assert renderer.check_docs(docs, manifest) == []
    assert renderer.render_docs(docs, manifest) is False
    text = docs.read_text(encoding="utf-8")
    assert "`c-large`" in text and "`x-big`" in text
    assert "stale" not in text


def test_check_passes_on_current_generated_blocks() -> None:
    renderer = _load_renderer("render_model_docs_check_clean")
    assert renderer.check_docs() == []
    assert renderer.main(["--check"]) == 0


def test_check_reports_stale_block_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    renderer = _load_renderer("render_model_docs_check_stale")
    docs, manifest = _write_synthetic_tree(tmp_path)

    before = docs.read_text(encoding="utf-8")
    diff = renderer.check_docs(docs, manifest)
    assert diff
    assert any(line.startswith(("+", "-")) and "stale" in line for line in diff)
    assert docs.read_text(encoding="utf-8") == before

    monkeypatch.setattr(renderer, "DOCS_PATH", docs)
    monkeypatch.setattr(renderer, "MANIFEST_PATH", manifest)
    assert renderer.main(["--check"]) == 1
    assert docs.read_text(encoding="utf-8") == before


def test_renderer_rejects_malformed_alias_input(tmp_path: Path) -> None:
    renderer = _load_renderer("render_model_docs_malformed")
    manifest = tmp_path / "models.yml"
    manifest.write_text(
        "providers:\n"
        "  claude:\n"
        "    models: [c-large, c-small]\n"
        "    tiers: {large: c-large, small: c-small}\n"
        "aliases:\n  small:\n    description: Small alias.\n    target: 12\n",
        encoding="utf-8",
    )

    try:
        renderer._declared_aliases(manifest)
    except ValueError as exc:
        assert "non-string target" in str(exc)
    else:
        raise AssertionError("malformed renderer input was accepted")


def test_renderer_rejects_unknown_tier_model(tmp_path: Path) -> None:
    renderer = _load_renderer("render_model_docs_bad_tier")
    manifest = tmp_path / "models.yml"
    manifest.write_text(
        "providers:\n"
        "  claude:\n"
        "    models: [c-large]\n"
        "    tiers: {large: c-large, small: c-small}\n"
        "aliases:\n"
        "  small:\n"
        "    description: Small alias.\n"
        '    target: "claude/c-large@high"\n',
        encoding="utf-8",
    )

    try:
        renderer._render_tier_defaults_table(manifest)
    except ValueError as exc:
        assert "tier 'small'" in str(exc)
    else:
        raise AssertionError("unknown tier model was accepted")
