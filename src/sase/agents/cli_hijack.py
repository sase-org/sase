"""``sase agent hijack`` — stop a stalled agent but keep its work.

Synchronous: exit 0 means the agent is HIJACKED with its workspace claim
held, 2 means refused with nothing changed, 3 means the hijack latched to
apply after the finalizer or a staged handoff settles, and 1 means the stop
failed or an error occurred. ``-j`` emits one stable JSON envelope.
"""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.text import Text

from sase.agent.hijack.facts import resolve_and_decide
from sase.agent.hijack.stop import HijackStopResult, stop_agent_for_hijack

HIJACK_JSON_SCHEMA_VERSION = 1


def handle_agents_hijack(args: argparse.Namespace) -> int:
    """Hijack the named agent, or explain/cancel/force its latch."""
    name: str = args.name
    reason = getattr(args, "reason", None)
    as_json = bool(getattr(args, "json", False))
    cancel = bool(getattr(args, "cancel", False))
    explain = bool(getattr(args, "explain", False))
    now = bool(getattr(args, "now", False))
    if sum((cancel, explain, now)) > 1:
        message = "sase agent hijack: -c/--cancel, -e/--explain, and -n/--now are mutually exclusive"
        if as_json:
            print(
                json.dumps(
                    {
                        "schema_version": HIJACK_JSON_SCHEMA_VERSION,
                        "ok": False,
                        "name": name,
                        "status": "refused",
                        "hijack_id": None,
                        "workspace_num": None,
                        "message": message,
                        "reason": "mutually_exclusive",
                        "mode": "refused",
                        "code": "mutually_exclusive",
                        "member": None,
                        "latched": False,
                        "boundary": None,
                        "next_action": "choose only one of -c, -e, or -n",
                        "redirect_op": None,
                        "adapter": None,
                        "occupant_name": None,
                        "occupant_reason": None,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(message, file=sys.stderr)
        return 2
    if explain:
        subject, decision = resolve_and_decide(name)
        if subject.target is None and subject.selected is None:
            message = f"Cannot explain agent '{name}': no agent or session resolves"
            if as_json:
                _print_json(
                    name,
                    HijackStopResult(
                        status="refused",
                        message=message,
                        exit_code=2,
                        reason="not_found",
                        decision=decision,
                        occupant_name=subject.occupant_name,
                        occupant_reason=subject.occupant_reason,
                        workspace_num=None,
                    ),
                )
            else:
                print(message, file=sys.stderr)
            return 2
        message = _explanation(subject.occupant_name or name, decision)
        result = HijackStopResult(
            status="explained",
            message=message,
            exit_code=0,
            reason=decision.get("code"),
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=(
                None if subject.target is None else subject.target.workspace_num
            ),
        )
    elif cancel:
        result = _cancel_latch(name)
    elif now:
        result = _force_latch(name)
    else:
        result = stop_agent_for_hijack(
            name, reason=reason if isinstance(reason, str) else None
        )
    if as_json:
        _print_json(name, result)
        return result.exit_code
    if result.exit_code == 0:
        style = "bold #FF5FAF" if result.status != "explained" else "bold cyan"
        Console().print(Text(result.message, style=style))
        if result.status == "explained" and result.decision is not None:
            _print_explanation_details(
                result.occupant_name,
                result.occupant_reason,
                result.decision,
            )
        return 0
    if result.exit_code == 3:
        Console().print(Text(result.message, style="bold #FF5FAF"))
        return 3
    if result.exit_code == 2:
        print(result.message, file=sys.stderr)
        return 2
    Console(stderr=True).print(Text(result.message, style="bold red"))
    return 1


def _print_json(name: str, result: HijackStopResult) -> None:
    """Emit the stable hijack envelope with additive latch fields."""
    decision = result.decision or {}
    record = result.record or {}
    latched = bool(
        result.exit_code == 3
        or result.status == "latched"
        or decision.get("mode") == "latched"
    )
    boundary = decision.get("boundary")
    if not isinstance(boundary, str) or not boundary:
        raw_boundary = record.get("boundary")
        boundary = (
            raw_boundary if isinstance(raw_boundary, str) and raw_boundary else None
        )
    print(
        json.dumps(
            {
                "schema_version": HIJACK_JSON_SCHEMA_VERSION,
                "ok": result.exit_code == 0,
                "name": name,
                "status": result.status,
                "hijack_id": result.hijack_id,
                "workspace_num": (
                    result.workspace_num
                    if result.workspace_num is not None
                    else record.get("workspace_num")
                ),
                "message": result.message,
                "reason": result.reason,
                "mode": decision.get("mode"),
                "code": decision.get("code"),
                "member": result.occupant_name,
                "latched": latched,
                "boundary": boundary,
                "boundary_outcome": record.get("boundary_outcome"),
                "suppressed_followup": record.get("suppressed_followup"),
                "next_action": decision.get("next_action") or record.get("next_action"),
                "redirect_op": decision.get("redirect_op"),
                "adapter": decision.get("adapter"),
                "occupant_name": result.occupant_name,
                "occupant_reason": result.occupant_reason,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _cancel_latch(name: str) -> HijackStopResult:
    """Cancel a pending latch; races report their observed durable state."""
    from sase.agent.hijack import latch as latch_module
    from sase.agent.hijack._stop_orchestrator_targets import compute_target_key
    from sase.agent.hijack.facts import resolve_hijack_subject

    subject = resolve_hijack_subject(name)
    target = subject.target
    if target is None:
        _subject, decision = resolve_and_decide(name)
        return HijackStopResult(
            status="refused",
            message=f"Cannot cancel hijack for agent '{name}': no latch target resolves",
            exit_code=2,
            reason="not_found",
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=None,
        )
    try:
        target_key = compute_target_key(subject, target)
    except Exception as exc:
        _subject, decision = resolve_and_decide(name)
        return HijackStopResult(
            status="error",
            message=f"Cannot cancel hijack for agent '{name}': {exc}",
            exit_code=1,
            reason="target_key_failed",
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )
    try:
        result = latch_module.cancel_latch(target_key)
    except Exception as exc:
        _subject, decision = resolve_and_decide(name)
        return HijackStopResult(
            status="error",
            message=f"Cannot cancel hijack for agent '{name}': {exc}",
            exit_code=1,
            reason="cancel_failed",
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )
    verdict = str(result.get("verdict") or "")
    record = result.get("record")
    record_dict = dict(record) if isinstance(record, dict) else None
    hijack_id = result.get("hijack_id")
    hijack_id_str = hijack_id if isinstance(hijack_id, str) else None
    _subject, decision = resolve_and_decide(name)
    if verdict == "cancelled":
        return HijackStopResult(
            status="cancelled",
            message=str(result.get("message") or "the pending hijack was cancelled"),
            exit_code=0,
            hijack_id=hijack_id_str,
            record=record_dict,
            reason="cancelled",
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )
    if verdict in {"applied", "moot"}:
        state = str((record_dict or {}).get("state") or verdict)
        return HijackStopResult(
            status=state,
            message=str(
                result.get("message")
                or f"hijack latch already {verdict}; nothing cancelled"
            ),
            exit_code=0,
            hijack_id=hijack_id_str,
            record=record_dict,
            reason=str(result.get("code") or verdict),
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )
    if verdict in {"no_latch", "refused", "ownership_uncertain"}:
        return HijackStopResult(
            status="refused",
            message=(
                f"Cannot cancel hijack for agent '{name}': "
                f"{result.get('message') or 'no pending latch'}"
            ),
            exit_code=2,
            hijack_id=hijack_id_str,
            record=record_dict,
            reason=str(result.get("code") or verdict or "no_latch"),
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )
    return HijackStopResult(
        status="error",
        message=(
            f"Cannot cancel hijack for agent '{name}': "
            f"{result.get('message') or 'cancel failed'}"
        ),
        exit_code=1,
        hijack_id=hijack_id_str,
        record=record_dict,
        reason=str(result.get("code") or "cancel_failed"),
        decision=decision,
        occupant_name=subject.occupant_name,
        occupant_reason=subject.occupant_reason,
        workspace_num=target.workspace_num,
    )


def _force_latch(name: str) -> HijackStopResult:
    """Force a pending latch after Rust's 120-second eligibility bound."""
    from sase.agent.hijack import latch as latch_module
    from sase.agent.hijack._stop_orchestrator_targets import compute_target_key
    from sase.agent.hijack.facts import resolve_hijack_subject

    subject = resolve_hijack_subject(name)
    target = subject.target
    if target is None:
        _subject, decision = resolve_and_decide(name)
        return HijackStopResult(
            status="refused",
            message=f"Cannot force hijack for agent '{name}': no latch target resolves",
            exit_code=2,
            reason="not_found",
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=None,
        )
    try:
        target_key = compute_target_key(subject, target)
    except Exception as exc:
        _subject, decision = resolve_and_decide(name)
        return HijackStopResult(
            status="error",
            message=f"Cannot force hijack for agent '{name}': {exc}",
            exit_code=1,
            reason="target_key_failed",
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )
    try:
        result = latch_module.force_hijack_latch(target_key)
    except Exception as exc:
        _subject, decision = resolve_and_decide(name)
        return HijackStopResult(
            status="error",
            message=f"Cannot force hijack for agent '{name}': {exc}",
            exit_code=1,
            reason="force_failed",
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )
    verdict = str(result.get("verdict") or "")
    record = result.get("record")
    record_dict = dict(record) if isinstance(record, dict) else None
    hijack_id = result.get("hijack_id")
    hijack_id_str = hijack_id if isinstance(hijack_id, str) else None
    _subject, decision = resolve_and_decide(name)
    if verdict == "applied":
        return HijackStopResult(
            status=str((record_dict or {}).get("state") or "held"),
            message=str(
                result.get("message") or "forced hijack applied; inspect the snapshot"
            ),
            exit_code=0,
            hijack_id=hijack_id_str,
            record=record_dict,
            reason=str(result.get("code") or "forced"),
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )
    if verdict in {"cancelled", "moot"}:
        state = str((record_dict or {}).get("state") or verdict)
        return HijackStopResult(
            status=state,
            message=str(result.get("message") or f"hijack latch already {verdict}"),
            exit_code=0,
            hijack_id=hijack_id_str,
            record=record_dict,
            reason=str(result.get("code") or verdict),
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )
    if verdict in {"no_latch", "refused", "ownership_uncertain"}:
        return HijackStopResult(
            status="refused",
            message=(
                f"Cannot force hijack for agent '{name}': "
                f"{result.get('message') or 'force was refused'}"
            ),
            exit_code=2,
            hijack_id=hijack_id_str,
            record=record_dict,
            reason=str(result.get("code") or verdict or "force_refused"),
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=target.workspace_num,
        )
    return HijackStopResult(
        status="error",
        message=(
            f"Cannot force hijack for agent '{name}': "
            f"{result.get('message') or 'force failed'}"
        ),
        exit_code=1,
        hijack_id=hijack_id_str,
        record=record_dict,
        reason=str(result.get("code") or "force_failed"),
        decision=decision,
        occupant_name=subject.occupant_name,
        occupant_reason=subject.occupant_reason,
        workspace_num=target.workspace_num,
    )


def _explanation(name: str, decision: dict[str, object]) -> str:
    mode = str(decision.get("mode") or "unknown")
    if mode == "immediate":
        return f"Hijack decision for {name}: immediate"
    code = decision.get("code")
    suffix = f" ({code})" if isinstance(code, str) and code else ""
    return f"Hijack decision for {name}: {mode}{suffix}"


def _print_explanation_details(
    occupant_name: str | None,
    occupant_reason: str | None,
    decision: dict[str, object],
) -> None:
    console = Console()
    console.print(Text(f"Occupant: {occupant_name or 'none'}", style="cyan"))
    if occupant_reason:
        console.print(Text(f"Selected because: {occupant_reason}", style="dim"))
    message = decision.get("message")
    next_action = decision.get("next_action")
    boundary = decision.get("boundary")
    if isinstance(message, str) and message:
        console.print(Text(f"Reason: {message}", style="white"))
    if isinstance(boundary, str) and boundary:
        console.print(
            Text(f"Applies after: {boundary.replace('_', ' ')}", style="white")
        )
    if isinstance(next_action, str) and next_action:
        console.print(Text(f"Next: {next_action}", style="dim cyan"))


__all__ = ["HIJACK_JSON_SCHEMA_VERSION", "handle_agents_hijack"]
