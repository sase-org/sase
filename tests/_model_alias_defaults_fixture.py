"""Frozen model-alias defaults for tests that assert resolution behavior.

Shipped-value changes in ``model_alias_defaults.yml`` need no change here.
Shipped graph-shape changes are code changes: if an alias switches between
target, fallback, or neither, or a fallback points to a different alias, update
this map to match. Keeping the frozen values distinct from the shipped file
makes value coupling visible while preserving the alias graph as a contract.
"""

from __future__ import annotations

from collections.abc import Mapping
import functools
from types import MappingProxyType

import pytest
import yaml  # type: ignore[import-untyped]

from sase.llm_provider.load_balancing import parse_model_alias_selector
from sase.llm_provider import model_alias_policy
from sase.llm_provider.model_alias_policy import (
    BIG_EPIC_LANDER_MODEL_ALIAS_NAME,
    CHEAP_MODEL_ALIAS_NAME,
    CHEAPER_MODEL_ALIAS_NAME,
    CHEAPEST_MODEL_ALIAS_NAME,
    DEFAULT_MODEL_ALIAS_NAME,
    EPIC_LANDER_MODEL_ALIAS_NAME,
    LARGE_WORKER_MODEL_ALIAS_NAME,
    MEDIUM_WORKER_MODEL_ALIAS_NAME,
    SMALL_WORKER_MODEL_ALIAS_NAME,
    SMART_MODEL_ALIAS_NAME,
    SMARTEST_MODEL_ALIAS_NAME,
    XLARGE_WORKER_MODEL_ALIAS_NAME,
    XSMALL_WORKER_MODEL_ALIAS_NAME,
    _ModelAliasDefaults,
)
from sase.xprompt.effort import split_model_effort

_FROZEN_ALIASES: dict[str, dict[str, str]] = {
    DEFAULT_MODEL_ALIAS_NAME: {
        "description": "Frozen test description for default.",
    },
    EPIC_LANDER_MODEL_ALIAS_NAME: {
        "fallback": "@default",
        "description": "Frozen test description for epic_lander.",
    },
    BIG_EPIC_LANDER_MODEL_ALIAS_NAME: {
        "fallback": "@smartest",
        "description": "Frozen test description for big_epic_lander.",
    },
    XSMALL_WORKER_MODEL_ALIAS_NAME: {
        "fallback": "@cheaper",
        "description": "Frozen test description for xsmall_worker.",
    },
    SMALL_WORKER_MODEL_ALIAS_NAME: {
        "fallback": "@cheap",
        "description": "Frozen test description for small_worker.",
    },
    MEDIUM_WORKER_MODEL_ALIAS_NAME: {
        "target": "codex/o3@high",
        "description": "Frozen test description for medium_worker.",
    },
    LARGE_WORKER_MODEL_ALIAS_NAME: {
        "fallback": "@smart",
        "description": "Frozen test description for large_worker.",
    },
    XLARGE_WORKER_MODEL_ALIAS_NAME: {
        "fallback": "@smartest",
        "description": "Frozen test description for xlarge_worker.",
    },
    SMART_MODEL_ALIAS_NAME: {
        "fallback": "@default",
        "description": "Frozen test description for smart.",
    },
    SMARTEST_MODEL_ALIAS_NAME: {
        "target": "claude/sonnet@max",
        "description": "Frozen test description for smartest.",
    },
    CHEAP_MODEL_ALIAS_NAME: {
        "target": "claude/haiku@low | codex/gpt-4.1@low",
        "description": "Frozen test description for cheap.",
    },
    CHEAPER_MODEL_ALIAS_NAME: {
        "target": "claude/haiku@minimal | codex/gpt-4.1-mini@low",
        "description": "Frozen test description for cheaper.",
    },
    CHEAPEST_MODEL_ALIAS_NAME: {
        "target": "claude/haiku@minimal | codex/gpt-4o-mini",
        "description": "Frozen test description for cheapest.",
    },
}

FROZEN_TARGETS: Mapping[str, str] = MappingProxyType(
    {
        name: entry["target"]
        for name, entry in _FROZEN_ALIASES.items()
        if "target" in entry
    }
)
FROZEN_FALLBACKS: Mapping[str, str] = MappingProxyType(
    {
        name: entry["fallback"]
        for name, entry in _FROZEN_ALIASES.items()
        if "fallback" in entry
    }
)
FROZEN_DESCRIPTIONS: Mapping[str, str] = MappingProxyType(
    {name: entry["description"] for name, entry in _FROZEN_ALIASES.items()}
)
FROZEN_TARGET_DETAILS: Mapping[str, tuple[str, str | None]] = MappingProxyType(
    {name: split_model_effort(target) for name, target in FROZEN_TARGETS.items()}
)


def _selector_member_details(raw: str) -> tuple[tuple[str, str | None], ...]:
    selector = parse_model_alias_selector(raw)
    if selector is None:
        return ()
    return tuple(split_model_effort(member) for member in selector.members)


FROZEN_SELECTOR_MEMBER_DETAILS: Mapping[str, tuple[tuple[str, str | None], ...]] = (
    MappingProxyType(
        {
            name: _selector_member_details(target)
            for name, target in FROZEN_TARGETS.items()
        }
    )
)


def _shape_signature(
    entries: Mapping[str, Mapping[str, str]],
) -> Mapping[str, tuple[str, str | None]]:
    shape: dict[str, tuple[str, str | None]] = {}
    for name, entry in entries.items():
        if "target" in entry:
            shape[name] = ("target", None)
            continue
        fallback = entry.get("fallback")
        if fallback is not None:
            clean_reference, _effort = split_model_effort(fallback)
            shape[name] = ("fallback", clean_reference[1:])
            continue
        shape[name] = ("empty", None)
    return MappingProxyType(shape)


FROZEN_ALIAS_SHAPE = _shape_signature(_FROZEN_ALIASES)


def frozen_provider_model(alias: str) -> tuple[str, str]:
    target, _effort = FROZEN_TARGET_DETAILS[alias]
    provider, model = target.split("/", 1)
    return provider, model


def frozen_provider_model_effort(alias: str) -> tuple[str, str, str | None]:
    target, effort = FROZEN_TARGET_DETAILS[alias]
    provider, model = target.split("/", 1)
    return provider, model, effort


def frozen_selector_member(alias: str, index: int) -> tuple[str, str | None]:
    return FROZEN_SELECTOR_MEMBER_DETAILS[alias][index]


def frozen_selector_provider_model_effort(
    alias: str, index: int
) -> tuple[str, str, str | None]:
    target, effort = frozen_selector_member(alias, index)
    provider, model = target.split("/", 1)
    return provider, model, effort


def frozen_alias_defaults_yaml(
    aliases: Mapping[str, Mapping[str, str]] | None = None,
) -> str:
    """Return fixture defaults YAML, optionally with caller-supplied aliases."""
    return yaml.safe_dump(
        {
            "schema_version": 1,
            "aliases": _FROZEN_ALIASES if aliases is None else aliases,
        },
        sort_keys=False,
    )


@functools.cache
def _frozen_model_alias_defaults() -> _ModelAliasDefaults:
    return model_alias_policy._parse_model_alias_defaults(
        frozen_alias_defaults_yaml(),
        source="tests._model_alias_defaults_fixture",
    )


def install_frozen_model_alias_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    frozen = _frozen_model_alias_defaults()
    monkeypatch.setattr(
        model_alias_policy, "_load_model_alias_defaults", lambda: frozen
    )
