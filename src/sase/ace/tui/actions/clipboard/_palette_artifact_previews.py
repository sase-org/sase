"""Warm artifact preview derivation for the ACE Copy as palette."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.commit_footer_facade import parse_commit_footer

from ...copy_targets import copy_targets_for
from ...models.artifact_file_clipboard import (
    artifact_file_has_stored_content,
    artifact_file_preferred_path_text,
)
from ._palette_helpers import (
    marked_count_hint,
    marked_hint,
    shorten,
    size_hint,
)


def artifact_target_state(
    *,
    group: str,
    subtab: str,
    pane: Any,
    objects: tuple[Any, ...],
    marked: bool,
    count: int,
) -> tuple[set[str], dict[str, str]]:
    available = {target.target for target in copy_targets_for(group)}
    previews = {
        "reference": marked_hint(count, "artifact references")
        if marked
        else "artifact reference",
        "link": marked_hint(count, "Markdown links") if marked else "Markdown link",
        "json": marked_hint(count, "metadata records") if marked else "metadata record",
        "handoff": marked_hint(count, "prompt references")
        if marked
        else "new agent prompt",
        "snapshot": "current Artifacts pane",
    }
    first = objects[0] if objects else None
    suffix = f" · +{count - 1}" if marked and count > 1 else ""

    if subtab == "stitches":
        commit = getattr(first, "commit", None)
        message = _commit_message(first)
        plan = _commit_plan_reference(message)
        values = {
            "sha": getattr(commit, "full_id", ""),
            "message": getattr(commit, "subject", "") or message,
            "repo_sha": (
                f"{getattr(first, 'repo', '')}@{getattr(commit, 'short_id', '')}"
                if first is not None
                else ""
            ),
            "plan": plan or "",
        }
        if not plan and not marked:
            available.discard("plan")
    elif subtab == "plans":
        values = _plan_values(first)
        for target in ("design", "path", "title", "body"):
            if not values.get(target) and not marked:
                available.discard(target)
    elif subtab == "beads":
        values = _bead_values(first)
        for target in ("id", "title", "body", "design"):
            if not values.get(target) and not marked:
                available.discard(target)
    elif subtab == "chats":
        agent = getattr(first, "agent_local_name", None) or getattr(
            first, "agent", None
        )
        excerpt = (
            getattr(first, "prompt_snippet", None)
            or getattr(first, "response_snippet", None)
            or ""
        )
        values = {
            "path": getattr(first, "absolute_path", ""),
            "agent": agent or "",
            "transcript": excerpt or size_hint(getattr(first, "size_bytes", None)),
        }
        if not agent and not marked:
            available.discard("agent")
    else:
        values = {} if marked else _file_target_values(pane, first)
        counts = _file_target_counts(pane, objects)
        labels = {
            "contents": "copyable contents",
            "reference": "artifact references",
            "link": "Markdown links",
            "path": "stored paths",
            "source": "source paths",
            "label": "artifact-file labels",
            "json": "metadata records",
            "handoff": "prompt references",
        }
        for target, representable_count in counts.items():
            if not representable_count:
                available.discard(target)
            elif marked:
                previews[target] = marked_count_hint(
                    representable_count,
                    count,
                    labels[target],
                )

    for target, value in values.items():
        if value:
            previews[target] = shorten(str(value)) + suffix
        elif marked:
            previews[target] = marked_hint(count, target.replace("_", " "))
    return available, previews


def _plan_values(row: Any | None) -> dict[str, str]:
    if row is None:
        return {"design": "", "path": "", "title": "", "body": ""}
    if getattr(row, "proposal", None) is not None:
        return {
            "design": "",
            "path": row.proposal.plan_path,
            "title": row.proposal.title,
            "body": row.proposal.body,
        }
    if getattr(row, "archive", None) is not None:
        plan = row.archive.plan
        return {
            "design": "",
            "path": plan.path,
            "title": plan.title or plan.name,
            "body": plan.body,
        }
    issue = getattr(row, "issue", None)
    path = getattr(issue, "design", "") if issue is not None else ""
    body = (
        getattr(issue, "description", "") or getattr(issue, "notes", "")
        if issue is not None
        else ""
    )
    return {
        "design": getattr(issue, "design", "") if issue is not None else "",
        "path": path or "",
        "title": getattr(issue, "title", "") if issue is not None else "",
        "body": body or "",
    }


def _bead_values(row: Any | None) -> dict[str, str]:
    issue = getattr(row, "issue", None)
    if issue is None:
        return {"id": "", "title": "", "body": "", "design": ""}
    description = str(getattr(issue, "description", "") or "")
    notes = str(getattr(issue, "notes", "") or "")
    body = "\n\n".join(part for part in (description, notes) if part)
    return {
        "id": str(getattr(issue, "id", "") or ""),
        "title": str(getattr(issue, "title", "") or ""),
        "body": body,
        "design": str(getattr(issue, "design", "") or ""),
    }


def _file_target_values(pane: Any, entry: Any | None) -> dict[str, str]:
    if entry is None:
        return {
            "contents": "",
            "reference": "",
            "link": "",
            "path": "",
            "source": "",
            "label": "",
            "json": "",
            "handoff": "",
        }

    artifact_id = str(getattr(entry, "id", "") or "")
    label = str(getattr(entry, "label", "") or "")
    kind = str(getattr(entry, "kind", "") or "")
    size = size_hint(getattr(entry, "size_bytes", None))
    view_mode = _warm_file_view_mode(pane, entry, selected=True)
    reference = f"file:{artifact_id}" if artifact_id else ""
    metadata_hint = " · ".join(part for part in (kind, size, "metadata") if part)
    return {
        "contents": " · ".join(part for part in (view_mode, size) if part),
        "reference": f"@{reference}" if reference else "",
        "link": f"[{label}]({reference})" if label and reference else "",
        "path": artifact_file_preferred_path_text(entry)[0],
        "source": str(getattr(entry, "source_path", "") or ""),
        "label": label,
        "json": metadata_hint,
        "handoff": f"@{reference} · new agent prompt" if reference else "",
    }


def _file_target_counts(pane: Any, entries: tuple[Any, ...]) -> dict[str, int]:
    reference_count = sum(bool(getattr(entry, "id", None)) for entry in entries)
    return {
        "contents": sum(
            _warm_file_view_mode(pane, entry, selected=len(entries) == 1)
            in {"markdown", "text"}
            for entry in entries
        ),
        "reference": reference_count,
        "link": sum(
            bool(getattr(entry, "id", None) and getattr(entry, "label", None))
            for entry in entries
        ),
        "path": sum(artifact_file_has_stored_content(entry) for entry in entries),
        "source": sum(bool(getattr(entry, "source_path", None)) for entry in entries),
        "label": sum(bool(getattr(entry, "label", None)) for entry in entries),
        "json": len(entries),
        "handoff": reference_count,
    }


def _warm_file_view_mode(
    pane: Any,
    entry: Any,
    *,
    selected: bool,
) -> str:
    """Return an already-classified file view mode without filesystem work."""

    if selected:
        selected_mode = getattr(pane, "selected_view_mode", None)
        if isinstance(selected_mode, str):
            return selected_mode

    snapshot = getattr(pane, "snapshot", None) or getattr(pane, "_snapshot", None)
    view_mode_for = getattr(snapshot, "view_mode_for", None)
    if callable(view_mode_for):
        try:
            mode = view_mode_for(entry)
        except Exception:
            mode = None
        if isinstance(mode, str):
            return mode

    view_modes = getattr(snapshot, "view_modes", None)
    if isinstance(view_modes, Mapping):
        mode = view_modes.get(getattr(entry, "id", None))
        if isinstance(mode, str):
            return mode
    return ""


def _commit_message(entry: Any | None) -> str:
    commit = getattr(entry, "commit", None)
    if commit is None:
        return ""
    subject = str(getattr(commit, "subject", "") or "")
    body = str(getattr(commit, "body", "") or "")
    return f"{subject}\n\n{body}" if body else subject


def _commit_plan_reference(message: str) -> str | None:
    try:
        footer = parse_commit_footer(message)
    except Exception:
        return None
    tag = next(
        (tag for tag in reversed(footer.tags) if tag.raw_key == "SASE_PLAN"),
        None,
    )
    return None if tag is None else tag.label
