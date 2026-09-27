"""Live tails, following, and the 1 Hz tick for the ⊛ FINAL deck.

Epic sase-1b2, phase ``final-live`` (plan §3.7 and §4.18).

The projection already ships per-operation ``live_tail`` lines (at most
``tail_lines`` entries, ``\\r``-collapsed, ANSI preserved); this module owns
everything the TUI adds on top:

- the ``ace.agent_decks.final_tail_delay_seconds`` gate: no tail renders
  until the active op has run for that long (``0`` renders immediately),
- sanitizing and capping the in-card tail to
  :data:`FINAL_LIVE_TAIL_MAX_LINES` lines through ``render_axe_output``,
- the follow target: the tail follows the newest run and the latest
  attempt, and never yanks the reader (arrival marker plus scroll-up
  pause / bottom resume),
- the 1 Hz tick predicates: the tick runs only while FINAL shows the
  selected node's active finalization, respects the navigation and typing
  gates, and every collection runs pump-free off the message pump.

Only the newest run's newest attempt can carry live content in practice:
the live sink (plan §3.3 C4) removes both ``.live`` files on normal
completion and retains them only on timeout, kill, or a terminal-write
failure. Rendering is therefore data-driven — tails appear wherever an
active op still holds live lines — with :func:`select_live_follow_target`
naming the newest such run and attempt so the tick and the renderer agree
on what "following" means.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.text import Text

from ....agent_decks_settings import DEFAULT_FINAL_TAIL_DELAY_SECONDS

#: At most this many live-tail lines render inside a FINAL card (§3.7).
FINAL_LIVE_TAIL_MAX_LINES = 12

#: The live-tick cadence in seconds: elapsed counters plus tail refresh.
FINAL_LIVE_TICK_SECONDS = 1.0

#: Row-summary phases that count as an active finalization (§3.7 scope).
FINAL_ACTIVE_SUMMARY_PHASES = frozenset({"declaring", "executing"})


def finalization_active(summary: Any) -> bool:
    """Return whether ``summary`` describes an active finalization.

    ``summary`` is a row-summary object (or mapping) with a ``phase``
    field. Only ``declaring``/``executing`` count: planned runs have
    nothing live yet and settled runs are repainted through the normal
    drift path, never the tick.
    """
    try:
        phase = summary.get("phase") if isinstance(summary, dict) else summary.phase
    except Exception:
        return False
    try:
        return str(phase) in FINAL_ACTIVE_SUMMARY_PHASES
    except Exception:
        return False


def _tail_gate_open(
    *,
    op_started_at: Any,
    now: float,
    delay_seconds: float = DEFAULT_FINAL_TAIL_DELAY_SECONDS,
) -> bool:
    """Return whether an op's live tail may render yet (§3.7 tail gate).

    A non-positive delay renders immediately. An op whose start is
    unknown renders nothing: without a start the gate cannot prove the
    op ran long enough, so fast ops stay a bare ``▶``.
    """
    try:
        delay = float(delay_seconds)
    except (TypeError, ValueError):
        return False
    if delay <= 0:
        return True
    if op_started_at is None or isinstance(op_started_at, bool):
        return False
    try:
        started = float(op_started_at)
    except (TypeError, ValueError):
        return False
    try:
        return float(now) - started >= delay
    except (TypeError, ValueError):
        return False


def _sanitize_live_tail_lines(
    lines: Any,
    *,
    max_lines: int = FINAL_LIVE_TAIL_MAX_LINES,
) -> list[str]:
    """Return the last ``max_lines`` tail lines as plain strings.

    Each line keeps only its last ``\\r``-separated segment (matching the
    projection's carriage-return collapse for tails collected outside the
    projection), and surrogates never escape: undecodable input already
    arrived with replacement characters.
    """
    try:
        limit = max(0, int(max_lines))
    except (TypeError, ValueError):
        limit = FINAL_LIVE_TAIL_MAX_LINES
    collected: list[str] = []
    if isinstance(lines, (str, bytes)):
        return []
    try:
        items = list(lines or ())
    except TypeError:
        return []
    for line in items:
        try:
            text = str(line)
        except Exception:
            continue
        if "\r" in text:
            text = text.rsplit("\r", 1)[-1]
        collected.append(text)
    if limit == 0:
        return []
    return collected[-limit:]


def _render_live_tail(source_id: str, lines: list[str]) -> Text:
    """Render sanitized tail ``lines`` through the shared ANSI renderer.

    Never raw Rich markup: ``render_axe_output(…, "ansi")`` parses the
    ANSI escapes the subprocess actually emitted, exactly like the
    monitor and named-proc sections do.
    """
    from ....util.axe_log_renderer import render_axe_output

    return render_axe_output(str(source_id), "\n".join(lines), "ansi")


@dataclass(frozen=True)
class LiveTailOptions:
    """One render pass's live-tail inputs (plan §3.7).

    ``delay_seconds`` gates the tail; ``now`` freezes the elapsed header
    (tests pass it explicitly, the loader passes collection time);
    ``follow``/``run_id`` scope the tail to the followed newest run and
    latest attempt; ``instance_id`` keys the renderer cache slot.
    """

    delay_seconds: float
    now: float | None = None
    follow: LiveFollowTarget | None = None
    run_id: str | None = None
    instance_id: str = ""


def _fit_line(line: str, width: int) -> str:
    """Truncate ``line`` to ``width`` cells with an ellipsis marker."""
    width = max(20, int(width))
    if len(line) <= width:
        return line
    return line[: max(0, width - 1)] + "…"


def live_options_for(
    delay_seconds: Any,
    *,
    now: float | None = None,
    follow: LiveFollowTarget | None = None,
    run_id: str | None = None,
    instance_id: str = "",
) -> LiveTailOptions | None:
    """Build one render pass's :class:`LiveTailOptions`, or None to skip tails.

    A non-numeric delay disables tails (preserving the pre-live render
    path for callers that pass the setting straight through).
    """
    if delay_seconds is None or isinstance(delay_seconds, bool):
        return None
    try:
        delay = float(delay_seconds)
    except (TypeError, ValueError):
        return None
    return LiveTailOptions(
        delay_seconds=delay,
        now=now,
        follow=follow,
        run_id=run_id,
        instance_id=instance_id,
    )


def build_live_tail_renderables(
    operation: Any,
    options: LiveTailOptions,
    *,
    width: int,
    max_lines: int = FINAL_LIVE_TAIL_MAX_LINES,
) -> list[Text]:
    """Return the gated in-card live tail for one active op (plan §3.7).

    Empty unless the op is active, still holds live lines, passes the
    tail-delay gate, and belongs to the followed run and latest attempt.
    The header carries the elapsed label so the 1 Hz tick has a visible
    effect; content renders through ``render_axe_output(…, "ansi")``.
    """
    import time as _time

    tail = _live_tail_lines_for_operation(
        operation,
        delay_seconds=options.delay_seconds,
        now=options.now,
        follow=options.follow,
        run_id=options.run_id,
    )
    if not tail:
        return []
    started = _field(operation, "started_at")
    try:
        moment = options.now if options.now is not None else _time.time()
    except Exception:
        moment = 0.0
    try:
        elapsed = _format_live_elapsed(started, float(moment))
    except Exception:
        elapsed = None
    try:
        op_name = str(_field(operation, "op") or "")
    except Exception:
        op_name = ""
    instance_id = options.instance_id or "finalizer"
    source_id = f"final:{instance_id}:{op_name}" if op_name else f"final:{instance_id}"
    header = f"  live{(' · ' + elapsed) if elapsed else ''}"
    lines = [Text(_fit_line(header, width), style="dim")]
    try:
        rendered = _render_live_tail(source_id, tail[:max_lines])
    except Exception:
        return lines
    try:
        rendered_lines = rendered.split("\n")
    except Exception:
        return lines
    for rendered_line in rendered_lines:
        entry = Text("  ")
        try:
            entry.append_text(rendered_line)
        except Exception:
            entry.append(rendered_line.plain)
        if len(entry.plain) > width:
            try:
                entry.truncate(width, overflow="ellipsis")
            except Exception:
                entry = Text(_fit_line(entry.plain, width))
        lines.append(entry)
    return lines


def _field(item: Any, name: str) -> Any:
    """Read ``name`` from a mapping or an attribute holder, or None."""
    try:
        if isinstance(item, dict):
            return item.get(name)
        return getattr(item, name)
    except Exception:
        return None


def _is_operation_active(operation: Any) -> bool:
    """Return whether ``operation`` is still running (no exit recorded)."""
    returncode = _field(operation, "returncode")
    if isinstance(returncode, bool):
        return True
    return returncode is None


def _operation_live_lines(operation: Any) -> list[str]:
    """Return the raw live-tail lines attached to ``operation``."""
    tail = _field(operation, "live_tail")
    if not isinstance(tail, (list, tuple)):
        return []
    return [str(line) for line in tail]


def _operation_attempt(operation: Any) -> int | None:
    """Return the attempt number scoping ``operation``, if any."""
    attempt = _field(operation, "attempt")
    if attempt is None or isinstance(attempt, bool):
        return None
    try:
        return int(attempt)
    except (TypeError, ValueError):
        return None


def _latest_attempt_number(run: Any) -> int | None:
    """Return the highest attempt number seen across one run's instances."""
    latest: int | None = None
    instances = _field(run, "instances")
    if instances is None:
        return None
    for item in instances or ():
        attempts = _field(item, "attempts") or ()
        for attempt in attempts:
            try:
                number = int(_field(attempt, "attempt"))
            except (TypeError, ValueError, AttributeError):
                continue
            if latest is None or number > latest:
                latest = number
        operations = _field(item, "operations") or ()
        for operation in operations or ():
            op_number = _operation_attempt(operation)
            if op_number is not None and (latest is None or op_number > latest):
                latest = op_number
    return latest


