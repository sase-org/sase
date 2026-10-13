"""Archive-restore submission, toasts, and reveal.

Run seam for the Archive restore split. Submission helpers that only this
module needs stay private here. The public import path stays
:mod:`sase.ace.tui.actions.agents._archive_restore`, which re-exports this
module's public names.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from functools import partial
from typing import Any

from ...models.agent_archive_view import AGENTS_VIEW_ARCHIVE
from ._archive_restore_keys import (
    capture_archive_restore_plan,
    collect_archive_restore_targets,
    hydrate_archive_candidate,
    resolve_archive_restore_targets,
)
from ._archive_restore_support import archive_light_name, notify_owner
from ._archive_restore_types import (
    ArchiveRestoreSkip,
    ArchiveRestoreSummary,
    ArchiveRestoreTargets,
)

__all__ = [
    "run_archive_restore",
    "run_archive_restore_async",
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


def _supported_revive_kwargs(func: Any, *, hook: Any | None) -> dict[str, Any]:
    """Return the quiet-mode kwargs one revive entry point accepts.

    Older entry points (and test stubs) predate ``quiet``: they get no
    extra kwargs so a single call never runs twice. The caller treats a
    missing ``on_revive_loaded`` as "hook not consumed" and reveals
    restore-and-show synchronously instead.
    """
    wanted: dict[str, Any] = {"quiet": True}
    if hook is not None:
        wanted["on_revive_loaded"] = hook
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return dict(wanted)
    if any(param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values()):
        return dict(wanted)
    return {key: value for key, value in wanted.items() if key in params}


def _submit_revive(
    owner: Any, agents: list[Any], *, on_revive_loaded: Any | None = None
) -> tuple[Any | None, bool]:
    """Submit agents through the real revive path in quiet mode.

    Returns ``(delta, hook_consumed)``. ``delta`` is None when no revive
    entry point exists or the submit raised; ``hook_consumed`` tells the
    caller whether restore-and-show's reveal runs on the revive refresh
    (True) or must run synchronously (older entry point without the hook).
    """
    batch = getattr(owner, "_do_revive_agents", None)
    if callable(batch):
        try:
            kwargs = _supported_revive_kwargs(batch, hook=on_revive_loaded)
            return batch(list(agents), **kwargs), "on_revive_loaded" in kwargs
        except Exception:
            return None, False
    single = getattr(owner, "_do_revive_agent", None)
    if not callable(single):
        return None, False
    try:
        single_kwargs = _supported_revive_kwargs(single, hook=None)
    except Exception:
        single_kwargs = {}
    revived: list[Any] = []
    failed: list[Any] = []
    for agent in agents:
        try:
            delta = single(agent, **single_kwargs)
        except Exception:
            continue
        if delta is None or delta is False:
            continue
        revived.extend(getattr(delta, "revived", None) or ())
        failed.extend(getattr(delta, "failed", None) or ())
    from ._revive_delta import AgentReviveDelta

    return AgentReviveDelta(revived=tuple(revived), failed=tuple(failed)), False


def _refresh_archive_chrome(owner: Any) -> None:
    try:
        from ._archive_column import refresh_archive_footer

        refresh_archive_footer(owner)
    except Exception:
        pass


def _bump_archive_pulse(owner: Any) -> None:
    """Repaint the Inbox pulse now, best-effort.

    The quiet revive completion repaints authoritatively once the delta
    refresh lands; this synchronous bump covers entry points that never
    reach the real path (and fakes without a scheduler).
    """
    try:
        from ._archive_controller import refresh_archive_inbox_pulse

        refresh_archive_inbox_pulse(owner)
    except Exception:
        pass


def _hydrated_entry(
    key: str,
    hydrated: tuple[Any | None, Any | None, str | None],
    submittable: list[tuple[str, str, Any]],
    skips: list[ArchiveRestoreSkip],
) -> None:
    """File one re-checked restore key as submittable or skipped."""
    agent, light_row, reason = hydrated
    name = archive_light_name(light_row)
    if agent is None or reason is not None:
        skips.append(ArchiveRestoreSkip(key=key, name=name, reason=reason or "skipped"))
    else:
        submittable.append((key, name, agent))


async def _off_loop[T](owner: Any, work: Callable[[], T]) -> T:
    runner = getattr(owner, "_archive_run_off_thread", None)
    if callable(runner):
        return await runner(work)  # type: ignore[no-any-return]
    return await asyncio.to_thread(work)


def run_archive_restore(
    owner: Any,
    *,
    targets: ArchiveRestoreTargets | None = None,
    keys: list[str] | None = None,
    and_show: bool = False,
) -> ArchiveRestoreSummary:
    """Restore Archive runs to the Inbox and keep their rows in place.

    Restores exactly ``targets`` (the chooser's resolved list), else the
    explicit ``keys``, else the current marks or cursor. Returns a summary
    for toasts and tests. The cursor never moves: every restored row stays in
    the list behind the ``⌂ restored`` overlay until the query changes or the
    Archive is left, and the pulse counts the agent through the revive
    path's own inbox refresh.
    """
    if targets is None:
        targets = (
            ArchiveRestoreTargets(keys=tuple(keys))
            if keys is not None
            else collect_archive_restore_targets(owner)
        )
    skips = list(targets.skipped)
    submittable: list[tuple[str, str, Any]] = []
    for key in targets.keys:
        hydrated = hydrate_archive_candidate(owner, key, targets.rows.get(key))
        _hydrated_entry(key, hydrated, submittable, skips)
    return _submit_and_finish(owner, submittable, skips, and_show)


async def run_archive_restore_async(
    owner: Any,
    *,
    targets: ArchiveRestoreTargets | None = None,
    keys: list[str] | None = None,
    and_show: bool = False,
) -> ArchiveRestoreSummary:
    """Submit-time re-check off the event loop, then restore as usual.

    Container resolution may query the corpus and the bundle reads in
    :func:`hydrate_archive_candidate` are sync file I/O, so both run in a
    thread worker. The selection is re-captured after the await: when the
    Archive view is gone, the submit aborts quietly instead of toasting into
    a view the user already left.
    """
    from ._archive_view_state import agents_archive_view_state

    if targets is None and keys is not None:
        targets = ArchiveRestoreTargets(keys=tuple(keys))
    if targets is None:
        plan = capture_archive_restore_plan(owner)
        targets = await _off_loop(owner, lambda: resolve_archive_restore_targets(plan))
    resolved = targets
    out_skips = list(resolved.skipped)
    submittable: list[tuple[str, str, Any]] = []
    for key in resolved.keys:
        hydrated = await _off_loop(
            owner,
            partial(hydrate_archive_candidate, owner, key, resolved.rows.get(key)),
        )
        _hydrated_entry(key, hydrated, submittable, out_skips)
    try:
        state = agents_archive_view_state(owner)
        still_archive = getattr(state, "active_view", None) == AGENTS_VIEW_ARCHIVE
    except Exception:
        still_archive = False
    if not still_archive:
        return ArchiveRestoreSummary(
            restored=(), skipped=tuple(out_skips), failed=(), and_show=and_show
        )
    return _submit_and_finish(owner, submittable, out_skips, and_show)


def _submit_and_finish(
    owner: Any,
    submittable: list[tuple[str, str, Any]],
    skips: list[ArchiveRestoreSkip],
    and_show: bool,
) -> ArchiveRestoreSummary:
    """Submit hydrated agents through quiet revive, then toast or reveal."""
    from ._archive_view import mark_archive_row_restored

    if not submittable:
        summary = ArchiveRestoreSummary(restored=(), skipped=tuple(skips), failed=())
        _toast_restore(owner, summary)
        return summary

    show_hook: Any | None = None
    if and_show and len(submittable) == 1:
        show_agent = submittable[0][2]
        show_name = submittable[0][1]

        def show_hook() -> None:
            _show_restored_in_inbox(owner, show_agent, show_name)

    delta, hook_consumed = _submit_revive(
        owner,
        [agent for _key, _name, agent in submittable],
        on_revive_loaded=show_hook,
    )
    if delta is None or delta is False:
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
    _bump_archive_pulse(owner)
    if and_show and len(restored) == 1 and not failures:
        # The quiet revive runs the hook on its delta refresh; older entry
        # points never consume it, so reveal synchronously for them.
        if not hook_consumed:
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
        messages: list[str] = []
        for _key, _name, message in summary.failed:
            text = str(message or "revive failed")
            if text not in messages:
                messages.append(text)
        shown = "; ".join(messages[:2])
        extra = f", +{len(messages) - 2} more" if len(messages) > 2 else ""
        parts.append(f"failed {len(summary.failed)} ({shown}{extra})")
    else:
        parts.append("failed 0")
    notify_owner(
        owner,
        " · ".join(parts),
        severity="warning" if total == 0 else "information",
    )


def _show_restored_in_inbox(owner: Any, agent: Any, name: str) -> None:
    """Leave the Archive and reveal one restored agent in the Inbox.

    Runs after the revive delta refresh lands, never synchronously with
    the submit. When the parked Inbox filter hides the agent, the same
    filtered-target rule as link follow applies (the helper from
    arrivals-finish): commit ``name:"<canonical>"``, push the old query
    to ``^``, and toast.
    """
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
    try:
        from .._link_follow_targets import reveal_filtered_loaded_agent
    except Exception:
        reveal_filtered_loaded_agent = None  # type: ignore[assignment]
    if reveal_filtered_loaded_agent is not None:
        try:
            if bool(reveal_filtered_loaded_agent(owner, agent)):
                return
        except Exception:
            pass
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
