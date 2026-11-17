"""Resolve a hijack request to its occupying turn and build backend facts."""

from __future__ import annotations

import logging
from typing import Any

from sase.agent.hijack._facts_common import (
    HijackSubject,
    MemberFacts,
    capabilities,
    eligibility_schema_version,
    positive_int,
    text,
)
from sase.agent.hijack._facts_resolve import resolve_hijack_subject
from sase.agent.hijack._stop_models import HijackTarget, StopDeps

LOG = logging.getLogger(__name__)


def _build_hijack_facts(subject: HijackSubject) -> dict[str, Any]:
    """Compute the v2 decision wire from the subject's observed records."""
    member = subject.selected or subject.context
    target = subject.target
    claim = None if member is None else member.claim
    workspace_num = positive_int(getattr(claim, "workspace_num", None))
    done_outcome = None if member is None else member.done_outcome
    active_state = _active_hijack_state(target)
    is_home = (
        target.is_home if target is not None else member.is_home if member else False
    )
    has_staged, staged_kind = _staged_pending(member)
    return {
        "schema_version": eligibility_schema_version(),
        "is_local": not subject.is_remote,
        "is_remote": subject.is_remote,
        "is_bulk": subject.is_bulk,
        "is_named_proc": subject.is_named_proc,
        "is_home_mode": is_home,
        "is_clan_container": subject.is_clan_container,
        "is_session_container": subject.is_session_container,
        "live_member_count": sum(not item.settled for item in subject.members),
        "occupying_kind": (
            member.occupying_kind if member is not None and subject.selected else "none"
        ),
        "status": member.status if member is not None and subject.selected else None,
        "turn_phase": member.turn_phase
        if member is not None and subject.selected
        else None,
        "finalizer_phase": (
            member.finalizer_phase if member is not None and subject.selected else None
        ),
        "gate_state": member.gate_state
        if member is not None and subject.selected
        else None,
        "monitor_state": (
            member.monitor_state if member is not None and subject.selected else None
        ),
        "workspace_num": workspace_num,
        "has_numbered_claim": workspace_num is not None,
        "pid": member.pid if member is not None and subject.selected else None,
        "process_alive": (
            member.process_alive if member is not None and subject.selected else False
        ),
        "has_hijack_capability": bool(
            member is not None and "hijack" in capabilities(member.meta)
        ),
        "successor_attachable": bool(
            subject.selected is not None
            and (
                subject.session is not None
                or (target and target.agent_session)
                or _promotion_preconditions_hold(member)
            )
        ),
        "done_outcome": done_outcome,
        "active_hijack_state": active_state,
        "has_staged_handoff": has_staged,
        "staged_kind": staged_kind,
        "monitor_followup_pending": bool(
            member is not None
            and subject.selected is not None
            and member.monitor_followup_pending
        ),
    }


def decide(subject: HijackSubject) -> dict[str, Any]:
    """Call the Rust v2 decision and attach it to the selected target."""
    if subject.lookup_error is not None:
        return {
            "schema_version": eligibility_schema_version(),
            "mode": "refused",
            "eligible": False,
            "code": "lookup_unavailable",
            "message": f"Cannot safely resolve '{subject.requested_name}': {subject.lookup_error}",
            "next_action": "retry after the agent artifact index is available",
            "redirect_op": None,
            "adapter": None,
        }

    from sase.agent.hijack.core import agent_hijack_decide

    facts = _build_hijack_facts(subject)
    decision = agent_hijack_decide(facts)
    if (
        not subject.found
        and not subject.is_remote
        and not subject.is_bulk
        and not subject.is_named_proc
        and not subject.is_clan_container
    ):
        decision = {
            **decision,
            "mode": "refused",
            "eligible": False,
            "code": "not_found",
            "message": f"no agent or session found with name '{subject.requested_name}'",
            "next_action": "check the name with `sase agent list`",
            "redirect_op": None,
            "adapter": None,
        }
    if subject.target is not None:
        subject.target.decision = decision
    LOG.info(
        "agent_hijack_decision mode=%s code=%s member=%s requested=%s",
        decision.get("mode") or "unknown",
        decision.get("code") or "-",
        subject.occupant_name or "-",
        subject.requested_name,
    )
    return decision


def resolve_and_decide(
    name_or_row: str | Any,
    *,
    deps: StopDeps | None = None,
) -> tuple[HijackSubject, dict[str, Any]]:
    """Resolve one request and evaluate the same facts used by stop and explain."""
    subject = resolve_hijack_subject(name_or_row, deps=deps)
    return subject, decide(subject)


def _active_hijack_state(target: HijackTarget | None) -> str | None:
    if target is None:
        return None
    try:
        from sase.agent.hijack import ledger

        record = ledger.load_record_by_artifacts_dir(target.artifacts_dir)
    except (OSError, RuntimeError, ValueError):
        return None
    return text(None if record is None else record.get("state"))


def _staged_pending(member: MemberFacts | None) -> tuple[bool, str | None]:
    """Return staged-adoption facts from durable files, never from row text.

    A staged handoff is pending when its staged payload exists and no
    adoption receipt authorizes that stage. Malformed staged state counts
    as pending: the later reconciler owns it and the healer must never
    discard it as an ordinary abandoned run.
    """
    if member is None or not member.artifacts_dir:
        return False, None
    artifacts_dir = member.artifacts_dir
    try:
        from sase.agent.staged_handoff import (
            StagedHandoffError,
            read_adoption_receipt,
            read_staged_handoff,
        )
    except Exception:
        return False, None
    try:
        staged = read_staged_handoff(artifacts_dir)
    except StagedHandoffError:
        return True, None
    except Exception:
        return False, None
    if staged is None:
        return False, None
    staged_id = staged.get("staged_id") if isinstance(staged, dict) else None
    kind = staged.get("kind") if isinstance(staged, dict) else None
    kind_text = kind if isinstance(kind, str) and kind.strip() else None
    try:
        receipt = read_adoption_receipt(artifacts_dir)
    except StagedHandoffError:
        return True, kind_text
    except Exception:
        return False, None
    if receipt is None:
        return True, kind_text
    try:
        from sase.agent.staged_handoff import receipt_authorizes
    except Exception:
        return True, kind_text
    if isinstance(staged_id, str) and staged_id:
        try:
            if receipt_authorizes(receipt, staged_id):
                return False, None
        except Exception:
            return True, kind_text
        return True, kind_text
    return True, kind_text


def _promotion_preconditions_hold(member: Any | None) -> bool:
    """Return whether a sessionless predecessor could be promoted.

    Keep-work recovery promotes a bare agent into a session with the
    existing ``promote_agent_to_agent_session`` helper before attaching
    the successor. A stop is only accepted when that promotion could run,
    so Continue never follows a stop that cannot be recovered: the
    predecessor needs a readable meta with a bare name and an artifacts
    directory that could host the session container.
    """
    if member is None:
        return False
    meta = getattr(member, "meta", None)
    if not isinstance(meta, dict):
        return False
    name = meta.get("name")
    if not isinstance(name, str) or not name:
        return False
    artifacts_dir = getattr(member, "artifacts_dir", None)
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return False
    # Already sessioned members attach without promotion; bare names with
    # no session marker are promotable. A conflicting session marker that
    # is not the member's own session fails closed elsewhere.
    return True


__all__ = [
    "decide",
    "resolve_and_decide",
    "resolve_hijack_subject",
]
