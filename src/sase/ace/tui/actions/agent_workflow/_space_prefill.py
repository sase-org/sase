"""`<space>` late prefill from the launchable-MRU snapshot.

Epic sase-1ex, phase space-prefill. A warm snapshot serves the ``<space>``
prefill with no I/O; a cold, error, or launch-pending snapshot opens a blank
bar at once and applies a late prefill only to an untouched session.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

__all__ = [
    "drop_pending_space_prefill",
    "peek_ready_mru_pairs",
    "peek_space_prefill_pairs",
    "record_pending_space_prefill",
    "try_apply_pending_space_prefill",
]


def peek_ready_mru_pairs(app: object) -> list[tuple[str, str]] | None:
    """Return snapshot pairs when the snapshot is ready, else ``None``.

    For the non-hot entry points (`,.` history and the editor): they open a
    modal or editor anyway, so a ready-but-stale snapshot is fine and only a
    cold/error snapshot falls back to the synchronous loader.
    """
    peek = getattr(app, "peek_launchable_mru_snapshot", None)
    if not callable(peek):
        return None
    try:
        snapshot = peek()
    except Exception:  # noqa: BLE001 - fall back to the loader.
        return None
    try:
        if snapshot is not None and snapshot.state == "ready":
            return list(snapshot.pairs)
    except Exception:  # noqa: BLE001 - a broken snapshot reads as cold.
        return None
    return None


def peek_space_prefill_pairs(app: object) -> list[tuple[str, str]] | None:
    """Return snapshot pairs for an immediate `<space>` prefill, else ``None``.

    Warm means ``ready`` and not ``refresh_pending`` (no launch/set-current
    rebuild is outstanding). Cold, error, or pending snapshots open a blank
    bar plus a pending prefill instead.
    """
    peek = getattr(app, "peek_launchable_mru_snapshot", None)
    if not callable(peek):
        return None
    try:
        snapshot = peek()
    except Exception:  # noqa: BLE001 - blank bar plus pending prefill.
        return None
    try:
        if (
            snapshot is not None
            and snapshot.state == "ready"
            and not snapshot.refresh_pending
        ):
            return list(snapshot.pairs)
    except Exception:  # noqa: BLE001 - a broken snapshot reads as cold.
        return None
    return None


def drop_pending_space_prefill(app: object) -> None:
    """Drop any pending `<space>` late prefill without applying it."""
    try:
        app._pending_space_prefill = None  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - pending state is best-effort.
        pass


def record_pending_space_prefill(app: object) -> None:
    """Record a pending late prefill keyed to the new prompt session.

    Called right after the blank home bar mounts. A new `<space>` overwrites
    any previous pending entry, so a reopened bar never receives an older
    session's prefill. Failures leave no pending entry.
    """
    try:
        from sase.ace.tui.actions.agent_workflow._types import (
            current_prompt_session,
        )

        session = current_prompt_session(app)
        if session is None:
            return
        session_id = session.session_id
    except Exception:  # noqa: BLE001 - no session means no pending prefill.
        return
    cursor: tuple[int, int] | None = None
    pane_index: int | None = None
    history_len: int = -1
    try:
        # Phase ``prompt-active-state``: the shared ``_mounted_prompt_bar``
        # accessor already prefers explicit state with a DOM fallback, so no
        # second lookup lives here.
        accessor = getattr(app, "_mounted_prompt_bar", None)
        bar = accessor() if callable(accessor) else None
        if bar is not None:
            try:
                area = bar.active_text_area()
            except Exception:  # noqa: BLE001 - no active pane yet.
                area = None
            if area is not None:
                try:
                    cursor = area.cursor_location
                except Exception:  # noqa: BLE001 - cursor read is best-effort.
                    cursor = None
                try:
                    history = getattr(area, "history", None)
                    undo_stack = getattr(history, "_undo_stack", None)
                    if undo_stack is not None:
                        history_len = len(undo_stack)
                except Exception:  # noqa: BLE001 - history read is best-effort.
                    history_len = -1
            try:
                pane_index = bar._stack.selected_index
            except Exception:  # noqa: BLE001 - pane read is best-effort.
                pane_index = None
    except Exception:  # noqa: BLE001 - pending capture never breaks the open.
        pass
    try:
        app._pending_space_prefill = {  # type: ignore[attr-defined]
            "session_id": session_id,
            "cursor": cursor,
            "pane_index": pane_index,
            "history_len": history_len,
        }
    except Exception:  # noqa: BLE001 - pending state is best-effort.
        pass


def try_apply_pending_space_prefill(
    app: object,
    pairs: Sequence[tuple[str, str]],
) -> bool:
    """Apply a pending `<space>` prefill from freshly published pairs.

    Consumes the pending entry in all cases. Applies only when the recorded
    session is still live, the bar is still mounted in single-pane prompt
    mode, and the active text area is untouched (empty, no recorded edits,
    cursor and pane unchanged). Applying sets the live context, loads the
    text, moves the cursor to the end, and refreshes title, subtitle, and
    the dispatch line. Returns whether the prefill landed.
    """
    try:
        pending = getattr(app, "_pending_space_prefill", None)
    except Exception:  # noqa: BLE001 - no pending entry.
        return False
    if not isinstance(pending, dict):
        return False
    drop_pending_space_prefill(app)
    try:
        from sase.ace.tui.actions.agent_workflow._types import (
            prompt_session_is_live,
        )

        if not prompt_session_is_live(app, pending.get("session_id")):
            return False
    except Exception:  # noqa: BLE001 - a dead session drops the prefill.
        return False
    try:
        # Phase ``prompt-active-state``: the shared ``_mounted_prompt_bar``
        # accessor already prefers explicit state with a DOM fallback, so no
        # second lookup lives here. A missing accessor reads as dismissed.
        accessor = getattr(app, "_mounted_prompt_bar", None)
        bar = accessor() if callable(accessor) else None
        if bar is None or not bool(getattr(bar, "is_mounted", False)):
            return False
        if getattr(bar, "_mode", "prompt") != "prompt":
            return False
        try:
            stack = getattr(bar, "_stack", None)
            if stack is not None and len(stack) != 1:
                return False
        except Exception:  # noqa: BLE001 - an unreadable stack drops it.
            return False
        try:
            area = bar.active_text_area()
        except Exception:  # noqa: BLE001 - no active pane drops the prefill.
            return False
        try:
            if area.text.strip() != "":
                return False
        except Exception:  # noqa: BLE001 - unreadable text drops the prefill.
            return False
        try:
            if pending.get("cursor") is not None and (
                area.cursor_location != pending.get("cursor")
            ):
                return False
        except Exception:  # noqa: BLE001 - unreadable cursor drops the prefill.
            return False
        try:
            if pending.get("pane_index") is not None and (
                bar._stack.selected_index != pending.get("pane_index")
            ):
                return False
        except Exception:  # noqa: BLE001 - unreadable pane drops the prefill.
            return False
        try:
            expected_history = pending.get("history_len", -1)
            if isinstance(expected_history, int) and expected_history >= 0:
                history = getattr(area, "history", None)
                undo_stack = getattr(history, "_undo_stack", None)
                if undo_stack is not None and len(undo_stack) != expected_history:
                    return False
        except Exception:  # noqa: BLE001 - unreadable history drops it.
            return False
    except Exception:  # noqa: BLE001 - any guard failure drops the prefill.
        return False
    try:
        from sase.ace.tui.actions.agent_workflow._entry_custom import (
            resolve_vcs_xprompt_mru_head,
        )
    except Exception:  # noqa: BLE001 - unresolvable head leaves a blank bar.
        return False
    try:
        resolved = resolve_vcs_xprompt_mru_head(pairs)
    except Exception:  # noqa: BLE001 - resolution failure leaves blank.
        return False
    if resolved is None:
        return False
    initial_text, display_name, history_sort_key = resolved
    try:
        context = getattr(app, "_prompt_context", None)
        if context is None:
            return False
        context.display_name = display_name
        context.history_sort_key = history_sort_key
        area.load_text(initial_text)
        try:
            bar._sync_state_from_widgets()
        except Exception:  # noqa: BLE001 - model sync is best-effort.
            pass
        try:
            bar._cursor_to_end(area)
        except Exception:  # noqa: BLE001 - cursor placement is best-effort.
            pass
        try:
            bar._sync_state_from_widgets()
        except Exception:  # noqa: BLE001 - model sync is best-effort.
            pass
        try:
            bar._refresh_title()
        except Exception:  # noqa: BLE001 - chrome refresh is best-effort.
            pass
        try:
            bar.set_prompt_mode_subtitle(bar.insert_mode_subtitle())
        except Exception:  # noqa: BLE001 - chrome refresh is best-effort.
            pass
        try:
            bar._refresh_dispatch_context_line()
        except Exception:  # noqa: BLE001 - chrome refresh is best-effort.
            pass
    except Exception:  # noqa: BLE001 - a failed apply leaves the blank bar.
        return False
    return True