@dataclass(frozen=True)
class LiveFollowTarget:
    """The newest run and latest attempt the live tail follows (§3.7)."""

    run_id: str
    attempt: int | None = None


def select_live_follow_target(runs: Any) -> LiveFollowTarget | None:
    """Return the follow target: newest run holding live content.

    Runs arrive in roster order, so the newest candidate is the last one
    with an active op carrying live lines. ``None`` means no run has
    anything live and no tail renders anywhere.
    """
    try:
        ordered = list(runs or ())
    except TypeError:
        return None
    for run in reversed(ordered):
        run_id = _field(run, "run_id")
        instances = _field(run, "instances")
        if run_id is None or instances is None:
            continue
        live = False
        for item in instances or ():
            operations = _field(item, "operations")
            if operations is None:
                continue
            for operation in operations or ():
                if _is_operation_active(operation) and _operation_live_lines(operation):
                    live = True
                    break
            if live:
                break
        if not live:
            continue
        try:
            target_id = str(run_id) if run_id else ""
        except Exception:
            continue
        if not target_id:
            continue
        return LiveFollowTarget(run_id=target_id, attempt=_latest_attempt_number(run))
    return None


def _live_tail_lines_for_operation(
    operation: Any,
    *,
    delay_seconds: float = DEFAULT_FINAL_TAIL_DELAY_SECONDS,
    now: float | None = None,
    follow: LiveFollowTarget | None = None,
    run_id: str | None = None,
) -> list[str]:
    """Return the sanitized tail lines to render for ``operation``.

    Empty unless the op is active, holds live lines, passes the tail
    gate, and — when ``follow`` is given — belongs to the followed run
    and latest attempt. ``now`` defaults to the current wall clock; pass
    it explicitly in tests.
    """
    import time as _time

    if not _is_operation_active(operation):
        return []
    raw = _operation_live_lines(operation)
    if not raw:
        return []
    if follow is not None:
        if run_id is None or str(run_id) != follow.run_id:
            return []
        if follow.attempt is not None:
            attempt = _operation_attempt(operation)
            if attempt is not None and attempt != follow.attempt:
                return []
    started = _field(operation, "started_at")
    moment = _time.time() if now is None else now
    gate = _tail_gate_open(
        op_started_at=started, now=moment, delay_seconds=delay_seconds
    )
    if not gate:
        return []
    return _sanitize_live_tail_lines(raw)


