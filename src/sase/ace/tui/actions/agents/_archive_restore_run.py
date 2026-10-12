"""Archive-restore submission, toasts, and reveal.

Run seam for the Archive restore split. Submission helpers that only this
module needs stay private here. The public import path stays
:mod:`sase.ace.tui.actions.agents._archive_restore`, which re-exports this
module's public names.
"""

from __future__ import annotations

from typing import Any

from ._archive_restore_keys import (
    collect_archive_restore_keys,
    hydrate_archive_candidate,
)
from ._archive_restore_support import archive_light_name, notify_owner
from ._archive_restore_types import ArchiveRestoreSkip, ArchiveRestoreSummary

__all__ = [
    "run_archive_restore",
]


def _failed_identities(delta: Any) -> set[Any]:
    failed = set()
    try:
        for failure in getattr(delta, "failed", None) or ():
            identity = getattr(failure, "identity", None)
            if identity is not None:
                failed.add(identity)
    except Exception:
        pass
    return failed


def _submit_revive(owner: Any, agents: list[Any]) -> Any | None:
    batch = getattr(owner, "_do_revive_agents", None)
    if callable(batch):
        try:
            return batch(list(agents))
        except Exception:
            return None
    single = getattr(owner, "_do_revive_agent", None)
    if not callable(single):
        return None
    revived: list[Any] = []
    failed: list[Any] = []
    for agent in agents:
        try:
            delta = single(agent)
        except Exception:
            continue
        if delta is None:
            continue
        revived.extend(getattr(delta, "revived", None) or ())
        failed.extend(getattr(delta, "failed", None) or ())
    from ._revive_delta import AgentReviveDelta

    return AgentReviveDelta(revived=tuple(revived), failed=tuple(failed))


def _refresh_archive_chrome(owner: Any) -> None:
    try:
        from ._archive_column import refresh_archive_footer

        refresh_archive_footer(owner)
    except Exception:
        pass


def run_archive_restore(
    owner: Any, *, keys: list[str] | None = None, and_show: bool = False
) -> ArchiveRestoreSummary:
    """Restore Archive runs to the Inbox and keep their rows in place.

    Returns a summary for toasts and tests. The cursor never moves: every
    restored row stays in the list behind the ``⌂ restored`` overlay until
    the query changes or the Archive is left, and the pulse counts the agent
    through the revive path's own inbox refresh.
    """
    from ._archive_view import mark_archive_row_restored

    targets, skipped = (
        (list(keys), []) if keys is not None else collect_archive_restore_keys(owner)
    )
    skips = list(skipped)
    submittable: list[tuple[str, str, Any]] = []
    for key in targets:
        agent, light_row, reason = hydrate_archive_candidate(owner, key)
        name = archive_light_name(light_row)
        if agent is None or reason is not None:
            skips.append(
                ArchiveRestoreSkip(key=key, name=name, reason=reason or "skipped")
            )
        else:
            submittable.append((key, name, agent))
    if not submittable:
        summary = ArchiveRestoreSummary(restored=(), skipped=tuple(skips), failed=())
        _toast_restore(owner, summary)
        return summary

    delta = _submit_revive(owner, [agent for _key, _name, agent in submittable])
    if delta is None:
        unavailable = tuple(
            (key, name, "revive is unavailable") for key, name, _agent in submittable
        )
        summary = ArchiveRestoreSummary(
            restored=(), skipped=tuple(skips), failed=unavailable, and_show=and_show
        )
        _toast_restore(owner, summary)
        return summary

    failed_ids = _failed_identities(delta)
    restored: list[tuple[str, str]] = []
    failures: list[tuple[str, str, str]] = []
    for key, name, agent in submittable:
        try:
            identity = getattr(agent, "identity", None)
        except Exception:
            identity = None
        if identity is not None and identity in failed_ids:
            message = "revive failed"
            try:
                for failure in getattr(delta, "failed", None) or ():
                    if getattr(failure, "identity", None) == identity:
                        message = str(getattr(failure, "message", None) or message)
                        break
            except Exception:
                pass
            failures.append((key, name, message))
        else:
            restored.append((key, name))
            try:
                mark_archive_row_restored(owner, key)
            except Exception:
                pass
    summary = ArchiveRestoreSummary(
        restored=tuple(restored),
        skipped=tuple(skips),
        failed=tuple(failures),
        and_show=and_show,
    )
    _refresh_archive_chrome(owner)
    if and_show and len(restored) == 1 and not failures:
        _show_restored_in_inbox(owner, submittable[0][2], restored[0][1])
    else:
        _toast_restore(owner, summary)
    return summary


def _toast_restore(owner: Any, summary: ArchiveRestoreSummary) -> None:
    total = len(summary.restored)
    if total == 1 and not summary.skipped and not summary.failed:
        notify_owner(
            owner,
            f"{summary.restored[0][1]} is back in the inbox · no new run started",
        )
        return
    if total == 0 and len(summary.skipped) == 1 and not summary.failed:
        skip = summary.skipped[0]
        notify_owner(
            owner, f"Nothing restored — {skip.name}: {skip.reason}", severity="warning"
        )
        return
    parts = [f"Restored {total}"]
    if summary.skipped:
        reasons: dict[str, int] = {}
        for skip in summary.skipped:
            reasons[skip.reason] = reasons.get(skip.reason, 0) + 1
        detail = ", ".join(
            f"{reason} ×{count}" for reason, count in sorted(reasons.items())
        )
        parts.append(f"skipped {len(summary.skipped)} ({detail})")
    else:
        parts.append("skipped 0")
    if summary.failed:
        parts.append(f"failed {len(summary.failed)}")
    else:
        parts.append("failed 0")
    notify_owner(
        owner,
        " · ".join(parts),
        severity="warning" if total == 0 else "information",
    )


def _show_restored_in_inbox(owner: Any, agent: Any, name: str) -> None:
    """Leave the Archive and reveal one restored agent in the Inbox."""
    try:
        from ._archive_view import close_agents_archive_view

        close_agents_archive_view(owner)
    except Exception:
        pass
    revealed = False
    select = getattr(owner, "_select_revived_agent", None)
    if callable(select):
        try:
            revealed = bool(select(agent))
        except Exception:
            revealed = False
    refresh = getattr(owner, "_refresh_agents_display", None)
    if callable(refresh):
        try:
            refresh(list_changed=False)
        except Exception:
            pass
    if revealed:
        notify_owner(owner, f"{name} is back in the inbox · showing in Inbox")
        return
    # Unrevealed covers two cases: the parked Inbox filter hides the row,
    # or the revive reload has not landed yet (its own scheduled refresh
    # reveals the row when it does). Only claim the filter when the agent
    # is already loaded but still unreached.
    try:
        loaded = tuple(
            getattr(owner, "_agents_with_children", None)
            or getattr(owner, "_agents", None)
            or ()
        )
        identity = getattr(agent, "identity", None)
        visible = any(
            getattr(candidate, "identity", None) == identity for candidate in loaded
        )
    except Exception:
        visible = False
    if visible:
        notify_owner(
            owner,
            f"{name} is back in the inbox · the inbox filter hides it",
            severity="warning",
        )
    else:
        notify_owner(owner, f"{name} is back in the inbox · no new run started")
