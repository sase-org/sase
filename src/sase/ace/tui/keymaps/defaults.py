"""Load bundled keymap defaults from ``default_config.yml``."""

import functools
import importlib.resources
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from sase._yaml_safe import yaml_safe_load
from sase.ace.tui.keymaps.key_validation import canonicalize_key_binding


@functools.cache
def _builtin_keymaps_config() -> Mapping[str, Any]:
    """Parse and cache the bundled keymap configuration."""

    ref = importlib.resources.files("sase").joinpath("default_config.yml")
    text = ref.read_text(encoding="utf-8")
    data = yaml_safe_load(text)
    if not isinstance(data, dict):
        msg = "default_config.yml is not a valid YAML mapping"
        raise RuntimeError(msg)
    keymaps = data.get("ace", {}).get("keymaps", {})
    if not isinstance(keymaps, dict):
        msg = "default_config.yml missing ace.keymaps section"
        raise RuntimeError(msg)
    return MappingProxyType(keymaps)


@functools.cache
def _builtin_scope_defaults(scope: str) -> Mapping[str, str]:
    """Cache one keymap scope's bundled defaults, keyed by *scope* name."""

    section = _builtin_keymaps_config().get(scope, {})
    if not isinstance(section, dict):
        msg = f"default_config.yml missing ace.keymaps.{scope} section"
        raise RuntimeError(msg)
    return MappingProxyType(
        {k: canonicalize_key_binding(str(v)) for k, v in section.items()}
    )


def load_builtin_app_defaults() -> dict[str, str]:
    """Load app-level keymap defaults from bundled configuration.

    Returns a fresh ``dict`` per call; callers may freely mutate it without
    corrupting the cached parse.
    """

    return dict(_builtin_scope_defaults("app"))


def load_builtin_statistics_defaults() -> dict[str, str]:
    """Return a mutable copy of bundled focused Statistics-pane defaults."""

    return dict(_builtin_scope_defaults("statistics"))


def load_builtin_gate_defaults() -> dict[str, str]:
    """Return a mutable copy of bundled focused gate-modal defaults."""

    return dict(_builtin_scope_defaults("gate"))


def load_builtin_glossary_defaults() -> dict[str, str]:
    """Return a mutable copy of bundled focused Glossary-panel defaults."""

    return dict(_builtin_scope_defaults("glossary"))


def load_builtin_projects_defaults() -> dict[str, str]:
    """Return a mutable copy of bundled focused Projects-pane defaults."""

    return dict(_builtin_scope_defaults("projects"))
