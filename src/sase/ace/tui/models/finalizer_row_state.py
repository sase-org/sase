"""Pure finalizer glance state over the in-memory ``Agent`` (plan §3.5).

No I/O and no flag reads: call sites gate on ``final_deck_enabled()`` so
flag-off rendering stays byte-identical to today. Buckets, ordering,
filters, capacity, ``agent_row_is_in_flight`` and row actions are untouched
(plan D11); only the ``RUNNING`` word overlay and the ``⊛`` chip are derived
here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.finalizers.view_vocabulary import FINAL_GLYPH, STATE_STYLES

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent

#: Summary phases where finalization is under way (plan C5).
ACTIVE_PHASES = frozenset({"declaring", "executing"})

#: D10 severity order for the session supersede rule.
_CHIP_SEVERITY: dict[str, int] = {
    "failed": 5,
    "refused": 4,
    "interrupted": 3,
    "deferred": 2,
    "running": 1,
}


@dataclass(frozen=True)
class FinalizerRowState:
    """Glance state for one row: the FINALIZING overlay plus the ``⊛`` chip."""

    is_finalizing: bool = False
    chip_text: str | None = None
    chip_style: str | None = None


def finalizer_summary_token(agent: Agent) -> tuple[object, ...] | None:
    """Return the compact summary token for render keys and signatures.

    ``(phase, status, updated_at, instance_count)``; None when the node has
    no summary (legacy runs).
    """
    summary = agent.finalizer_status
    if summary is None:
        return None
    return (
        summary.phase,
        summary.status,
        summary.updated_at,
        summary.instance_count,
    )


def _instance_label(instance_id: str, op: str | None, step: str | None) -> str:
    """Return ``<id>`` plus the step label, else the op label (plan §3.5)."""
    label = step or op
    if label:
        return f"{instance_id} · {label}"
    return instance_id


def _chip_text(
    state_key: str, instance_id: str, op: str | None, step: str | None
) -> str:
    """Render the ``⊛`` chip: the state glyph only for non-running states."""
    style = STATE_STYLES[state_key]
    glyph = "" if state_key == "running" else style.glyph
    return f"{FINAL_GLYPH}{glyph} {_instance_label(instance_id, op, step)}"


def _chip_style(state_key: str) -> str:
    color = STATE_STYLES[state_key].color
    if color == "dim":
        return "dim"
    return f"bold {color}"


def _member_candidates(
    agent: Agent,
) -> list[tuple[str, str | None, str | None, str | None]]:
    """Return ``(state_key, id, op, step)`` rows for one shell's summary.

    A ``running`` instance on a non-RUNNING turn derives to ``interrupted``:
    the turn ended while finalization never settled.
    """
    summary = agent.finalizer_status
    if summary is None:
        return []
    turn_terminal = agent.status != "RUNNING"
    rows: list[tuple[str, str | None, str | None, str | None]] = []
    for instance in summary.instances:
        status = instance.status or ""
        if status == "running" and turn_terminal:
            state_key = "interrupted"
        elif status == "waiting" and summary.phase == "executing":
            state_key = "running"
        else:
            state_key = {
                "planned": "planned",
                "waiting": "planned",
                "running": "running",
                "success": "success",
                "failed": "failed",
                "refused": "refused",
                "deferred": "deferred",
                "not_triggered": "not triggered",
                "skipped": "skipped",
                "not_run": "not run",
            }.get(status, "planned")
        rows.append((state_key, instance.id, instance.op, instance.step))
    if summary.phase in ACTIVE_PHASES and not rows and turn_terminal:
        return [("interrupted", "", None, None)]
    return rows


def _pick_chip(
    rows: list[tuple[str, str | None, str | None, str | None]],
) -> FinalizerRowState:
    best: tuple[str, str | None, str | None, str | None] | None = None
    for row in rows:
        if _CHIP_SEVERITY.get(row[0], 0) <= 0:
            continue
        if best is None or _CHIP_SEVERITY[row[0]] >= _CHIP_SEVERITY[best[0]]:
            best = row
    if best is None:
        return FinalizerRowState()
    state_key, instance_id, op, step = best
    return FinalizerRowState(
        chip_text=_chip_text(state_key, instance_id or "", op, step),
        chip_style=_chip_style(state_key),
    )


def finalizer_row_state(agent: Agent) -> FinalizerRowState:
    """Derive the glance state for one agent row (plan §3.5, D11).

    ``FINALIZING`` overlays the ``RUNNING`` word only; warnings never produce
    a chip and ``success`` stays silent.
    """
    summary = agent.finalizer_status
    if summary is None:
        return FinalizerRowState()
    state = _pick_chip(_member_candidates(agent))
    is_finalizing = summary.phase in ACTIVE_PHASES and agent.display_status == "RUNNING"
    return FinalizerRowState(
        is_finalizing=is_finalizing,
        chip_text=state.chip_text,
        chip_style=state.chip_style,
    )


def session_finalizer_row_state(
    container: Agent,
    members: Sequence[Agent] | None = None,
) -> FinalizerRowState:
    """Aggregate member shells by the D10 session supersede rule.

    Only runs after the newest successful settled run are considered; among
    those the highest severity wins (failed > refused > interrupted >
    deferred > running), with ``k of n runs`` appended when n > 1.
    ``members`` defaults to the container's session turns (gates excluded).
    """
    turns: list[Agent]
    if members is None:
        from sase.ace.tui.models.agent_session_members import (
            concrete_agent_session_turn_rows,
        )

        try:
            turns = [
                turn
                for turn in concrete_agent_session_turn_rows(container)
                if not turn.is_gate
            ]
        except (ValueError, AttributeError):
            turns = [container, *container.followup_agents]
        if not turns:
            turns = [container, *container.followup_agents]
    else:
        turns = [turn for turn in members if not turn.is_gate]
    considered: list[Agent] = []
    for turn in turns:
        summary = turn.finalizer_status
        if summary is None or summary.phase in ("planned", "skipped"):
            continue
        considered.append(turn)
    newest_success = -1
    for index, turn in enumerate(considered):
        summary = turn.finalizer_status
        if (
            summary is not None
            and summary.phase == "settled"
            and summary.status == "success"
        ):
            newest_success = index
    considered = considered[newest_success + 1 :]
    if not considered:
        return FinalizerRowState()
    rows: list[tuple[str, str | None, str | None, str | None]] = []
    for turn in considered:
        rows.extend(_member_candidates(turn))
    if not any(_CHIP_SEVERITY.get(row[0], 0) > 0 for row in rows):
        return FinalizerRowState()
    best_key = max(
        (row[0] for row in rows),
        key=lambda key: _CHIP_SEVERITY.get(key, 0),
    )
    winners = [row for row in rows if row[0] == best_key]
    _, instance_id, op, step = winners[-1]
    text = _chip_text(best_key, instance_id or "", op, step)
    if len(considered) > 1:
        text += f" · {len(winners)} of {len(considered)} runs"
    is_finalizing = container.display_status == "RUNNING" and any(
        turn.finalizer_status is not None
        and turn.finalizer_status.phase in ACTIVE_PHASES
        for turn in considered
    )
    return FinalizerRowState(
        is_finalizing=is_finalizing,
        chip_text=text,
        chip_style=_chip_style(best_key),
    )


def finalizer_header_chip(agent: Agent) -> tuple[str, str] | None:
    """Return the identity-header activity override while FINALIZING.

    ``⊛ finalizing · <id> · <label>`` (or ``⊛ declaration``); None otherwise.
    Call sites fall back to the existing activity chip.
    """
    summary = agent.finalizer_status
    if summary is None or summary.phase not in ACTIVE_PHASES:
        return None
    if summary.phase == "declaring":
        return (
            f"{FINAL_GLYPH} declaration",
            f"bold {STATE_STYLES['declaration'].color}",
        )
    for instance in summary.instances:
        if (instance.status or "") in ("running", "waiting"):
            label = instance.step or instance.op
            text = f"{FINAL_GLYPH} finalizing · {instance.id}"
            if label:
                text += f" · {label}"
            return (text, f"bold {STATE_STYLES['running'].color}")
    first = summary.instances[0] if summary.instances else None
    if first is not None:
        return (
            f"{FINAL_GLYPH} finalizing · {first.id}",
            f"bold {STATE_STYLES['running'].color}",
        )
    return (f"{FINAL_GLYPH} finalizing", f"bold {STATE_STYLES['running'].color}")


__all__ = [
    "ACTIVE_PHASES",
    "FinalizerRowState",
    "finalizer_header_chip",
    "finalizer_row_state",
    "finalizer_summary_token",
    "session_finalizer_row_state",
]