def _format_live_elapsed(started_at: Any, now: float) -> str | None:
    """Return a short elapsed label (``12s`` / ``3m04s``) for the tail header."""
    if started_at is None or isinstance(started_at, bool):
        return None
    try:
        elapsed = float(now) - float(started_at)
    except (TypeError, ValueError):
        return None
    if elapsed < 0:
        return None
    if elapsed >= 60:
        return f"{int(elapsed // 60)}m{int(elapsed % 60):02d}s"
    return f"{elapsed:.0f}s"


@dataclass
class _LiveFollowState:
    """Scroll-follow pause for the FINAL live tail (§3.7 following).

    Scrolling up pauses the tail refresh so the tick never yanks the
    reader; returning to the bottom resumes it. The rail's arrival dot
    (owned by the generalized block host) still marks newer runs while
    paused.
    """

    paused: bool = False

    def note_scroll(self, *, at_bottom: bool) -> bool:
        """Record one scroll position; return True when a resume refresh is due."""
        try:
            bottom = bool(at_bottom)
        except Exception:
            bottom = True
        if bottom:
            if self.paused:
                self.paused = False
                return True
            return False
        self.paused = True
        return False


def _should_live_tick(
    *,
    visible: bool,
    active: bool,
    navigating: bool,
    typing: bool,
    paused: bool,
    in_flight: bool,
) -> bool:
    """Return whether the 1 Hz tick may spawn a live collection (§3.7 scope).

    The tick runs only while some panel shows FINAL for the selected node
    and that node has an active finalization. It stands down while the
    user navigates or types, while follow is paused, and while a previous
    collection is still in flight (coalesced, last-request-wins: the next
    tick retries).
    """
    if in_flight or paused or typing or navigating:
        return False
    return bool(visible and active)


