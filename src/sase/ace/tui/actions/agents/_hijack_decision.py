"""Pure Agent Hijack decision helpers for TUI ingress."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from collections.abc import Mapping

from ...models.agent_status import DISMISSABLE_STATUSES
from ._remote_lifecycle import is_remote_fleet_agent

if TYPE_CHECKING:
    from ...models import Agent

_HIJACK_OFFER_MODES = frozenset({"immediate", "latched", "redirect"})
_HIJACK_STOP_MODES = frozenset({"immediate", "latched"})
_CHEAP_TERMINAL_STATUSES = frozenset(DISMISSABLE_STATUSES) | {
    "CONTINUED",
    "ESCALATED",
    "LOST",
}


@dataclass(frozen=True, slots=True)
class HijackDecisionView:
    """One backend hijack decision cached for a TUI row."""

    identity: tuple[object, ...]
    roster_generation: int
    occupant_name: str | None
    occupant_reason: str
    workspace_num: int | None
    decision: dict[str, Any]
    computed_at: float = 0.0

    @property
    def mode(self) -> str:
        value = self.decision.get("mode")
        return value if isinstance(value, str) and value else "refused"

    @property
    def code(self) -> str | None:
        value = self.decision.get("code")
        return value if isinstance(value, str) and value else None

    @property
    def redirect_op(self) -> str | None:
        value = self.decision.get("redirect_op")
        return value if isinstance(value, str) and value else None


def cheap_hijack_ingress_available(agent: Agent | None) -> bool:
    """Return whether the footer may offer hijack before a backend decision.

    Named procs, bulk rows, and terminal statuses hide the chip immediately.
    Remote rows stay offered (copy-command redirect). Every other row is
    optimistic, including anonymous-workflow session containers.
    """
    if agent is None:
        return False
    if getattr(agent, "is_named_proc", False):
        return False
    if getattr(agent, "is_bulk", False) or getattr(agent, "is_bulk_marked", False):
        return False
    status = getattr(agent, "status", None)
    if isinstance(status, str) and status in _CHEAP_TERMINAL_STATUSES:
        return False
    return True


def agent_can_offer_hijack(agent: Agent | None) -> bool:
    """Cheap row-local ingress check used until a backend decision arrives."""
    return cheap_hijack_ingress_available(agent)


def agent_hijack_ingress_available(agent: Agent | None) -> bool:
    """Return whether leader ingress can act locally or guide a remote user."""
    return cheap_hijack_ingress_available(agent)


def _decision_offers_ingress(decision: Mapping[str, Any] | None) -> bool:
    """Return whether `,k` and the leader footer chip should appear."""
    if not isinstance(decision, Mapping):
        return False
    mode = decision.get("mode")
    return isinstance(mode, str) and mode in _HIJACK_OFFER_MODES


def _decision_offers_stop(decision: Mapping[str, Any] | None) -> bool:
    """Return whether the kill modal may offer ``h`` Hijack instead."""
    if not isinstance(decision, Mapping):
        return False
    mode = decision.get("mode")
    return isinstance(mode, str) and mode in _HIJACK_STOP_MODES


def format_hijack_decision_toast(decision: Mapping[str, Any]) -> str:
    """Format ``code``, ``message``, and ``next_action`` for a TUI toast."""
    code = decision.get("code")
    message = decision.get("message")
    next_action = decision.get("next_action")
    parts: list[str] = []
    if isinstance(code, str) and code:
        parts.append(code)
    if isinstance(message, str) and message:
        parts.append(message)
    text = ": ".join(parts) if parts else "Hijack is not available"
    if isinstance(next_action, str) and next_action:
        text = f"{text} · {next_action}"
    return text


def row_has_pending_latch(agent: Agent | None) -> bool:
    """Return whether *agent* currently presents a durable pending latch."""
    if agent is None:
        return False
    if getattr(agent, "hijack_overlay", None) == "pending":
        return True
    record = getattr(agent, "hijack_record", None)
    return isinstance(record, dict) and record.get("state") == "latched"


def hijack_ingress_available_for_footer(app: object, agent: Agent | None) -> bool:
    """Footer chip: cached backend decision, else cheap row-local refusals.

    This helper never schedules a compute. Footer and leader refresh paths
    request a decision from one place per refresh. A durable pending latch
    keeps the chip even when eligibility still refuses the live turn.
    """
    if agent is None:
        return False
    if row_has_pending_latch(agent):
        return True
    cached = getattr(app, "_cached_hijack_decision", None)
    if callable(cached):
        view = cached(agent)
        if isinstance(view, HijackDecisionView):
            return _decision_offers_ingress(view.decision)
    return cheap_hijack_ingress_available(agent)


def kill_modal_hijack_available(app: object, agent: Agent | None) -> bool:
    """Kill-modal ``h``: cached stop modes, else a cheap local optimistic check."""
    if agent is None or is_remote_fleet_agent(agent):
        return False
    if row_has_pending_latch(agent):
        return True
    cached = getattr(app, "_cached_hijack_decision", None)
    if callable(cached):
        view = cached(agent)
        if isinstance(view, HijackDecisionView):
            return _decision_offers_stop(view.decision)
    return cheap_hijack_ingress_available(agent)


def compute_hijack_decision(
    agent: Agent,
    *,
    roster_generation: int = 0,
    deps: Any | None = None,
) -> HijackDecisionView:
    """Resolve and decide the same way ``sase agent hijack --explain`` does."""
    from sase.agent.hijack.facts import resolve_and_decide

    identity = _row_identity(agent)
    try:
        subject, decision = resolve_and_decide(agent, deps=deps)
    except Exception:
        decision = {
            "mode": "refused",
            "eligible": False,
            "code": "decision_failed",
            "message": "could not compute a hijack decision",
            "next_action": "retry, or use x to stop the row",
            "redirect_op": None,
            "adapter": None,
        }
        return HijackDecisionView(
            identity=identity,
            roster_generation=roster_generation,
            occupant_name=getattr(agent, "agent_name", None),
            occupant_reason="",
            workspace_num=getattr(agent, "workspace_num", None),
            decision=decision,
        )
    workspace_num = None
    if subject.target is not None:
        workspace_num = getattr(subject.target, "workspace_num", None)
    if not isinstance(workspace_num, int):
        workspace_num = getattr(agent, "workspace_num", None)
    occupant = subject.occupant_name
    return HijackDecisionView(
        identity=identity,
        roster_generation=roster_generation,
        occupant_name=occupant if isinstance(occupant, str) and occupant else None,
        occupant_reason=str(subject.occupant_reason or ""),
        workspace_num=workspace_num if isinstance(workspace_num, int) else None,
        decision=dict(decision),
    )


def _row_identity(agent: Agent) -> tuple[object, ...]:
    identity = getattr(agent, "identity", None)
    if isinstance(identity, tuple):
        return identity
    return (getattr(agent, "agent_name", None), id(agent))


def hijack_decision_fingerprint(
    agent: Agent, *, _seen: frozenset[int] | None = None
) -> tuple[object, ...]:
    """Return the row-local fields a hijack decision reads from *agent*.

    The roster generation is never part of this fingerprint. Container rows
    include each follow-up member's fingerprint.
    """
    marker = id(agent)
    seen = _seen or frozenset()
    if marker in seen:
        return (_row_identity(agent),)
    seen = seen | {marker}
    record = getattr(agent, "hijack_record", None)
    record_state = record.get("state") if isinstance(record, dict) else None
    record_boundary = record.get("boundary") if isinstance(record, dict) else None
    base = (
        getattr(agent, "status", None),
        getattr(agent, "pid", None),
        getattr(agent, "workspace_num", None),
        getattr(agent, "artifacts_dir", None),
        getattr(agent, "agent_session", None),
        getattr(agent, "agent_session_role", None),
        bool(getattr(agent, "agent_session_parallel", False)),
        getattr(agent, "agent_clan", None),
        getattr(agent, "agent_clan_generation", None),
        bool(getattr(agent, "is_clan_container", False)),
        bool(getattr(agent, "is_agent_session_container_row", False)),
        bool(getattr(agent, "is_imported_agent_session_container", False)),
        bool(getattr(agent, "is_remote_agent_session_container", False)),
        bool(getattr(agent, "is_named_proc", False)),
        getattr(agent, "fleet_origin_alias", None),
        getattr(agent, "hijack_overlay", None),
        bool(getattr(agent, "hijack_stop_failed", False)),
        getattr(agent, "hijack_id", None),
        bool(getattr(agent, "hijack_expired", False)),
        getattr(agent, "hijack_diff_summary", None),
        record_state,
        record_boundary,
    )
    members = getattr(agent, "followup_agents", None) or ()
    if not members:
        return base
    return (
        *base,
        tuple(hijack_decision_fingerprint(member, _seen=seen) for member in members),
    )


row_identity = _row_identity

__all__ = [
    "HijackDecisionView",
    "agent_can_offer_hijack",
    "agent_hijack_ingress_available",
    "cheap_hijack_ingress_available",
    "compute_hijack_decision",
    "format_hijack_decision_toast",
    "hijack_decision_fingerprint",
    "hijack_ingress_available_for_footer",
    "kill_modal_hijack_available",
    "row_has_pending_latch",
    "row_identity",
]
