"""``sase gate answer`` -- answer a durable gate headlessly.

This is the headless peer of the ACE gate modals: it collects a selection, the
reviewer's note, and one typed input value per selected option, then calls the
same :func:`~sase.notification_gates.executor.execute_gate_selection` every
other surface calls. The feedback-to-input rule, schema enforcement, retry
resolution, and secret redaction all live there, so answering from a script and
answering from the TUI cannot drift.

CLI value parsing lives in
:mod:`sase.notification_gates.cli_answer_inputs`, detached submission in
:mod:`sase.notification_gates.cli_answer_submit`, and answered-shell resume
in :mod:`sase.notification_gates.cli_answer_resume`; this module owns the
entrypoint, the resolve-then-execute orchestration, and the human summary.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from typing import Any, NoReturn

from rich.console import Console
from rich.text import Text

from sase.gate_turn.log import bind_gate_turn_execution_callbacks
from sase.gate_turn.settlement import settle_gate_turn
from sase.gate_turn.store import find_gate_turn_by_gate_id
from sase.notification_gates._cli_answer_shared import answered_payload
from sase.notification_gates.branches import GateBranchData
from sase.notification_gates.cli_answer_inputs import (
    build_per_option_inputs,
    read_shared_input,
    request_option_ids,
    request_option_inputs,
    request_review_revision,
    request_source,
    resolve_selection,
    retry_choice,
)
from sase.notification_gates.cli_answer_resume import resume_answered_shell
from sase.notification_gates.cli_answer_submit import (
    effective_detach,
    reject_detached_tty_options,
    submit_detached_answer,
)
from sase.notification_gates.cli_support import (
    EXIT_ERROR,
    EXIT_OK,
    GateCliError,
    JsonArgumentReader,
    emit_json,
    report_gate_error,
    resolve_gate_cli_bundle,
)
from sase.notification_gates.decision import read_current_receipt, receipt_acceptance_id
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.failure_outcome import with_follow_up_stage_tracking
from sase.notification_gates.models import GateError
from sase.ops.cli import emit_operation_result, load_request
from sase.ops.names import GATE_ANSWER


def handle_gate_answer(args: argparse.Namespace) -> NoReturn:
    """Answer one gate and emit its stable terminal projection."""
    try:
        payload = _answer(args)
    except GateCliError as exc:
        message = f"sase gate answer: {exc}"
        emit_operation_result(
            operation=GATE_ANSWER,
            success=False,
            message=message,
            error=message,
            payload={},
            args=args,
        )
        print(message, file=sys.stderr)
        sys.exit(EXIT_ERROR)
    except GateError as exc:
        message = f"gate answer failed [{exc.code}] {exc.target}: {exc}"
        emit_operation_result(
            operation=GATE_ANSWER,
            success=False,
            message=message,
            error=message,
            payload={"code": exc.code, "target": exc.target},
            args=args,
        )
        sys.exit(report_gate_error("answer", exc))
    except OSError as exc:
        message = f"sase gate answer: cannot answer gate: {exc}"
        emit_operation_result(
            operation=GATE_ANSWER,
            success=False,
            message=message,
            error=message,
            payload={},
            args=args,
        )
        print(message, file=sys.stderr)
        sys.exit(EXIT_ERROR)

    emit_operation_result(
        operation=GATE_ANSWER,
        success=True,
        message=str(payload.get("message") or "Gate answered"),
        payload=payload,
        args=args,
    )
    if bool(getattr(args, "json", False)):
        emit_json(payload)
    else:
        _print_human_summary(payload)
    sys.exit(EXIT_OK)


def _answer(args: argparse.Namespace) -> dict[str, Any]:
    """Resolve every argument against the bundle and run the executor."""
    bundle = resolve_gate_cli_bundle(str(args.kind), str(args.id))
    gate = GateBranchData.from_envelope(
        bundle.envelope, default_feedback=bundle.adapter.default_feedback
    )
    request = load_request(GATE_ANSWER, args)
    retry = request.payload.get("retry")
    retry = retry if retry in {"resume", "restart"} else retry_choice(args)
    request_options = request_option_ids(request.payload)
    requested = request_options or getattr(args, "option", None) or []
    if retry == "resume" and not requested and bundle.response_path.exists():
        stored = read_json_object(bundle.response_path).get("selected_option_ids")
        requested = [str(item) for item in stored] if isinstance(stored, list) else []
    selected = resolve_selection(gate.options, requested)
    reader = JsonArgumentReader()
    input_data = (
        request.payload.get("input_data")
        if "input_data" in request.payload
        else read_shared_input(args, reader)
    )
    option_inputs = (
        request_option_inputs(request.payload)
        if "option_inputs" in request.payload
        else build_per_option_inputs(args, selected, reader)
    )
    if input_data is not None and option_inputs is not None:
        raise GateCliError(
            "--input submits one shared value and --set/--option-input submit "
            "per-option values; use one or the other"
        )
    feedback = request.payload.get("feedback")
    feedback = (
        feedback if isinstance(feedback, str) else getattr(args, "feedback", None)
    )
    source = request_source(request.payload) or "cli"
    selected_ids = [option.id for option in selected]
    expected_review_revision = request_review_revision(request.payload)

    # A shell-backed gate is defined by the envelope's ``shell`` block (the
    # source of truth per the gate-turn design), never by whether the
    # agent-session-member lookup below happens to resolve one -- that lookup
    # goes through the artifact-index scan, which is best-effort here.
    turn_backed = isinstance(bundle.envelope.get("turn"), dict) or isinstance(
        bundle.envelope.get("shell"), dict
    )
    if retry == "resume" and turn_backed and bundle.response_path.exists():
        return resume_answered_shell(
            bundle,
            selected_ids=selected_ids,
            input_data=input_data,
            option_inputs=option_inputs,
            feedback=feedback,
            source=source,
            expected_review_revision=expected_review_revision,
        )
    if effective_detach(args, turn_backed=turn_backed):
        reject_detached_tty_options(selected)
        return submit_detached_answer(
            bundle,
            selected,
            input_data=input_data,
            feedback=feedback,
            retry=retry,
            option_inputs=option_inputs,
            source=source,
            review_revision=expected_review_revision,
        )

    gate_turn = (
        find_gate_turn_by_gate_id(None, bundle.request_id) if turn_backed else None
    )

    execution_kwargs: dict[str, Any] = (
        {}
        if gate_turn is None
        else bind_gate_turn_execution_callbacks(gate_turn.artifacts_dir).as_kwargs()
    )
    execution = execute_gate_selection(
        bundle.root,
        [option.id for option in selected],
        input_data,
        feedback=feedback,
        source=source,
        retry=retry,
        option_inputs=option_inputs,
        expected_review_revision=expected_review_revision,
        **execution_kwargs,
    )
    if gate_turn is not None:
        acceptance_id = receipt_acceptance_id(read_current_receipt(bundle.root))
        with_follow_up_stage_tracking(
            bundle.root,
            acceptance_id=acceptance_id,
            source=source,
            run=lambda: settle_gate_turn(
                gate_turn,
                gate_state="answered",
                reason="gate answered",
                resume=retry == "resume",
            ),
        )
    return answered_payload(bundle, execution.response, execution.already_completed)


def _print_human_summary(payload: Mapping[str, Any]) -> None:
    summary = Text()
    summary.append("✓", style="bold green")
    summary.append(f" Gate {payload['kind']}/{payload['request_id']} ")
    if payload.get("detached"):
        summary.append(
            f"submitted to proc {payload.get('proc_id')}", style="bold green"
        )
    else:
        summary.append(
            "was already answered" if payload["already_answered"] else "answered",
            style="bold green",
        )
    selected = payload["selected_option_ids"]
    if isinstance(selected, list) and selected:
        summary.append(" · options ", style="dim")
        summary.append(", ".join(str(value) for value in selected), style="bold")
    console = Console()
    console.print(summary, soft_wrap=True)

    option_inputs = payload["option_inputs"]
    if isinstance(option_inputs, Mapping):
        for option_id, value in sorted(option_inputs.items()):
            if not value:
                continue
            line = Text("  input ", style="dim")
            line.append(str(option_id), style="bold")
            line.append(": ", style="dim")
            line.append(_render_input(value))
            console.print(line, soft_wrap=True)

    feedback = payload["feedback"]
    if feedback is not None:
        line = Text("  feedback: ", style="dim")
        line.append(str(feedback))
        console.print(line, soft_wrap=True)
    response = Text("Response path: ", style="dim")
    response.append(str(payload["response_path"]))
    console.print(response, soft_wrap=True)


def _render_input(value: object) -> str:
    if not isinstance(value, Mapping):
        return repr(value)
    parts = []
    for key, entry in sorted(value.items()):
        if isinstance(entry, Mapping) and entry.get("$redacted") is True:
            parts.append(f"{key}=••• (redacted)")
        else:
            parts.append(f"{key}={entry!r}")
    return ", ".join(parts)


__all__ = ["handle_gate_answer"]