class FinalLiveTicker:
    """Coalesced 1 Hz live-tick state for one FINAL view.

    The Textual timer handle stays with the owning view (started only
    while its subject is active, stopped on hide, subject change, settle
    and teardown); this object holds the remainder: the follow-pause
    state and the in-flight guard. :meth:`want_tick` is the thin,
    side-effect-free predicate the timer callback consults before
    spawning pump-free collection work.
    """

    def __init__(self) -> None:
        """Initialize an idle ticker with follow engaged."""
        self.follow = _LiveFollowState()
        self._in_flight = False

    @property
    def in_flight(self) -> bool:
        """Return whether a live collection is currently running."""
        return self._in_flight

    def want_tick(
        self,
        *,
        visible: bool,
        active: bool,
        navigating: bool,
        typing: bool,
    ) -> bool:
        """Return whether the timer callback should spawn a collection."""
        return _should_live_tick(
            visible=visible,
            active=active,
            navigating=navigating,
            typing=typing,
            paused=self.follow.paused,
            in_flight=self._in_flight,
        )

    def begin(self) -> bool:
        """Claim the in-flight slot; False when a collection already runs."""
        if self._in_flight:
            return False
        self._in_flight = True
        return True

    def finish(self) -> None:
        """Release the in-flight slot after a collection settles."""
        self._in_flight = False

    def note_scroll(self, *, at_bottom: bool) -> bool:
        """Record one scroll position; return True when a resume refresh is due."""
        return self.follow.note_scroll(at_bottom=at_bottom)


__all__ = [
    "FINAL_ACTIVE_SUMMARY_PHASES",
    "FINAL_LIVE_TAIL_MAX_LINES",
    "FINAL_LIVE_TICK_SECONDS",
    "FinalLiveTicker",
    "LiveFollowTarget",
    "LiveTailOptions",
    "build_live_tail_renderables",
    "finalization_active",
    "live_options_for",
    "select_live_follow_target",
]
