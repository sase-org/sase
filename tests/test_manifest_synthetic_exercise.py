"""Phase-3 proof: one manifest edit reaches every model surface.

A synthetic built-in model plus a tier retune and a size-alias selector
retune are derived from the shipped ``models.yml`` (never hand-written from
scratch). The test shows generated docs are the only derived diff and that
registry hooks, routing, alias resolution, picker visibility, TUI
completion, and the LSP payload all observe the synthetic model with no
Python source change.
"""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest
import yaml  # type: ignore[import-untyped]

from sase.llm_provider import model_alias_policy, model_manifest, registry
from sase.llm_provider.config import resolve_model_alias_with_effort
from sase.llm_provider.load_balancing import (
    concatenated_selector_members,
    parse_model_alias_selector,
)
from sase.llm_provider.model_alias_policy import implicit_alias_targets
from sase.llm_provider.model_policy import validate_manifest_policy
from sase.xprompt import model_completion

from tests._xprompt_model_completion_helpers import (
    clear_model_completion_cache as clear_model_completion_cache,
)

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "render_model_docs"
SHIPPED_MANIFEST = files("sase.llm_provider").joinpath("models.yml")

SYNTHETIC_MODEL = "claude-synthetic-proof-9"
SYNTHETIC_SHORT_ALIAS = "synth9"


def _load_renderer(name: str) -> ModuleType:
    loader = SourceFileLoader(name, str(TOOL_PATH))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _synthetic_manifest_text() -> str:
    """Derive the synthetic manifest from the shipped file with one edit."""
    data = yaml.safe_load(SHIPPED_MANIFEST.read_text(encoding="utf-8"))
    claude = data["providers"]["claude"]
    claude["models"] = [*claude["models"], SYNTHETIC_MODEL]
    claude["short_aliases"] = {
        **claude.get("short_aliases", {}),
        SYNTHETIC_MODEL: SYNTHETIC_SHORT_ALIAS,
    }
    claude["tiers"] = {**claude["tiers"], "small": SYNTHETIC_MODEL}
    medium_target = data["aliases"]["medium"]["target"]
    assert "claude/sonnet@xhigh" in medium_target
    data["aliases"]["medium"]["target"] = medium_target.replace(
        "claude/sonnet@xhigh",
        f"claude/sonnet@xhigh | claude/{SYNTHETIC_MODEL}@xhigh",
    )
    return yaml.safe_dump(data, sort_keys=False)


def _parse_synthetic() -> model_manifest.ModelManifest:
    return model_manifest._parse_model_manifest(
        _synthetic_manifest_text(), source="synthetic exercise manifest"
    )


def _install_synthetic_manifest(
    monkeypatch: pytest.MonkeyPatch,
    parsed: model_manifest.ModelManifest,
) -> None:
    """Route every manifest reader at the synthetic bundle for this test."""
    monkeypatch.setattr(model_manifest, "get_model_manifest", lambda: parsed)
    monkeypatch.setattr(model_alias_policy, "get_model_manifest", lambda: parsed)
    model_alias_policy._load_model_alias_defaults.cache_clear()
    registry._llm_metadata_payload.cache_clear()
    registry._provider_cli_available.cache_clear()
    model_completion._CATALOG_CACHE = None


def _restore_manifest_caches() -> None:
    model_alias_policy._load_model_alias_defaults.cache_clear()
    registry._llm_metadata_payload.cache_clear()
    registry._provider_cli_available.cache_clear()
    model_completion._CATALOG_CACHE = None


def _write_stale_docs(renderer: ModuleType, docs: Path, manifest: Path) -> None:
    parts = ["# Models"]
    for marker, _render in renderer._block_renderers(manifest):
        begin, end = renderer._block_markers(marker)
        parts.append(f"{begin}\n\nstale\n\n{end}")
    docs.write_text("\n\n".join(parts) + "\n", encoding="utf-8")


