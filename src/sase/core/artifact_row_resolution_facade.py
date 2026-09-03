"""Typed Python boundary for artifact-link row resolution.

All matching rules live in :mod:`sase_core_rs`; this module only converts
between :class:`ArtifactEntryTarget` and plain Rust binding dictionaries.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.rust import require_rust_binding


@lru_cache(maxsize=1)
def _wire_schema_version() -> int:
    binding = require_rust_binding("artifact_row_resolution_wire_schema_version")
    return int(binding())


def parse_artifact_link_ref(value: str) -> tuple[str, str] | None:
    binding = require_rust_binding("artifact_link_ref_parts")
    payload = binding(value)
    if payload is None:
        return None
    return str(payload["kind"]), str(payload["payload"])


def artifact_row_index_keys(
    targets: Sequence[ArtifactEntryTarget],
) -> tuple[tuple[tuple[str, ...], ...], ...]:
    binding = require_rust_binding("artifact_row_index_keys")
    batches = binding([_target_to_wire(target) for target in targets])
    return tuple(_keys_from_wire(keys) for keys in batches)


def artifact_row_ref_lookup_keys(
    kind: str,
    payload: str,
    *,
    project_hint: str | None = None,
    agent_name_candidates: Sequence[str] = (),
) -> tuple[tuple[str, ...], ...]:
    binding = require_rust_binding("artifact_row_ref_lookup_keys")
    keys = binding(
        _query_to_wire(
            kind,
            payload,
            project_hint=project_hint,
            agent_name_candidates=agent_name_candidates,
        )
    )
    return _keys_from_wire(keys)


def resolve_artifact_row_target(
    kind: str,
    payload: str,
    candidates: Sequence[ArtifactEntryTarget],
    *,
    project_hint: str | None = None,
    agent_name_candidates: Sequence[str] = (),
) -> ArtifactEntryTarget | None:
    binding = require_rust_binding("artifact_row_resolve")
    resolved = binding(
        _query_to_wire(
            kind,
            payload,
            project_hint=project_hint,
            agent_name_candidates=agent_name_candidates,
        ),
        [_target_to_wire(candidate) for candidate in candidates],
    )
    if resolved is None:
        return None
    return _target_from_wire(resolved)


def _query_to_wire(
    kind: str,
    payload: str,
    *,
    project_hint: str | None,
    agent_name_candidates: Sequence[str],
) -> dict[str, Any]:
    return {
        "schema_version": _wire_schema_version(),
        "kind": kind,
        "payload": payload,
        "project_hint": project_hint,
        "agent_name_candidates": list(agent_name_candidates),
    }


def _target_to_wire(target: ArtifactEntryTarget) -> dict[str, Any]:
    return {"pane_id": target.pane_id, "parts": list(target.parts)}


def _target_from_wire(payload: Mapping[str, Any]) -> ArtifactEntryTarget:
    return ArtifactEntryTarget(
        str(payload["pane_id"]),
        tuple(str(part) for part in payload["parts"]),
    )


def _keys_from_wire(keys: Sequence[Sequence[Any]]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(str(part) for part in key) for key in keys)


__all__ = [
    "artifact_row_index_keys",
    "artifact_row_ref_lookup_keys",
    "parse_artifact_link_ref",
    "resolve_artifact_row_target",
]
