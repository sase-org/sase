"""Load bundled keymap defaults from ``default_config.yml``."""

import functools
import importlib.resources
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.ace.tui.keymaps.key_validation import canonicalize_key_binding


@functools.cache
def _builtin_keymaps_config() -> Mapping[str, Any]:
    """Parse and cache the bundled keymap configuration."""

    ref = importlib.resources.files("sase").joinpath("default_config.yml")
    text = ref.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        msg = "default_config.yml is not a valid YAML mapping"
        raise RuntimeError(msg)
    keymaps = data.get("ace", {}).get("keymaps", {})
    if not isinstance(keymaps, dict):
        msg = "default_config.yml missing ace.keymaps section"
        raise RuntimeError(msg)
    return MappingProxyType(keymaps)


@functools.cache
def _builtin_app_defaults() -> Mapping[str, str]:
    """Cache app-level defaults from the bundled configuration."""

    app = _builtin_keymaps_config().get("app", {})
    if not isinstance(app, dict):
        msg = "default_config.yml missing ace.keymaps.app section"
        raise RuntimeError(msg)
    return MappingProxyType(
        {k: canonicalize_key_binding(str(v)) for k, v in app.items()}
    )


def load_builtin_app_defaults() -> dict[str, str]:
    """Load app-level keymap defaults from bundled configuration.

    Returns a fresh ``dict`` per call; callers may freely mutate it without
    corrupting the cached parse.
    """

    return dict(_builtin_app_defaults())


@functools.cache
def _builtin_statistics_defaults() -> Mapping[str, str]:
    """Cache focused Statistics-pane defaults from bundled configuration."""

    statistics = _builtin_keymaps_config().get("statistics", {})
    if not isinstance(statistics, dict):
        msg = "default_config.yml missing ace.keymaps.statistics section"
        raise RuntimeError(msg)
    return MappingProxyType(
        {k: canonicalize_key_binding(str(v)) for k, v in statistics.items()}
    )


def load_builtin_statistics_defaults() -> dict[str, str]:
    """Return a mutable copy of bundled focused Statistics-pane defaults."""

    return dict(_builtin_statistics_defaults())


@functools.cache
def _builtin_gate_defaults() -> Mapping[str, str]:
    """Cache focused gate-modal defaults from bundled configuration."""

    gate = _builtin_keymaps_config().get("gate", {})
    if not isinstance(gate, dict):
        msg = "default_config.yml missing ace.keymaps.gate section"
        raise RuntimeError(msg)
    return MappingProxyType(
        {k: canonicalize_key_binding(str(v)) for k, v in gate.items()}
    )


def load_builtin_gate_defaults() -> dict[str, str]:
    """Return a mutable copy of bundled focused gate-modal defaults."""

    return dict(_builtin_gate_defaults())
