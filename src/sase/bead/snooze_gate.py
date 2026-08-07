"""Trusted notification-gate contract for a woken snoozed task bead.

The gate a snoozed task bead's wake time raises. It is born already snoozed —
the spec declares ``presentation.snooze_until`` and the gate service creates
its notification muted and snoozed to that instant — so the wake needs no
second timer: the notification snooze machinery resurfaces the row, and the
bead is visible in the panel's Snoozed tab the whole time it sleeps.

Its shape deliberately mirrors :mod:`sase.bead.task_gate`: same payload
fields, same command wrapper, same preview renderer. Only the decisions
differ, because the question a woken bead asks ("is this still worth doing?")
is not the question a ready one asks ("who works this?").
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from sase.bead.model import CloseRecord, SnoozeRecord, TaskPlusOneEvidence
from sase.bead.snooze_duration import SnoozeDurationError, parse_snooze_request
from sase.bead.task_gate import (
    render_task_triage_preview,
    task_triage_presentation_note,
)
from sase.bead_time_presentation import bead_instant_label
from sase.notification_gates.entrypoints import gate_command_entrypoint
from sase.notification_gates.models import GateError

BeadSnoozeAction = Literal["close", "ready", "snooze"]

BEAD_SNOOZE_KIND = "bead_snooze"
BEAD_SNOOZE_CONTINUATION_MODE = "bead_snooze"
BEAD_SNOOZE_QUERY = "close OR ready OR snooze"
BEAD_SNOOZE_CLOSE_OPTION_ID: BeadSnoozeAction = "close"
BEAD_SNOOZE_READY_OPTION_ID: BeadSnoozeAction = "ready"
BEAD_SNOOZE_SNOOZE_OPTION_ID: BeadSnoozeAction = "snooze"
BEAD_SNOOZE_OPTION_IDS: tuple[BeadSnoozeAction, ...] = (
    BEAD_SNOOZE_CLOSE_OPTION_ID,
    BEAD_SNOOZE_READY_OPTION_ID,
    BEAD_SNOOZE_SNOOZE_OPTION_ID,
)
BEAD_SNOOZE_PRIMARY_BRANCH = (BEAD_SNOOZE_CLOSE_OPTION_ID,)
BEAD_SNOOZE_PREVIEW_PATH = "task.md"
BEAD_SNOOZE_COMMAND_PATHS: dict[BeadSnoozeAction, str] = {
    option_id: f"commands/{option_id}" for option_id in BEAD_SNOOZE_OPTION_IDS
}
BEAD_SNOOZE_OPTION_FEEDBACK: dict[BeadSnoozeAction, str] = {
    BEAD_SNOOZE_CLOSE_OPTION_ID: "optional",
    BEAD_SNOOZE_READY_OPTION_ID: "optional",
    BEAD_SNOOZE_SNOOZE_OPTION_ID: "required",
}
BEAD_SNOOZE_READY_NOTE = "Woken from snooze and returned to triage."


def _bead_snooze_close_reason(until: str) -> str:
    """Return the preset close reason a bare Close accepts."""
    return (
        f"Snoozed until {bead_instant_label(until)} with no new evidence; "
        "closing as stale."
    )


@dataclass(frozen=True)
class _BeadSnoozeResponse:
    """Trusted task identity and decision translated from a persisted gate."""

    bead_id: str
    project: str
    title: str
    action: BeadSnoozeAction
    feedback: str | None
    source: str
    snooze: SnoozeRecord


def create_bead_snooze_gate(
    *,
    request_id: str,
    bead_id: str,
    project: str,
    title: str,
    snooze: SnoozeRecord,
    description: str = "",
    notes: str = "",
    created_by: str = "",
    created_at: str = "",
    size: str | None = None,
    refs: Sequence[str] = (),
    plus_one_evidence: Sequence[TaskPlusOneEvidence] = (),
    close_history: Sequence[CloseRecord] = (),
    producer: Mapping[str, Any] | None = None,
) -> Any:
    """Create one human-only wake gate for a snoozed standalone task bead."""
    from sase.notification_gates.service import create_gate

    return create_gate(
        _build_bead_snooze_gate_spec(
            request_id=request_id,
            bead_id=bead_id,
            project=project,
            title=title,
            snooze=snooze,
            description=description,
            notes=notes,
            created_by=created_by,
            created_at=created_at,
            size=size,
            refs=refs,
            plus_one_evidence=plus_one_evidence,
            close_history=close_history,
            producer=producer,
        )
    )


def _build_bead_snooze_gate_spec(
    *,
    request_id: str,
    bead_id: str,
    project: str,
    title: str,
    snooze: SnoozeRecord,
    description: str = "",
    notes: str = "",
    created_by: str = "",
    created_at: str = "",
    size: str | None = None,
    refs: Sequence[str] = (),
    plus_one_evidence: Sequence[TaskPlusOneEvidence] = (),
    close_history: Sequence[CloseRecord] = (),
    producer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the only request shape accepted by the BeadSnooze adapter."""
    from sase.bead.task_gate import close_record_payload

    empty_input_schema = {
        "type": "object",
        "additionalProperties": False,
    }
    origin_agent = created_by.strip()
    evidence = tuple(plus_one_evidence)
    count = len(evidence)
    history = tuple(close_history)
    presentation: dict[str, Any] = {
        "sender": "bead",
        "icon": "◈",
        "notes": [
            bead_snooze_presentation_note(
                bead_id,
                title,
                count,
                until=snooze.until,
                reopen_count=len(history),
            )
        ],
        "tags": ["bead", "task"],
        "panel": "beads",
        "files": [BEAD_SNOOZE_PREVIEW_PATH],
        "preview": BEAD_SNOOZE_PREVIEW_PATH,
        "snooze_until": snooze.until,
    }
    if origin_agent:
        presentation["origin_agent"] = origin_agent
    return {
        "schema_version": 3,
        "kind": BEAD_SNOOZE_KIND,
        "request_id": request_id,
        "producer": dict(producer or {}),
        "continuation_mode": BEAD_SNOOZE_CONTINUATION_MODE,
        "payload": {
            "bead_id": bead_id,
            "project": project,
            "title": title,
            "created_at": created_at,
            "size": size,
            "refs": list(refs),
            "plus_one_count": count,
            "plus_one_evidence": [
                {
                    "timestamp": item.timestamp,
                    "reporter": item.reporter,
                    "note": item.note,
                    "refs": list(item.refs),
                }
                for item in evidence
            ],
            "close_history": [close_record_payload(record) for record in history],
            "snooze": _bead_snooze_payload_record(snooze),
        },
        "presentation": presentation,
        "query": BEAD_SNOOZE_QUERY,
        "primary_branch": list(BEAD_SNOOZE_PRIMARY_BRANCH),
        "options": [
            {
                "id": option_id,
                "label": _BEAD_SNOOZE_OPTION_LABELS[option_id],
                "icon": _BEAD_SNOOZE_OPTION_ICONS[option_id],
                "command": {"argv": [BEAD_SNOOZE_COMMAND_PATHS[option_id]]},
                "input_schema": empty_input_schema,
                "result_schema": bead_snooze_result_schema(option_id),
                "feedback": BEAD_SNOOZE_OPTION_FEEDBACK[option_id],
            }
            for option_id in BEAD_SNOOZE_OPTION_IDS
        ],
        "resources": [
            *[
                {
                    "path": BEAD_SNOOZE_COMMAND_PATHS[option_id],
                    "role": "command",
                    "content": bead_snooze_gate_command_script(option_id),
                }
                for option_id in BEAD_SNOOZE_OPTION_IDS
            ],
            {
                "path": BEAD_SNOOZE_PREVIEW_PATH,
                "role": "preview",
                "content": render_bead_snooze_preview(
                    bead_id=bead_id,
                    title=title,
                    description=description,
                    notes=notes,
                    snooze=snooze,
                    created_by=origin_agent,
                    created_at=created_at,
                    size=size,
                    refs=refs,
                    plus_one_evidence=evidence,
                    close_history=history,
                ),
            },
        ],
        "auto": False,
    }


