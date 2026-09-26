"""Tests for the bundled ``models.yml`` manifest loader.

Behavioral expectations (which models ship, which tier points where) stay
data-driven through the manifest itself: these tests pin the loader contract
(structure, validation diagnostics, immutability, hook agreement), not today's
catalog values.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest
import yaml  # type: ignore[import-untyped]

from sase.llm_provider import model_manifest
from sase.llm_provider.model_alias_policy import (
    implicit_alias_targets,
    role_alias_descriptions,
    role_alias_fallbacks,
)

_MANIFEST_PROVIDERS = (
    "agy",
    "claude",
    "codex",
    "grok",
    "muse",
    "opencode",
    "qwen",
)


def _manifest_dict() -> dict:
    """Return a minimal valid manifest mapping for negative tests."""
    return {
        "schema_version": 1,
        "providers": {
            "alpha": {
                "models": ["m1", "m2"],
                "short_aliases": {"m1": "a1"},
                "tiers": {"large": "m1", "small": "m2"},
            },
            "beta": {
                "models": ["n1"],
                "tiers": {"large": "n1", "small": "n1"},
                "supersedes": {},
                "advisories": {
                    "n1": {
                        "severity": "info",
                        "label": "preview",
                        "detail": "A preview model.",
                    }
                },
            },
        },
        "aliases": {
            "xsmall": {"target": "alpha/m1", "description": "xsmall."},
            "small": {"target": "alpha/m1", "description": "small."},
            "medium": {"target": "alpha/m1", "description": "medium."},
            "large": {"target": "alpha/m1", "description": "large."},
            "xlarge": {"target": "alpha/m1", "description": "xlarge."},
        },
    }


def _parse(data: dict) -> model_manifest.ModelManifest:
    return model_manifest._parse_model_manifest(
        yaml.safe_dump(data, sort_keys=False),
        source="test manifest",
    )


def _break(path: tuple, value) -> dict:
    """Return the minimal manifest with *value* set at nested *path*."""
    data = _manifest_dict()
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return data


def test_shipped_manifest_declares_exactly_the_seven_user_facing_providers(
    real_model_alias_defaults: None,
) -> None:
    assert model_manifest.manifest_provider_names() == _MANIFEST_PROVIDERS
    assert "fakey" not in model_manifest.get_model_manifest().providers


def test_shipped_manifest_is_internally_consistent(
    real_model_alias_defaults: None,
) -> None:
    manifest = model_manifest.get_model_manifest()
    for name, record in manifest.providers.items():
        assert record.models, name
        assert set(record.tiers) == {"large", "small"}, name
        for tier, tier_model in record.tiers.items():
            assert tier_model in record.models, (name, tier)
        for aliased in record.short_aliases:
            assert aliased in record.models, (name, aliased)
        for advised in record.advisories:
            assert advised in record.models, (name, advised)
        for successor, predecessor in record.supersedes.items():
            assert successor in record.models, (name, successor)
            assert predecessor in record.models, (name, predecessor)


def test_provider_hooks_agree_with_the_manifest(
    real_model_alias_defaults: None,
) -> None:
    from sase.llm_provider import registry

    for name, plugin in registry.iter_plugins():
        if name not in _MANIFEST_PROVIDERS:
            continue
        assert list(plugin.llm_known_model_names()) == list(
            model_manifest.provider_model_names(name)
        )
        short_aliases = getattr(plugin, "llm_model_short_aliases", None)
        assert (short_aliases() if short_aliases is not None else {}) == (
            model_manifest.provider_short_aliases(name)
        )
        advisories = getattr(plugin, "llm_model_advisories", None)
        assert (advisories() if advisories is not None else {}) == (
            model_manifest.provider_model_advisories(name)
        )
        for tier in ("large", "small"):
            assert plugin.llm_resolve_model_name(tier) == (
                model_manifest.provider_tier_model(name, tier)
            )


def test_manifest_alias_views_match_the_policy_accessors(
    real_model_alias_defaults: None,
) -> None:
    manifest = model_manifest.get_model_manifest()
    assert dict(manifest.alias_targets) == dict(implicit_alias_targets())
    assert dict(manifest.alias_fallbacks) == dict(role_alias_fallbacks())
    assert dict(manifest.alias_descriptions) == dict(role_alias_descriptions())


def test_manifest_loader_is_cached_and_immutable() -> None:
    first = model_manifest.get_model_manifest()
    assert model_manifest.get_model_manifest() is first
    assert isinstance(first.providers, MappingProxyType)
    with pytest.raises(TypeError):
        first.providers["nope"] = first.providers["grok"]  # type: ignore[index]
    record = first.providers["grok"]
    assert isinstance(record.short_aliases, MappingProxyType)
    assert isinstance(record.tiers, MappingProxyType)


def test_unknown_provider_raises_installation_defect() -> None:
    with pytest.raises(RuntimeError, match="installation defect"):
        model_manifest.provider_tier_model("nope", "large")


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("schema_version",), 2, "schema_version must be 1"),
        (("extra",), {}, "unknown top-level keys"),
        (("providers", "alpha", "bogus"), 1, "unknown keys"),
        (
            ("providers", "alpha", "tiers", "large"),
            "missing-model",
            "unknown model",
        ),
        (
            ("providers", "alpha", "short_aliases"),
            {"missing-model": "a9"},
            "unknown model",
        ),
        (
            ("providers", "alpha", "supersedes"),
            {"m1": "missing-model"},
            "unknown model",
        ),
        (
            ("providers", "alpha", "advisories"),
            {
                "m1": {
                    "severity": "warn",
                    "label": "x",
                    "detail": "y",
                    "bogus": 1,
                }
            },
            "unknown keys",
        ),
        (
            ("providers", "alpha", "advisories"),
            {"m1": {"severity": "catastrophe", "label": "x", "detail": "y"}},
            "invalid severity",
        ),
    ],
)
def test_malformed_manifest_is_rejected(path: tuple, value, match: str) -> None:
    with pytest.raises(RuntimeError, match=match):
        _parse(_break(path, value))


def test_duplicate_bare_model_across_providers_is_rejected() -> None:
    data = _manifest_dict()
    data["providers"]["beta"]["models"] = ["m1"]
    data["providers"]["beta"]["tiers"] = {"large": "m1", "small": "m1"}
    data["providers"]["beta"]["advisories"] = {}
    with pytest.raises(RuntimeError, match="claimed by both"):
        _parse(data)


def test_short_alias_shadowing_a_bare_model_is_rejected() -> None:
    data = _manifest_dict()
    data["providers"]["alpha"]["short_aliases"] = {"m1": "n1"}
    with pytest.raises(RuntimeError, match="ambiguous with a bare model"):
        _parse(data)


def test_supersedes_cycle_is_rejected() -> None:
    data = _manifest_dict()
    data["providers"]["alpha"]["supersedes"] = {"m1": "m2", "m2": "m1"}
    with pytest.raises(RuntimeError, match="cycle"):
        _parse(data)


def test_alias_grammar_violations_are_rejected() -> None:
    data = _manifest_dict()
    data["aliases"]["small"] = {"target": "alpha/m1 || || beta/n1"}
    with pytest.raises(RuntimeError, match="small"):
        _parse(data)
