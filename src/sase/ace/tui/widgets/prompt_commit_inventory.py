"""Warm shared-core snapshots for prompt ``@commit:`` completion."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from sase.artifact_refs import ArtifactRefContext
from sase_core_rs import (  # type: ignore[import-untyped]
    artifact_ref_payload_inventory,
)


PROMPT_COMMIT_INVENTORY_TTL = 2.0
"""Seconds before a prompt commit snapshot is eligible for revalidation."""


@dataclass(frozen=True, slots=True)
class ArtifactRefCommitRow:
    """One immutable commit row supplied by the shared core inventory."""

    payload: str
    label: str = ""
    detail: str = ""
    age: str = ""
    scope: str = ""
    rank: int | None = None
    body: str = ""


@dataclass(frozen=True, slots=True)
class PromptCommitSnapshot:
    """One target project's commit rows and their freshness metadata."""

    project: str | None
    rows: tuple[ArtifactRefCommitRow, ...]
    loaded_at: float
    truncated_payloads: int = 0


def prompt_commit_snapshot_expired(
    snapshot: PromptCommitSnapshot,
    *,
    now: float | None = None,
) -> bool:
    """Return whether *snapshot* is old enough for background revalidation."""
    current = monotonic() if now is None else now
    return current - snapshot.loaded_at >= PROMPT_COMMIT_INVENTORY_TTL


def load_prompt_commit_snapshot(
    project: str | None,
    context: ArtifactRefContext,
    *,
    loaded_at: float | None = None,
) -> PromptCommitSnapshot:
    """Load commit rows through the shared core; worker-thread use only."""
    inventory = artifact_ref_payload_inventory("commit", context.to_wire())
    raw_rows = inventory.get("payloads", [])
    rows = tuple(
        row
        for raw in raw_rows
        if isinstance(raw, dict) and (row := _commit_row(raw)) is not None
    )
    truncated = inventory.get("truncated_payloads", 0)
    return PromptCommitSnapshot(
        project=project,
        rows=rows,
        loaded_at=monotonic() if loaded_at is None else loaded_at,
        truncated_payloads=(
            truncated if isinstance(truncated, int) and truncated >= 0 else 0
        ),
    )


def revalidate_prompt_commit_snapshot(
    previous: PromptCommitSnapshot,
    project: str | None,
    context: ArtifactRefContext,
    *,
    now: float | None = None,
) -> PromptCommitSnapshot:
    """Return *previous* inside the TTL, otherwise load a fresh snapshot."""
    current = monotonic() if now is None else now
    if previous.project == project and not prompt_commit_snapshot_expired(
        previous,
        now=current,
    ):
        return previous
    return load_prompt_commit_snapshot(project, context, loaded_at=current)


def _commit_row(raw: dict[object, object]) -> ArtifactRefCommitRow | None:
    """Map one defensive wire row without re-deriving core-owned fields."""
    payload = raw.get("payload")
    if not isinstance(payload, str) or not payload:
        return None
    rank = raw.get("rank")
    return ArtifactRefCommitRow(
        payload=payload,
        label=_wire_string(raw.get("label")),
        detail=_wire_string(raw.get("detail")),
        age=_wire_string(raw.get("age")),
        scope=_wire_string(raw.get("scope")),
        rank=rank if isinstance(rank, int) and rank >= 0 else None,
        body=_wire_string(raw.get("body")),
    )


def _wire_string(value: object) -> str:
    return value if isinstance(value, str) else ""