_BEAD_SNOOZE_OPTION_LABELS: dict[BeadSnoozeAction, str] = {
    BEAD_SNOOZE_CLOSE_OPTION_ID: "Close",
    BEAD_SNOOZE_READY_OPTION_ID: "Ready",
    BEAD_SNOOZE_SNOOZE_OPTION_ID: "Snooze again",
}
_BEAD_SNOOZE_OPTION_ICONS: dict[BeadSnoozeAction, str] = {
    BEAD_SNOOZE_CLOSE_OPTION_ID: "✕",
    BEAD_SNOOZE_READY_OPTION_ID: "◇",
    BEAD_SNOOZE_SNOOZE_OPTION_ID: "◈",
}


def _bead_snooze_payload_record(snooze: SnoozeRecord) -> dict[str, Any]:
    """Return the payload projection of one snooze record."""
    return {
        "until": snooze.until,
        "snoozed_at": snooze.snoozed_at,
        "snoozed_by": snooze.snoozed_by,
        "plus_one_target": snooze.plus_one_target,
        "plus_one_baseline": snooze.plus_one_baseline,
        "reason": snooze.reason,
    }


def render_bead_snooze_preview(
    *,
    bead_id: str,
    title: str,
    description: str,
    notes: str,
    snooze: SnoozeRecord,
    created_by: str = "",
    created_at: str = "",
    size: str | None = None,
    refs: Sequence[str] = (),
    plus_one_evidence: Sequence[TaskPlusOneEvidence] = (),
    close_history: Sequence[CloseRecord] = (),
) -> str:
    """Render the woken task's detail, snooze block first.

    Every rendered field is a persisted absolute instant, never a recomputed
    age: gate validation reconstructs this preview byte for byte, so a
    relative time would make the gate fail validation as it aged.
    """
    return _bead_snooze_block(snooze) + render_task_triage_preview(
        bead_id=bead_id,
        title=title,
        description=description,
        notes=notes,
        created_by=created_by,
        created_at=created_at,
        size=size,
        refs=refs,
        plus_one_evidence=plus_one_evidence,
        close_history=close_history,
    )


