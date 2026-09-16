"""Host adjudication for agent-side gate-creation intent markers."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from sase.agent.gate_intent import (
    GateIntent,
    atomic_write_json,
    discard_gate_intents,
    gate_intent_paths,
    list_gate_intents,
)
from sase.agent.pending_handoff import has_pending_handoff
from sase.core.process_identity import process_identity_matches
from sase.llm_provider.types import LLMInvocationError

GATE_INTENT_GRACE_SECONDS = 60.0
GATE_INTENT_LOST_EVIDENCE = "gate_intent_lost.json"


class GateIntentLostError(LLMInvocationError):
    """Raised when an agent-side gate intent was not handed off."""

    def __init__(
        self,
        intent: GateIntent,
        *,
        evidence_path: Path,
        pid_alive: bool,
        cause: BaseException | None = None,
    ) -> None:
        self.kind = intent.kind
        self.request_id = intent.request_id
        self.pid = intent.pid
        self.source = intent.source
        self.evidence_path = evidence_path
        message = _gate_intent_lost_message(
            intent,
            evidence_path=evidence_path,
            pid_alive=pid_alive,
            cause=cause,
        )
        super().__init__(message)


def raise_if_gate_intent_lost(
    artifacts_dir: str | None,
    *,
    cause: BaseException | None = None,
) -> None:
    """Raise when ``artifacts_dir`` contains an unresolved gate intent."""
    if not artifacts_dir:
        return
    if not gate_intent_paths(artifacts_dir):
        return
    intents = list_gate_intents(artifacts_dir)
    if not intents or _runner_was_killed():
        return
    if has_pending_handoff(artifacts_dir):
        discard_gate_intents(artifacts_dir)
        return

    for intent in list(intents):
        if _intent_pid_alive(intent):
            _wait_for_intent_resolution(artifacts_dir, intent)
            if _runner_was_killed():
                return
            if has_pending_handoff(artifacts_dir):
                discard_gate_intents(artifacts_dir)
                return
            intents = list_gate_intents(artifacts_dir)
            if not any(current.path == intent.path for current in intents):
                continue

    if has_pending_handoff(artifacts_dir):
        discard_gate_intents(artifacts_dir)
        return
    intents = list_gate_intents(artifacts_dir)
    if not intents:
        return

    evidence_path = _write_lost_evidence(artifacts_dir, intents)
    first = intents[0]
    lost = GateIntentLostError(
        first,
        evidence_path=evidence_path,
        pid_alive=_intent_pid_alive(first),
        cause=cause,
    )
    if cause is not None:
        raise lost from cause
    raise lost


def gate_intent_lost_error_for(
    exc: Exception,
    artifacts_dir: str | None,
) -> Exception:
    """Return ``exc`` or a chained lost-intent error for ``artifacts_dir``."""
    try:
        raise_if_gate_intent_lost(artifacts_dir, cause=exc)
    except GateIntentLostError as lost:
        return lost
    return exc


def find_gate_intent_lost_error(
    exc: BaseException,
) -> GateIntentLostError | None:
    """Find a :class:`GateIntentLostError` in an exception chain."""
    seen: set[int] = set()
    pending: list[BaseException | None] = [exc]
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, GateIntentLostError):
            return current
        pending.append(current.__cause__)
        pending.append(current.__context__)
    return None


def _wait_for_intent_resolution(artifacts_dir: str, intent: GateIntent) -> None:
    deadline = time.monotonic() + GATE_INTENT_GRACE_SECONDS
    while time.monotonic() < deadline:
        if _runner_was_killed() or has_pending_handoff(artifacts_dir):
            return
        if not intent.path.exists() or not _intent_pid_alive(intent):
            return
        time.sleep(0.2)


def _write_lost_evidence(
    artifacts_dir: str,
    intents: list[GateIntent],
) -> Path:
    evidence_path = Path(artifacts_dir) / GATE_INTENT_LOST_EVIDENCE
    payload = {
        "schema_version": 1,
        "adjudicated_at": time.time(),
        "intents": [_evidence_payload(intent) for intent in intents],
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(evidence_path, payload)
    for intent in intents:
        try:
            intent.path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            pass
    return evidence_path


def _evidence_payload(intent: GateIntent) -> dict[str, Any]:
    payload = dict(intent.payload)
    if "kind" not in payload:
        payload["kind"] = intent.kind
    if "request_id" not in payload:
        payload["request_id"] = intent.request_id
    if "source" not in payload:
        payload["source"] = intent.source
    if "pid" not in payload:
        payload["pid"] = intent.pid
    if "process_identity" not in payload:
        payload["process_identity"] = intent.process_identity
    if "timestamp" not in payload:
        payload["timestamp"] = intent.timestamp
    payload["path"] = str(intent.path)
    payload["pid_alive"] = _intent_pid_alive(intent)
    if intent.corrupt:
        payload["corrupt"] = True
    return payload


def _intent_pid_alive(intent: GateIntent) -> bool:
    pid = intent.pid
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return process_identity_matches(pid, intent.process_identity)
    except OSError:
        return False
    return process_identity_matches(pid, intent.process_identity)


def _gate_intent_lost_message(
    intent: GateIntent,
    *,
    evidence_path: Path,
    pid_alive: bool,
    cause: BaseException | None,
) -> str:
    kind = intent.kind or "unknown"
    request_id = intent.request_id or "(unassigned)"
    command = "sase sudo list --all" if kind == "sudo" else "sase gate list --all"
    pid_detail = ""
    if intent.pid is not None:
        state = "still alive after grace period" if pid_alive else "exited"
        pid_detail = f" pid {intent.pid} is {state}."
    source_detail = f" Source: {intent.source}." if intent.source else ""
    member_detail = _gate_shell_member_detail(intent)
    cause_detail = f" provider error: {cause}" if cause is not None else ""
    failure = (
        "The creating process did not hand off the gate before host adjudication."
        if pid_alive
        else "The creating process exited before the gate was created or handed off."
    )
    return (
        f"gate intent lost: {kind} gate request {request_id}. {failure}"
        f"{pid_detail}{source_detail} Check `{command}` and re-run the request "
        f"in the foreground. Evidence: {evidence_path}.{member_detail}"
        f"{cause_detail}"
    )


def _gate_shell_member_detail(intent: GateIntent) -> str:
    if not intent.request_id:
        return ""
    try:
        from sase.gate_shell.store import find_gate_shell_by_gate_id

        record = find_gate_shell_by_gate_id(None, intent.request_id)
    except Exception:
        return ""
    if record is None:
        return " No gate-shell member record was found."
    return (
        " Gate-shell member record exists"
        f" in state {record.gate_state} at {record.artifacts_dir}."
    )


def _runner_was_killed() -> bool:
    try:
        from sase.axe.runner_signals import was_killed

        return was_killed()
    except Exception:
        return False


__all__ = [
    "GATE_INTENT_GRACE_SECONDS",
    "GateIntentLostError",
    "find_gate_intent_lost_error",
    "gate_intent_lost_error_for",
    "raise_if_gate_intent_lost",
]
