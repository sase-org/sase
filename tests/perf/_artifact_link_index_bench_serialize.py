"""Stable JSON payloads, chip serialization, and parity diff helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.ace.tui.relations.link_index import LinkChip, LinkIndex
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import RelationDiagnostic, RelationEdge, RelationIndex

__all__ = [
    "chip_payload",
    "diagnostic_payload",
    "edge_payload",
    "index_enumeration_refs",
    "jsonable",
    "parity_diff",
    "serialize_link_index",
    "serialize_relation_index",
    "target_payload",
]


def jsonable(value: Any) -> Any:
    """Convert nested tuples to lists so a payload is JSON-serializable."""

    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


def target_payload(target: ArtifactEntryTarget | None) -> dict[str, Any] | None:
    """Normalize a target to a JSON object, or ``None``."""

    if target is None:
        return None
    return {"pane_id": target.pane_id, "parts": list(target.parts)}


def chip_payload(chip: LinkChip) -> dict[str, Any]:
    """Pin every :class:`LinkChip` field."""

    return {
        "accent": chip.accent,
        "created_at": chip.created_at,
        "created_by": chip.created_by,
        "directed": chip.directed,
        "icon": chip.icon,
        "label": chip.label,
        "neighbor_ref": chip.neighbor_ref,
        "neighbor_target": target_payload(chip.neighbor_target),
        "origin": chip.origin,
        "relation": chip.relation,
        "this_is_source": chip.this_is_source,
        "uses": chip.uses,
        "why": chip.why,
        "writable": chip.writable,
    }


def edge_payload(edge: RelationEdge) -> dict[str, Any]:
    """Pin every :class:`RelationEdge` field."""

    return {
        "dangling": edge.dangling,
        "derived": edge.derived,
        "description": edge.description,
        "kind": edge.kind.value,
        "label": edge.label,
        "origin": edge.origin,
        "relation": edge.relation,
        "source": target_payload(edge.source),
        "target": target_payload(edge.target),
        "uses": edge.uses,
    }


def diagnostic_payload(item: RelationDiagnostic) -> dict[str, Any]:
    return {
        "code": item.code,
        "message": item.message,
        "relation": item.relation,
        "target": target_payload(item.target),
    }


def index_enumeration_refs(
    rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Every ``by_ref``/``targets_by_ref`` key the eager index would carry.

    Test-enumeration helper only: production lookups never enumerate the
    graph. Mirrors the native pass-2 alias pattern (canonical entries first,
    aliases never shadowing a canonical spelling).
    """

    from sase.core.agent_identity_facade import AgentIdentitySnapshot
    from sase.sdd._artifact_link_store_support import (
        canonicalize_artifact_link_ref,
    )

    identity = AgentIdentitySnapshot.current()
    canonical: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in ("source_ref", "target_ref"):
            raw = str(row.get(key) or "").strip()
            if not raw:
                continue
            try:
                ref = str(canonicalize_artifact_link_ref(raw))
            except Exception:  # noqa: BLE001 - malformed refs keep spelling
                ref = raw
            if ref not in seen:
                seen.add(ref)
                canonical.append(ref)
    refs = list(canonical)
    keyed = set(canonical)
    for ref in canonical:
        for alias in _bench_aliases_for_ref(ref, identity):
            if alias not in keyed:
                keyed.add(alias)
                refs.append(alias)
    return sorted(refs)


def _bench_aliases_for_ref(ref: str, identity: Any) -> tuple[str, ...]:
    from sase.ace.tui.relations.artifact_links import parse_link_ref
    from sase.core.agent_identity_facade import (
        current_owner_agent_name_lookup_candidates,
    )

    parsed = parse_link_ref(ref)
    if parsed is None:
        return ()
    kind, payload = parsed
    if kind == "agent":
        return tuple(
            f"agent:{candidate}"
            for candidate in current_owner_agent_name_lookup_candidates(
                payload, identity
            )
        )
    if kind == "stitch":
        repo, at, sha = payload.partition("@")
        if at and repo and len(sha) > 7:
            return (f"stitch:{repo}@{sha[:7]}",)
        return ()
    if kind == "plan":
        return (f"ref:plan:{payload}",)
    if kind == "chop":
        return (f"job:{payload}",)
    return ()


def serialize_link_index(
    index: LinkIndex, rows: Sequence[Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    """Stable JSON form of chips and targets, keyed in sorted ref order.

    *rows* enumerates the refs to serialize; production indexes are lazy
    per-ref views, so callers pass the snapshot rows they built from.
    """

    if rows is None:
        try:
            refs = sorted(index.by_ref.keys())  # type: ignore[union-attr]
        except TypeError:
            refs = []
    else:
        refs = index_enumeration_refs(rows)
    return {
        "by_ref": {
            ref: [chip_payload(chip) for chip in index.chips_for(ref)] for ref in refs
        },
        "source_key": jsonable(index.source_key),
        "targets_by_ref": {ref: target_payload(index.target_for(ref)) for ref in refs},
    }


def serialize_relation_index(index: RelationIndex) -> dict[str, Any]:
    """Stable JSON form of Patch ``RelationIndex`` edges and targets."""

    known: list[dict[str, Any]] = []
    for target in index.known_targets:
        payload = target_payload(target)
        if payload is not None:
            known.append(payload)
    known.sort(key=lambda item: (str(item["pane_id"]), list(item["parts"])))
    return {
        "diagnostics": [diagnostic_payload(item) for item in index.diagnostics],
        "edges": [edge_payload(edge) for edge in index.edges],
        "known_targets": known,
        "pane_id": index.pane_id,
    }


def parity_diff(actual: Any, expected: Any, *, path: str = "$") -> list[str]:
    """Return human-readable mismatch lines; empty means equal."""

    if type(actual) is not type(expected) and not (
        isinstance(actual, (int, float)) and isinstance(expected, (int, float))
    ):
        return [f"{path}: type {type(actual).__name__} != {type(expected).__name__}"]
    if isinstance(actual, dict):
        diffs: list[str] = []
        actual_keys = set(actual)
        expected_keys = set(expected)
        for key in sorted(actual_keys - expected_keys):
            diffs.append(f"{path}.{key}: unexpected key")
        for key in sorted(expected_keys - actual_keys):
            diffs.append(f"{path}.{key}: missing key")
        for key in sorted(actual_keys & expected_keys):
            diffs.extend(parity_diff(actual[key], expected[key], path=f"{path}.{key}"))
        return diffs
    if isinstance(actual, list):
        diffs = []
        if len(actual) != len(expected):
            diffs.append(f"{path}: len {len(actual)} != {len(expected)}")
        for index, (left, right) in enumerate(zip(actual, expected, strict=False)):
            diffs.extend(parity_diff(left, right, path=f"{path}[{index}]"))
        return diffs
    if actual != expected:
        return [f"{path}: {actual!r} != {expected!r}"]
    return []
