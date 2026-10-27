"""Detect agent-copied bead IDs that miss the assigned bead by one segment.

A phase worker that drops or inserts one interior ``.N`` can land on a
different, real bead. This module is the shared comparison and the CLI
warning / refusal surface for that shape.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path


def _near_miss_of_assigned(requested: str, assigned: str) -> bool:
    """Return whether *requested* differs from *assigned* by one interior segment.

    Both arguments are full bead IDs. The result is true when they share a
    root (the text before the first ``.``), are unequal, neither is an
    ancestor or descendant of the other, and inserting or deleting exactly
    one dot-segment turns one into the other. A trailing-only insert or
    delete is an ancestor/descendant pair and never counts.
    """
    if not requested or not assigned or requested == assigned:
        return False
    requested_root, requested_segments = _root_and_segments(requested)
    assigned_root, assigned_segments = _root_and_segments(assigned)
    if requested_root != assigned_root:
        return False
    if _is_segment_prefix(requested_segments, assigned_segments) or _is_segment_prefix(
        assigned_segments, requested_segments
    ):
        return False
    return _one_segment_removed(
        assigned_segments, requested_segments
    ) or _one_segment_removed(requested_segments, assigned_segments)


def _assigned_bead_id() -> str | None:
    """Return the agent's assigned bead, or ``None`` outside an assigned run.

    Resolution matches the bead-work env then durable agent-meta fallback:
    ``SASE_PHASE_BEAD_ID``, then ``SASE_BEAD_ID``, then ``phase_bead_id`` /
    ``bead_id`` on ``agent_meta.json``.
    """
    from sase.bead.work_types import SASE_BEAD_ID_ENV, SASE_PHASE_BEAD_ID_ENV

    phase = os.environ.get(SASE_PHASE_BEAD_ID_ENV, "").strip()
    if phase:
        return phase
    bead = os.environ.get(SASE_BEAD_ID_ENV, "").strip()
    if bead:
        return bead
    meta = _read_agent_meta_associations()
    return meta.get("phase_bead_id") or meta.get("bead_id") or None


def _near_miss_banner(requested: str, assigned: str) -> str:
    """Return the warning banner naming both IDs."""
    return (
        f"⚠ `{requested}` is not your assigned bead `{assigned}`; "
        "the two IDs differ by one segment. If you meant your own bead, "
        f"rerun with the exact ID `{assigned}`."
    )


def near_miss_refusal_message(requested: str, assigned: str) -> str:
    """Return the close/open error text naming both IDs."""
    return (
        f"`{requested}` is not your assigned bead `{assigned}`; "
        "the target differs from the assigned bead by one segment."
    )


def first_assigned_near_miss(ids: Sequence[str]) -> tuple[str, str] | None:
    """Return ``(requested, assigned)`` for the first near-miss in *ids*."""
    assigned = _assigned_bead_id()
    if assigned is None:
        return None
    seen: set[str] = set()
    for raw in ids:
        if not raw or raw in seen:
            continue
        seen.add(raw)
        if _near_miss_of_assigned(raw, assigned):
            return raw, assigned
    return None


def warn_if_assigned_near_miss(ids: Sequence[str]) -> None:
    """Print the near-miss banner on stderr when *ids* include a near-miss."""
    hit = first_assigned_near_miss(ids)
    if hit is None:
        return
    print(_near_miss_banner(*hit), file=sys.stderr)


def refuse_if_assigned_near_miss(ids: Sequence[str]) -> None:
    """Exit non-zero when *ids* include a near-miss of the assigned bead."""
    hit = first_assigned_near_miss(ids)
    if hit is None:
        return
    print(f"Error: {near_miss_refusal_message(*hit)}", file=sys.stderr)
    sys.exit(1)


def annotate_not_found_message(message: str, *, requested: str | None = None) -> str:
    """Append a did-you-mean hint when a missing ID is a near-miss."""
    assigned = _assigned_bead_id()
    if assigned is None:
        return message
    target = requested if requested is not None else _not_found_target(message)
    if target is None or not _near_miss_of_assigned(target, assigned):
        return message
    return f"{message.rstrip()} (did you mean `{assigned}`?)"


def ids_from_operation_context(context: object, extra: Sequence[str] = ()) -> list[str]:
    """Collect requested and resolved IDs from a bead operation context."""
    ids = [item for item in extra if item]
    for target in getattr(context, "targets", ()):
        requested = getattr(target, "requested_id", "")
        resolved = getattr(target, "resolved_id", "")
        if requested:
            ids.append(str(requested))
        if resolved:
            ids.append(str(resolved))
    for resolved_id in getattr(context, "resolved_ids", ()):
        if resolved_id:
            ids.append(str(resolved_id))
    return ids


def apply_read_near_miss[PagerT](
    body: str,
    batch: object,
    *,
    format_name: str,
    pager_document: PagerT,
) -> tuple[str, PagerT | None]:
    """Banner a near-miss ``sase bead read`` without changing JSON stdout."""
    ids: list[str] = []
    for entry in getattr(batch, "entries", ()):
        issue = getattr(entry, "issue", None)
        issue_id = getattr(issue, "id", None)
        if issue_id:
            ids.append(str(issue_id))
        requested = getattr(entry, "requested_id", None)
        if requested:
            ids.append(str(requested))
    hit = first_assigned_near_miss(ids)
    if hit is None:
        return body, pager_document
    banner = _near_miss_banner(*hit)
    if format_name == "json":
        print(banner, file=sys.stderr)
        return body, pager_document
    return _wrap_with_banners(body, banner), None


def _wrap_with_banners(body: str, banner: str) -> str:
    stripped = body.rstrip("\n")
    if stripped:
        return f"{banner}\n\n{stripped}\n\n{banner}\n"
    return f"{banner}\n"


def _root_and_segments(bead_id: str) -> tuple[str, tuple[str, ...]]:
    if "." not in bead_id:
        return bead_id, ()
    root, rest = bead_id.split(".", 1)
    return root, tuple(rest.split("."))


def _is_segment_prefix(shorter: tuple[str, ...], longer: tuple[str, ...]) -> bool:
    return len(shorter) < len(longer) and longer[: len(shorter)] == shorter


def _one_segment_removed(longer: tuple[str, ...], shorter: tuple[str, ...]) -> bool:
    if len(longer) != len(shorter) + 1:
        return False
    for index in range(len(longer)):
        if longer[:index] + longer[index + 1 :] == shorter:
            return True
    return False


def _not_found_target(message: str) -> str | None:
    marker = "issue not found: "
    index = message.lower().find(marker)
    if index < 0:
        return None
    target = message[index + len(marker) :].strip()
    return target or None


def _read_agent_meta_associations() -> dict[str, str]:
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR", "").strip()
    if not artifacts_dir:
        return {}
    try:
        raw_meta = json.loads(
            (Path(artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw_meta, dict):
        return {}
    associations: dict[str, str] = {}
    for key in ("phase_bead_id", "bead_id"):
        value = raw_meta.get(key)
        if isinstance(value, str) and (stripped := value.strip()):
            associations[key] = stripped
    return associations
