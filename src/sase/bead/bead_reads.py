"""Audited log of agent ``sase bead read`` reasoned reads.

Reasoned reads go to the audited artifact-read log (``artifact_reads.jsonl``)
as ``bead:<full-id>`` rows with an authored reason, so the panel and
``sase bead touched`` can surface them as the stronger ``read`` verb with
its ``why``. Legacy machine-local ``sase bead show`` views in
``bead_views.jsonl`` are no longer written — agents are refused at ``show``
— but are still read for display as the weaker ``viewed`` signal.
"""

from __future__ import annotations

from collections.abc import Sequence

from sase.artifact_read_links import record_read_link, should_record_read_link
from sase.artifact_read_log import (
    ArtifactReadError,
    append_artifact_read_event,
    artifact_read_log_path,
    build_artifact_read_event,
)


def bead_read_ref(bead_id: str) -> str:
    """Return the canonical ``bead:<full-id>`` ref for *bead_id*.

    Accepts a bare bead ID or an already-canonical ``bead:`` ref, so
    callers may canonicalize up front and still pass the result back
    through the recording entry points below.
    """
    text = (bead_id or "").strip()
    if text.startswith("bead:"):
        text = text.removeprefix("bead:").strip()
    if not text:
        raise ArtifactReadError("bead id must not be empty")
    try:
        from sase.artifact_ref_operations import parse_artifact_ref

        return parse_artifact_ref(f"bead:{text}").rendered
    except Exception:
        return f"bead:{text}"


def record_bead_reads(
    bead_ids: Sequence[str],
    *,
    reason: str,
) -> tuple[str, ...]:
    """Validate *reason* and append one audited read row per bead id.

    Returns the canonical refs in input order. Raises
    :class:`ArtifactReadError` when the reason is empty or when an audit
    append fails; callers must print no bead output in that case.
    """
    normalized = (reason or "").strip()
    if not normalized:
        raise ArtifactReadError("reason must not be empty")
    recorded_link = should_record_read_link()
    refs: list[str] = []
    for bead_id in bead_ids:
        ref = bead_read_ref(str(bead_id))
        event = build_artifact_read_event(
            ref=ref,
            reason=normalized,
            recorded_link=recorded_link,
        )
        append_artifact_read_event(
            event, log_path=artifact_read_log_path(event.project)
        )
        refs.append(ref)
    return tuple(refs)


def queue_bead_read_links(refs: Sequence[str], *, reason: str) -> None:
    """Queue best-effort read-link rows for audited bead *refs*."""
    normalized = (reason or "").strip()
    for ref in refs:
        record_read_link(str(ref), reason=normalized)


__all__ = [
    "bead_read_ref",
    "queue_bead_read_links",
    "record_bead_reads",
]