def test_synthetic_manifest_regenerates_docs_cleanly(tmp_path: Path) -> None:
    """Generated docs are the only derived diff of the synthetic edit."""
    renderer = _load_renderer("render_model_docs_manifest_exercise")
    parsed = _parse_synthetic()
    assert validate_manifest_policy(parsed) == ()

    manifest = tmp_path / "models.yml"
    manifest.write_text(_synthetic_manifest_text(), encoding="utf-8")
    docs = tmp_path / "llms.md"
    _write_stale_docs(renderer, docs, manifest)

    assert renderer.render_docs(docs, manifest) is True
    assert renderer.check_docs(docs, manifest) == []
    assert renderer.render_docs(docs, manifest) is False
    text = docs.read_text(encoding="utf-8")
    assert f"`{SYNTHETIC_MODEL}`" in text
    assert "stale" not in text
    # The exercise is reversible: the shipped bundle is untouched.
    assert SYNTHETIC_MODEL not in SHIPPED_MANIFEST.read_text(encoding="utf-8")


def test_synthetic_manifest_reaches_model_surfaces(
    monkeypatch: pytest.MonkeyPatch,
    real_model_alias_defaults: None,
) -> None:
    """One manifest edit reaches routing, aliases, picker, completion, LSP."""
    parsed = _parse_synthetic()
    assert validate_manifest_policy(parsed) == ()
    _install_synthetic_manifest(monkeypatch, parsed)
    try:
        # Registry hooks answer from the manifest.
        assert SYNTHETIC_MODEL in model_manifest.provider_model_names("claude")
        assert model_manifest.provider_tier_model("claude", "small") == (
            SYNTHETIC_MODEL
        )
        assert (
            model_manifest.provider_short_aliases("claude")[SYNTHETIC_MODEL]
            == SYNTHETIC_SHORT_ALIAS
        )
        plugins = dict(registry.iter_plugins())
        claude_plugin = cast(Any, plugins["claude"])
        assert SYNTHETIC_MODEL in claude_plugin.llm_known_model_names()
        assert claude_plugin.llm_resolve_model_name("small") == SYNTHETIC_MODEL
        assert claude_plugin.llm_model_short_aliases()[SYNTHETIC_MODEL] == (
            SYNTHETIC_SHORT_ALIAS
        )

        # Routing resolves the synthetic model explicitly and bare.
        assert registry.resolve_model_provider(f"claude/{SYNTHETIC_MODEL}") == (
            "claude",
            SYNTHETIC_MODEL,
        )
        assert registry.model_to_provider_map()[SYNTHETIC_MODEL] == "claude"
        assert registry.model_short_alias_map()[SYNTHETIC_MODEL] == (
            SYNTHETIC_SHORT_ALIAS
        )

        # Alias resolution carries the retuned selector member.
        medium_target = implicit_alias_targets()["medium"]
        assert f"claude/{SYNTHETIC_MODEL}@xhigh" in medium_target
        selector = parse_model_alias_selector(medium_target)
        assert selector is not None
        assert f"claude/{SYNTHETIC_MODEL}@xhigh" in (
            concatenated_selector_members(selector)
        )
        resolved = resolve_model_alias_with_effort("medium", consume=False)
        assert resolved.valid

        # Picker visibility: the synthetic model is a visible catalog row.
        assert "claude" not in registry.model_picker_hidden_provider_names()
        entries = model_completion.build_model_completion_catalog(use_cache=False)
        model_entries = {
            entry.value: entry for entry in entries if entry.kind == "model"
        }
        assert SYNTHETIC_MODEL in model_entries
        assert SYNTHETIC_SHORT_ALIAS in model_entries[SYNTHETIC_MODEL].aliases

        # TUI completion narrows to the synthetic model.
        filtered = {
            entry.value
            for entry in model_completion.filter_model_completion_entries(
                entries, "synth"
            )
        }
        assert SYNTHETIC_MODEL in filtered

        # LSP payload materializes the synthetic row.
        payload = model_completion.model_completion_catalog_payload()
        payload_entries = payload["entries"]
        assert isinstance(payload_entries, list)
        values = [
            row["value"]
            for row in payload_entries
            if isinstance(row, dict) and "value" in row
        ]
        assert SYNTHETIC_MODEL in values
    finally:
        _restore_manifest_caches()
