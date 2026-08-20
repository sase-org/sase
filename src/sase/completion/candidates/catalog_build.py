"""Catalog fetchers for what this sase build ships.

Feature flags, installed plugins, and built-in model aliases are properties
of the running build rather than of any project; see
:mod:`sase.completion.candidates.catalog` for the import contract.
"""

from __future__ import annotations

from pathlib import Path

from sase.completion.candidates.protocol import Candidate

_BUILTIN_MODEL_ALIASES: tuple[str, ...] = (
    "xsmall",
    "small",
    "medium",
    "large",
    "xlarge",
)


def flag_source_path(_project: str | None) -> Path | None:
    """Return no cache-invalidation path: flag definitions are compiled in."""
    return None


def artifact_relation_source_path(_project: str | None) -> Path | None:
    """Return no cache-invalidation path: relations are compiled in."""

    return None


def artifact_relation_candidates(_project: str | None) -> list[Candidate]:
    """Return builtin artifact-link relation slugs."""

    from sase.core.rust import require_rust_binding

    try:
        rows = require_rust_binding("artifact_relations_builtins")()
    except Exception:  # noqa: BLE001 - completion must not traceback
        return []
    if not isinstance(rows, list):
        return []
    candidates: list[Candidate] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        slug = str(row.get("slug") or "")
        if not slug:
            continue
        inverse = str(row.get("inverse") or "")
        written_by = str(row.get("written_by") or "")
        description = f"inverse {inverse}" if inverse else written_by
        candidates.append(Candidate(slug, description))
    return candidates


def flag_candidates(_project: str | None) -> list[Candidate]:
    """Return every registered feature flag key, with kind and description."""
    from sase.feature_flags.registry import feature_flag_definitions

    return [
        Candidate(key, f"{definition.kind}: {definition.description}")
        for key, definition in feature_flag_definitions().items()
    ]


def plugin_source_path(_project: str | None) -> Path | None:
    """Return no cache-invalidation path: plugins come from the environment."""
    return None


def plugin_candidates(_project: str | None) -> list[Candidate]:
    """Return installed third-party plugin distributions and entry points."""
    from sase.plugins.inventory import collect_plugin_inventory

    inventory = collect_plugin_inventory(load_resource_entry_points=False)
    values: list[Candidate] = []
    seen: set[str] = set()
    for dist in inventory.distributions:
        if dist.package.casefold() == "sase" or dist.package in seen:
            continue
        seen.add(dist.package)
        values.append(Candidate(dist.package, dist.version))
    for entry in inventory.third_party_entry_points:
        if entry.name in seen:
            continue
        seen.add(entry.name)
        values.append(Candidate(entry.name, entry.package))
    return values


def model_source_path(_project: str | None) -> Path | None:
    """Return no cache-invalidation path: model aliases are compiled in."""
    return None


def model_candidates(_project: str | None) -> list[Candidate]:
    """Return the built-in model size aliases."""
    return [Candidate(name, "builtin model alias") for name in _BUILTIN_MODEL_ALIASES]


__all__ = [
    "artifact_relation_candidates",
    "artifact_relation_source_path",
    "flag_candidates",
    "flag_source_path",
    "model_candidates",
    "model_source_path",
    "plugin_candidates",
    "plugin_source_path",
]