def _bead_snooze_block(snooze: SnoozeRecord) -> str:
    """Render the callout describing who deferred this task, and until when."""
    lines = [
        f"> [!NOTE] **◈ Snoozed by `@{snooze.snoozed_by}` on "
        f"{bead_instant_label(snooze.snoozed_at)}**",
        ">",
        f"> **Wakes:** {bead_instant_label(snooze.until)}",
    ]
    if snooze.plus_one_target is not None:
        remaining = snooze.plus_ones_remaining
        lines.append(
            f"> **+1 target:** {remaining} more "
            f"({snooze.plus_one_target} total) wakes it early"
        )
    reason = snooze.reason.strip()
    if reason:
        lines.append(f"> **Reason:** {reason}")
    return "\n".join(lines) + "\n\n"


def bead_snooze_presentation_note(
    bead_id: str,
    title: str,
    count: int,
    *,
    until: str,
    reopen_count: int = 0,
) -> str:
    """Return the stable notification summary for one snooze wake gate.

    The wake time rides along as an immutable instant rather than a countdown,
    because gate validation recomputes this note and compares it with the
    persisted one; a relative time would drift and fail that comparison.
    """
    base = task_triage_presentation_note(
        bead_id, title, count, reopen_count=reopen_count
    )
    return f"{base} · ◈ {bead_instant_label(until)}"


def bead_snooze_gate_command_script(option_id: str) -> str:
    """Return the only command wrapper accepted by the BeadSnooze adapter."""
    return (
        f"#!{sys.executable}\n"
        "from sase.bead.snooze_gate import execute_bead_snooze_gate_command\n"
        f"raise SystemExit(execute_bead_snooze_gate_command({option_id!r}))\n"
    )


@gate_command_entrypoint
def execute_bead_snooze_gate_command(option_id: str) -> int:
    """Validate command input and emit one typed side-effect-free result."""
    try:
        raw_input = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"invalid command input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(raw_input, dict):
        print("bead snooze command input must be an object", file=sys.stderr)
        return 2
    if raw_input:
        print("bead snooze command input must be empty", file=sys.stderr)
        return 2
    if option_id not in BEAD_SNOOZE_OPTION_IDS:
        print(f"unsupported bead snooze option: {option_id}", file=sys.stderr)
        return 2
    print(json.dumps({"action": option_id}, sort_keys=True))
    return 0


def validate_bead_snooze_feedback(
    selected_option_ids: Sequence[str], feedback: str | None
) -> None:
    """Reject an unparsable re-snooze before the gate becomes terminal.

    The duration rides in the free-text feedback field, so a typo is the one
    input error the command wrapper cannot catch. Checking it here — before
    the response is persisted — leaves the gate pending, so a mistyped
    duration costs a retry rather than the bead's wake gate.
    """
    if BEAD_SNOOZE_SNOOZE_OPTION_ID not in selected_option_ids:
        return
    try:
        parse_snooze_request(feedback or "")
    except SnoozeDurationError as exc:
        raise GateError("invalid_snooze_duration", "feedback", str(exc)) from exc


