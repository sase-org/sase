"""Parity tests for the LibYAML-preferring safe loader."""

from __future__ import annotations

import importlib.resources

import pytest
import yaml

from sase._yaml_safe import _safe_loader, yaml_safe_load


JSON_SHAPED_SAMPLES: tuple[str, ...] = (
    "",
    "null\n",
    "true\n",
    "42\n",
    "3.14\n",
    "'a plain string'\n",
    "unicode: caf\u00e9 \u2014 \u4f60\u597d\n",
    "nested:\n  a:\n    - 1\n    - 2\n    - {b: 3, c: [4, 5]}\n  d: null\n  e: true\n",
    "[]\n",
    "{}\n",
    "- 1\n- 2\n- 3\n",
)

MALFORMED_SAMPLES: tuple[str, ...] = (
    "invalid: yaml: [not closed",
    "a: !!python/object:os.system {}",
    "  bad indent\nfoo: bar\n",
)


def test_safe_loader_prefers_c_loader_when_available() -> None:
    """The C loader is selected whenever libyaml bindings are present."""
    if not hasattr(yaml, "CSafeLoader"):
        pytest.skip("environment's pyyaml build has no libyaml bindings")
    assert _safe_loader() is yaml.CSafeLoader


def test_safe_loader_falls_back_without_libyaml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing ``CSafeLoader`` attribute falls back to the pure-Python loader."""
    monkeypatch.delattr(yaml, "CSafeLoader", raising=False)
    assert _safe_loader() is yaml.SafeLoader


@pytest.mark.parametrize("text", JSON_SHAPED_SAMPLES)
def test_yaml_safe_load_matches_safe_load(text: str) -> None:
    """Every JSON-shaped fixture parses identically to ``yaml.safe_load``."""
    assert yaml_safe_load(text) == yaml.safe_load(text)


@pytest.mark.parametrize("text", JSON_SHAPED_SAMPLES)
def test_yaml_safe_load_matches_safe_load_without_libyaml(
    text: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pure-Python fallback path also matches ``yaml.safe_load``."""
    monkeypatch.delattr(yaml, "CSafeLoader", raising=False)
    assert yaml_safe_load(text) == yaml.safe_load(text)


@pytest.mark.parametrize("text", MALFORMED_SAMPLES)
def test_yaml_safe_load_raises_yaml_error_like_safe_load(text: str) -> None:
    """Malformed input raises the same ``yaml.YAMLError`` family as ``safe_load``."""
    with pytest.raises(yaml.YAMLError) as safe_load_exc_info:
        yaml.safe_load(text)
    with pytest.raises(yaml.YAMLError) as fast_load_exc_info:
        yaml_safe_load(text)
    assert type(fast_load_exc_info.value) is type(safe_load_exc_info.value)


def test_yaml_safe_load_matches_default_config_yml() -> None:
    """The bundled default config parses identically through both loaders."""
    ref = importlib.resources.files("sase").joinpath("default_config.yml")
    text = ref.read_text(encoding="utf-8")
    assert yaml_safe_load(text) == yaml.safe_load(text)
