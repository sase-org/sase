"""Decide whether a continuation replay is eligible for automatic launch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ._util import (
    AUTOMATIC_REFUSAL_OMISSIONS,
    BlockContent,
    ContinuationReplayRefusal,
)


def assess_automatic_continuation_launch(
    manifest: Mapping[str, object],
    content_by_node_id: Mapping[str, BlockContent],
) -> tuple[ContinuationReplayRefusal, ...]:
    """Return durable refusal reasons that block automatic successor launch."""

    refusals: list[ContinuationReplayRefusal] = []
    omissions = _mapping_list(manifest.get("omissions"))
    for omission in omissions:
        kind = str(omission.get("kind") or "unknown")
        if kind not in AUTOMATIC_REFUSAL_OMISSIONS:
            continue
        refusals.append(
            ContinuationReplayRefusal(kind, _format_omission(omission)),
        )

    for node_id, content in content_by_node_id.items():
        if content.kind != "agent_delta":
            continue
        status = str(content.payload.get("status") or "")
        if status not in {"failed", "interrupted"}:
            continue
        checkpoint = (
            content.payload.get("handoff_checkpoint_ref")
            or content.payload.get("checkpoint_ref")
            or content.payload.get("checkpoint_body")
        )
        if checkpoint:
            continue
        if not _is_essential_parent(manifest, node_id):
            continue
        refusals.append(
            ContinuationReplayRefusal(
                "failed_starter_without_checkpoint",
                "failed starter "
                f"`{node_id}` has no durable checkpoint and is nonlaunchable",
            )
        )
    return tuple(_unique_refusals(refusals))


def merge_omissions(
    manifest: Mapping[str, object],
    extra: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Return a copy of *manifest* with *extra* omissions appended uniquely."""

    merged = dict(manifest)
    omissions = _mapping_list(manifest.get("omissions"))
    seen = {_omission_key(omission) for omission in omissions}
    for omission in extra:
        key = _omission_key(omission)
        if key in seen:
            continue
        seen.add(key)
        omissions.append(dict(omission))
    merged["omissions"] = omissions
    return merged


def _is_essential_parent(manifest: Mapping[str, object], node_id: str) -> bool:
    for edge in _mapping_list(manifest.get("parent_edges")):
        if str(edge.get("parent_id") or "") == node_id:
            return True
    for block in _mapping_list(manifest.get("stable_blocks")):
        parents = block.get("parent_ids")
        if isinstance(parents, list) and node_id in parents:
            return True
    return False


def _mapping_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _format_omission(omission: Mapping[str, object]) -> str:
    kind = str(omission.get("kind") or "unknown")
    reason = str(omission.get("reason") or "unknown")
    details = []
    node_id = omission.get("node_id")
    parent_id = omission.get("parent_id")
    if isinstance(node_id, str) and node_id:
        details.append(f"node `{node_id}`")
    if isinstance(parent_id, str) and parent_id:
        details.append(f"parent `{parent_id}`")
    suffix = " · " + ", ".join(details) if details else ""
    return f"{kind}: {reason}{suffix}"


def _omission_key(omission: Mapping[str, object]) -> tuple[object, object, object]:
    return (omission.get("kind"), omission.get("node_id"), omission.get("parent_id"))


def _unique_refusals(
    refusals: Sequence[ContinuationReplayRefusal],
) -> list[ContinuationReplayRefusal]:
    seen: set[tuple[str, str]] = set()
    unique: list[ContinuationReplayRefusal] = []
    for refusal in refusals:
        key = (refusal.kind, str(refusal))
        if key in seen:
            continue
        seen.add(key)
        unique.append(refusal)
    return unique