def translate_bead_snooze_response(
    bundle_path: Path,
    response: Mapping[str, Any],
) -> _BeadSnoozeResponse:
    """Translate one persisted BeadSnooze response into trusted host input."""
    from sase.notification_gates.durability import read_json_object

    envelope = read_json_object(bundle_path / "request.json")
    if envelope.get("kind") != BEAD_SNOOZE_KIND:
        raise GateError(
            "invalid_response",
            str(bundle_path / "request.json"),
            "request is not a bead snooze gate",
        )
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise GateError(
            "invalid_response",
            "payload",
            "bead snooze request payload is missing",
        )
    bead_id, project, title = _task_identity_from_payload(payload)
    snooze = _snooze_from_payload(payload)

    raw_selected = response.get("selected_option_ids")
    if (
        not isinstance(raw_selected, list)
        or len(raw_selected) != 1
        or raw_selected[0] not in BEAD_SNOOZE_OPTION_IDS
    ):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "bead snooze response must select exactly close, ready, or snooze",
        )
    action = cast(BeadSnoozeAction, raw_selected[0])
    option_results = response.get("option_results")
    if not isinstance(option_results, list):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "bead snooze response has no option results",
        )
    result = next(
        (
            entry.get("result")
            for entry in option_results
            if isinstance(entry, Mapping) and entry.get("id") == action
        ),
        None,
    )
    if not isinstance(result, Mapping) or result.get("action") != action:
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "bead snooze response result does not match its selected action",
        )

    raw_feedback = response.get("feedback")
    feedback = (
        raw_feedback.strip()
        if isinstance(raw_feedback, str) and raw_feedback.strip()
        else None
    )
    if action == BEAD_SNOOZE_SNOOZE_OPTION_ID and feedback is None:
        raise GateError(
            "invalid_response",
            "feedback",
            "re-snoozing a bead snooze gate requires a new wake time",
        )
    source = response.get("source")
    return _BeadSnoozeResponse(
        bead_id=bead_id,
        project=project,
        title=title,
        action=action,
        feedback=feedback,
        source=source if isinstance(source, str) and source else "host",
        snooze=snooze,
    )


def close_bead_snooze(decision: _BeadSnoozeResponse) -> None:
    """Close the woken task, defaulting to the preset stale-snooze reason."""
    _require_action(decision, BEAD_SNOOZE_CLOSE_OPTION_ID)
    from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
    from sase.bead.mutation_commit import close_mutation_commit_message

    reason = decision.feedback or _bead_snooze_close_reason(decision.snooze.until)
    cwd = _resolve_bead_snooze_project_cwd(decision.project)
    with bead_store_mutation(auto_commit_bead_store, cwd=cwd) as mutation:
        mutation.project.close(
            [decision.bead_id],
            reason=reason,
            resolution="canceled",
        )
        outcome = mutation.project.last_mutation_outcome
        commit_message = close_mutation_commit_message(
            closed_ids=_outcome_ids(outcome, "closed_ids"),
            cascade_closed_ids=_outcome_ids(outcome, "cascade_closed_ids"),
            noted_ids=_outcome_ids(outcome, "noted_ids"),
        )
        if commit_message is not None:
            mutation.commit(commit_message)


def ready_bead_snooze(decision: _BeadSnoozeResponse) -> None:
    """Return the woken task to triage, clearing its snooze record.

    The ``TaskTriage`` gate is deliberately not raised here: the bead task-gate
    reconciliation owns which gate a task bead has, and raising one directly
    would give the bead two.
    """
    _require_action(decision, BEAD_SNOOZE_READY_OPTION_ID)
    from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
    from sase.bead.mutation_commit import require_mutation_commit_message

    cwd = _resolve_bead_snooze_project_cwd(decision.project)
    note = BEAD_SNOOZE_READY_NOTE
    if decision.feedback:
        note = f"{note} {decision.feedback}"
    with bead_store_mutation(auto_commit_bead_store, cwd=cwd) as mutation:
        actor = _bead_snooze_actor(mutation.project)
        mutation.project.cancel_snooze(decision.bead_id, actor=actor)
        mutation.project.append_note(decision.bead_id, note, author=actor)
        mutation.commit(
            require_mutation_commit_message("snooze_cancel", [decision.bead_id])
        )


