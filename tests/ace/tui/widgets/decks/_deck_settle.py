"""Shared anchor-scroll settle wait for deck pilot tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import textual
from textual.containers import VerticalScroll

from sase.ace.testing import wait_for


def describe_files_nav(panel: Any) -> str:
    """Summarize pending Files spread navigation for timeout output.

    Reports the live scroll position and extent plus the durable
    navigation state (pending index, retry counter, generation and
    confirmed flag) so the next CI timeout names the stall instead of
    just the wait.
    """
    try:
        panel_index = int(getattr(panel, "_panel_index", 0))
    except Exception:
        panel_index = 0
    try:
        scroll = panel.query_one(
            f"#agent-deck-panel-{panel_index}-files-scroll",
            VerticalScroll,
        )
        scroll_y: int | None = int(scroll.scroll_y)
        max_scroll_y: int | None = int(scroll.max_scroll_y)
    except Exception:
        scroll_y = None
        max_scroll_y = None
    try:
        pending = getattr(panel, "_files_pending_scroll_index", None)
        pending_repr = repr(None if pending is None else int(pending))
    except Exception:
        pending_repr = "<unreadable>"
    try:
        retry = int(getattr(panel, "_files_scroll_retry", 0) or 0)
    except Exception:
        retry = "<unreadable>"  # type: ignore[assignment]
    try:
        generation = int(getattr(panel, "_files_transition_generation", -1))
    except Exception:
        generation = "<unreadable>"  # type: ignore[assignment]
    try:
        confirmed = bool(getattr(panel, "_files_scroll_confirmed", False))
    except Exception:
        confirmed = "<unreadable>"  # type: ignore[assignment]
    return (
        f"files_nav: scroll_y={scroll_y} max_scroll_y={max_scroll_y} "
        f"pending={pending_repr} retry={retry} "
        f"generation={generation} confirmed={confirmed}"
    )


def _settle_state_line(
    scroll_pos: Callable[[], int],
    live_target: Callable[[], int | None],
    last_target: int | None,
    last_pos: int | None,
    diagnose: Callable[[], str] | None,
) -> str:
    """Build the diagnostic line appended to an anchor-wait timeout."""
    try:
        pos: int | None = int(scroll_pos())
    except Exception:
        pos = last_pos
    try:
        target: int | None = live_target()
    except Exception:
        target = last_target
    if target is None:
        target = last_target
    parts = [f"anchor_wait: scroll_y={pos} live_target={target}"]
    if diagnose is not None:
        try:
            parts.append(diagnose())
        except Exception as exc:
            parts.append(f"diagnose failed: {exc!r}")
    parts.append(f"textual={textual.__version__}")
    return " ".join(parts)


async def wait_for_anchor_scroll(
    pilot: Any,
    scroll_pos: Callable[[], int],
    live_target: Callable[[], int | None],
    *,
    timeout: float = 5.0,
    diagnose: Callable[[], str] | None = None,
) -> int:
    """Wait until an anchor scroll settles on its live landing target.

    The landing target depends on layout (published anchors, trailing
    reserve, scrollbar clamping), so it can shift across frames while the
    view settles. Callers must not snapshot it once and wait for equality
    with the stale value: this helper re-reads the target on every poll
    and only succeeds when the scroll position matches the *same* target
    on two consecutive settle iterations, proving the landing converged
    rather than transited through the value.

    When the wait times out, the error keeps the original message and
    appends the last observed scroll position, the live target, the
    optional ``diagnose`` state and the Textual version. The timeout and
    the success condition are unchanged by ``diagnose``.
    """
    last: list[int | None] = [None]
    seen_pos: list[int | None] = [None]

    def settled_on_live_target() -> bool:
        try:
            target = live_target()
        except Exception:
            last[0] = None
            return False
        if target is None:
            last[0] = None
            return False
        try:
            pos = int(scroll_pos())
        except Exception:
            seen_pos[0] = None
            last[0] = None
            return False
        seen_pos[0] = pos
        settled = pos == int(target) and last[0] == int(target)
        last[0] = int(target)
        return settled

    try:
        await wait_for(pilot, settled_on_live_target, timeout=timeout)
    except AssertionError as exc:
        state = _settle_state_line(
            scroll_pos, live_target, last[0], seen_pos[0], diagnose
        )
        raise AssertionError(f"{exc}\n{state}") from exc
    target = live_target()
    assert target is not None
    return int(target)


__all__ = ["describe_files_nav", "wait_for_anchor_scroll"]