def resnooze_bead_snooze(decision: _BeadSnoozeResponse) -> None:
    """Defer the woken task again, using the duration the human typed."""
    _require_action(decision, BEAD_SNOOZE_SNOOZE_OPTION_ID)
    from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
    from sase.bead.mutation_commit import require_mutation_commit_message

    try:
        request = parse_snooze_request(decision.feedback or "")
    except SnoozeDurationError as exc:
        raise GateError("invalid_snooze_duration", "feedback", str(exc)) from exc
    cwd = _resolve_bead_snooze_project_cwd(decision.project)
    with bead_store_mutation(auto_commit_bead_store, cwd=cwd) as mutation:
        mutation.project.snooze(
            decision.bead_id,
            until=request.until,
            actor=_bead_snooze_actor(mutation.project),
            plus_ones=request.plus_ones,
            reason=decision.snooze.reason,
        )
        mutation.commit(require_mutation_commit_message("snooze", [decision.bead_id]))


def bead_snooze_result_schema(action: BeadSnoozeAction) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["action"],
        "properties": {"action": {"const": action}},
        "additionalProperties": False,
    }


def _require_action(decision: _BeadSnoozeResponse, action: BeadSnoozeAction) -> None:
    if decision.action != action:
        raise GateError(
            "invalid_task_action",
            decision.action,
            f"bead snooze {action} helper requires the {action} action",
        )


def _bead_snooze_actor(project: Any) -> str:
    """Attribute the mutation to the answering agent, else the store owner."""
    from sase.agent.identity import discover_agent_identity

    identity = discover_agent_identity()
    return identity.name if identity is not None else str(project.owner)


def _resolve_bead_snooze_project_cwd(project: str) -> Path:
    """Resolve an explicit ProjectSpec key to its canonical primary checkout."""
    from sase.bead.task_launch import resolve_task_launch_cwd_for_project

    try:
        return resolve_task_launch_cwd_for_project(project)
    except (FileNotFoundError, ValueError) as exc:
        raise GateError(
            "invalid_task_project",
            "payload.project",
            str(exc),
        ) from exc


def _snooze_from_payload(payload: Mapping[str, Any]) -> SnoozeRecord:
    from sase.bead.snooze_codec import snooze_from_dict

    record = snooze_from_dict(payload.get("snooze"))
    if record is None:
        raise GateError(
            "invalid_task_payload",
            "payload.snooze",
            "bead snooze payload requires a snooze record",
        )
    return record


def _task_identity_from_payload(
    payload: Mapping[str, Any],
) -> tuple[str, str, str]:
    values: list[str] = []
    for field in ("bead_id", "project", "title"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GateError(
                "invalid_task_payload",
                f"payload.{field}",
                f"bead snooze payload requires {field}",
            )
        values.append(value)
    return values[0], values[1], values[2]


def _outcome_ids(outcome: Mapping[str, Any], field: str) -> list[str]:
    raw = outcome.get(field)
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw]


__all__ = [
    "BEAD_SNOOZE_CLOSE_OPTION_ID",
    "BEAD_SNOOZE_COMMAND_PATHS",
    "BEAD_SNOOZE_CONTINUATION_MODE",
    "BEAD_SNOOZE_KIND",
    "BEAD_SNOOZE_OPTION_FEEDBACK",
    "BEAD_SNOOZE_OPTION_IDS",
    "BEAD_SNOOZE_PREVIEW_PATH",
    "BEAD_SNOOZE_PRIMARY_BRANCH",
    "BEAD_SNOOZE_QUERY",
    "BEAD_SNOOZE_READY_NOTE",
    "BEAD_SNOOZE_READY_OPTION_ID",
    "BEAD_SNOOZE_SNOOZE_OPTION_ID",
    "BeadSnoozeAction",
    "bead_snooze_gate_command_script",
    "bead_snooze_presentation_note",
    "bead_snooze_result_schema",
    "close_bead_snooze",
    "create_bead_snooze_gate",
    "execute_bead_snooze_gate_command",
    "ready_bead_snooze",
    "render_bead_snooze_preview",
    "resnooze_bead_snooze",
    "translate_bead_snooze_response",
    "validate_bead_snooze_feedback",
]
