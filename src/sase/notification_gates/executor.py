"""Trusted host execution and terminal persistence for notification gates."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sase.gate_shell.lifecycle import (
    DISPOSITION_ACCEPTED_OWNER_LOST,
    classify_gate_lifecycle,
    collect_gate_lifecycle_facts,
)
from sase.notification_gates.attempts import (
    execute_one_option,
    open_planned_attempt,
    plan_attempt,
)
from sase.notification_gates.command_runner import validate_json_instance
from sase.notification_gates.decision import (
    ACCEPTANCE_LOCK_FILENAME,
    DECISION_RECEIPT_FILENAME,
    accept_gate_decision,
    claim_gate_decision_execution_receipt,
    read_current_receipt,
    receipt_acceptance_id,
)
from sase.notification_gates.dismissal import settle_gate_notification
from sase.notification_gates.durability import (
    atomic_write_json,
    file_lock,
    read_json_object,
)
from sase.notification_gates.executor_inputs import (
    redact_option_inputs,
    redact_secrets_in_result,
    redact_shared_input,
    resolve_option_inputs,
)
from sase.notification_gates.failure_outcome import (
    SIDE_EFFECTS_ATTEMPT_ID,
    record_failure_outcome,
    record_owner_lost_outcome,
    recorded_attempt_failure,
)
from sase.notification_gates.feedback_input import apply_feedback_input
from sase.notification_gates.failure_notifications import (
    dismiss_gate_execution_failed,
)
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.input_bounds import check_input_bounds
from sase.notification_gates.journal import (
    append_journal_event,
    current_post_response_failure,
    value_digest,
)
from sase.notification_gates.models import (
    GATE_RESPONSE_SCHEMA_VERSION,
    GateError,
    GateExecutionResult,
    GateOption,
)
from sase.notification_gates.paths import (
    CANCELLATION_FILENAME,
    RESPONSE_FILENAME,
    assert_owned_bundle,
)
from sase.notification_gates.selection import (
    normalize_feedback,
    options_from_envelope,
    resolve_selection,
)

if TYPE_CHECKING:
    from sase.bead.epic_launch import EpicLaunchOrigin

log = logging.getLogger(__name__)

#: Bound on how long ``cancel_gate`` waits for ``.acceptance.lock``. That
#: lock is only ever held briefly (validation plus one small file write),
#: never for an approved option command's full runtime (bead
#: ``bob-cli-15.2`` note #2, the original reason for this bound, back when
#: cancellation shared ``.response.lock`` with execution) -- kept as
#: defense-in-depth against a slow concurrent accept/cancel rather than as
#: the load-bearing fix it once was.
CANCEL_LOCK_TIMEOUT_SECONDS = 5.0


def execute_gate_selection(
    bundle_path: Path,
    selected_option_ids: Sequence[str],
    input_data: object | None = None,
    *,
    feedback: str | None = None,
    source: str = "host",
    retry: Literal["resume", "restart"] | None = None,
    epic_launch_origin: EpicLaunchOrigin | None = None,
    option_inputs: Mapping[str, object] | None = None,
    on_command_start: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    on_output_line: Callable[[str, str, str, str], None] | None = None,
    on_process_state: Callable[[subprocess.Popen[bytes], bool], None] | None = None,
) -> GateExecutionResult:
    """Execute a non-empty subset of one branch and persist one response.

    Submitted ids are normalized to query order before command execution and
    persistence.

    ``input_data`` and ``option_inputs`` are mutually exclusive submission
    contracts. With ``input_data`` (or neither given), every selected option
    receives the same JSON input value, as before. With ``option_inputs``, a
    mapping of selected option id to that option's own submitted JSON value,
    each selected option receives its own value and a selected option with no
    entry is judged against its own schema with ``{}``. Supplying both raises
    ``conflicting_input``; an ``option_inputs`` key outside the selection
    raises ``unknown_option``. The reviewer's note is then injected as
    ``input.feedback`` for each selected option whose schema declares that
    property. That rule lives here rather than in any surface so every
    client -- ACE, mobile, Telegram, and headless callers -- answers one
    gate the same way.

    An AND branch runs its commands one at a time, and a later member may
    fail after earlier members already took effect. Every attempt is recorded
    in the bundle's execution journal, and an identical resubmission over an
    incomplete attempt raises ``partial_attempt`` instead of silently
    re-running the completed commands; the caller then chooses ``retry``:

    - ``"resume"`` skips the options already recorded complete and replays
      their recorded results, starting at the option that failed.
    - ``"restart"`` runs the whole branch again under a fresh attempt.

    Because ``restart`` is a supported reviewer choice, **option commands in
    an AND branch must tolerate being run again** after a later member fails.
    Write them to be idempotent.
    """
    bundle_path = assert_owned_bundle(bundle_path)
    response_path = bundle_path / RESPONSE_FILENAME
    cancellation_path = bundle_path / CANCELLATION_FILENAME
    envelope, adapter = load_and_verify_bundle(bundle_path)
    options = options_from_envelope(envelope)
    selected = resolve_selection(envelope, options, selected_option_ids)
    _reject_unavailable_option_transport(adapter.kind, selected, source)
    _preflight_sudo_approval_inputs(envelope, adapter.kind, selected, option_inputs)

    # Durably accept the decision and dismiss its notification under a
    # short, separate lock before any option command, archive, or launch
    # work runs below. A conflicting resubmission is rejected here, before
    # it can run a single option command; an identical one replays the
    # original receipt. See ``decision.py`` for the full rationale.
    acceptance = accept_gate_decision(
        bundle_path,
        selected_option_ids,
        input_data,
        feedback=feedback,
        source=source,
        option_inputs=option_inputs,
    )
    acceptance_id = (
        None
        if acceptance is None
        else (
            acceptance.receipt.get("acceptance_id")
            if isinstance(acceptance.receipt.get("acceptance_id"), str)
            else None
        )
    )

    with file_lock(bundle_path / ".response.lock"):
        envelope, adapter = load_and_verify_bundle(bundle_path)
        options = options_from_envelope(envelope)
        selected = resolve_selection(envelope, options, selected_option_ids)
        if response_path.exists():
            existing_response = read_json_object(response_path)
            receipt = read_current_receipt(bundle_path)
            if retry == "resume" and (
                current_post_response_failure(
                    bundle_path, receipt, stage="side_effects"
                )
                is not None
            ):
                _resume_side_effects(
                    bundle_path,
                    adapter=adapter,
                    response=existing_response,
                    acceptance_id=receipt_acceptance_id(receipt),
                    epic_launch_origin=epic_launch_origin,
                    source=source,
                )
                existing_response = read_json_object(response_path)
                dismiss_gate_execution_failed(
                    bundle_path=bundle_path,
                    envelope=envelope,
                )
            settle_gate_notification(envelope, existing_response, source=source)
            dismiss_gate_execution_failed(
                bundle_path=bundle_path,
                envelope=envelope,
            )
            return GateExecutionResult(
                response=existing_response,
                already_completed=True,
            )
        if cancellation_path.exists():
            raise GateError(
                "gate_cancelled",
                str(cancellation_path),
                "gate is already cancelled",
            )

        normalized_input = {} if input_data is None else input_data
        with recorded_attempt_failure(
            bundle_path,
            acceptance_id=acceptance_id,
            selected=selected,
            resolved_inputs=None,
            source=source,
        ):
            normalized_feedback = normalize_feedback(selected, feedback)
        with recorded_attempt_failure(
            bundle_path,
            acceptance_id=acceptance_id,
            selected=selected,
            resolved_inputs=None,
            source=source,
        ):
            resolved_inputs = resolve_option_inputs(selected, input_data, option_inputs)
        resolved_inputs = apply_feedback_input(
            selected,
            resolved_inputs,
            normalized_feedback,
        )
        for option in selected:
            target = f"option {option.id} input"
            with recorded_attempt_failure(
                bundle_path,
                acceptance_id=acceptance_id,
                selected=(option,),
                resolved_inputs=resolved_inputs,
                source=source,
            ):
                check_input_bounds(resolved_inputs[option.id], target)
                validate_json_instance(
                    resolved_inputs[option.id], option.input_schema, target
                )
        request_hash = str(envelope["hashes"]["request"])
        input_digests = {
            option.id: value_digest(resolved_inputs[option.id]) for option in selected
        }
        attempt_plan = plan_attempt(
            bundle_path,
            request_hash=request_hash,
            selected=selected,
            input_digests=input_digests,
            retry=retry,
        )
        claimed_receipt = claim_gate_decision_execution_receipt(
            bundle_path,
            gate_id=str(envelope["request_id"]),
            request_hash=request_hash,
            acceptance_id=acceptance_id,
        )
        acceptance_id = receipt_acceptance_id(claimed_receipt)
        attempt_id, replayed = open_planned_attempt(
            bundle_path,
            attempt_plan,
            acceptance_id=acceptance_id,
        )

        option_results: list[dict[str, Any]] = []
        for option in selected:
            if option.id in replayed:
                option_results.append({"id": option.id, "result": replayed[option.id]})
                continue
            try:
                result = execute_one_option(
                    bundle_path,
                    option,
                    envelope=envelope,
                    normalized_input=resolved_inputs[option.id],
                    response_path=response_path,
                    cancellation_path=cancellation_path,
                    source=source,
                    acceptance_id=acceptance_id,
                    attempt_id=attempt_id,
                    on_command_start=on_command_start,
                    on_output_line=on_output_line,
                    on_process_state=on_process_state,
                )
            except GateError as exc:
                append_journal_event(
                    bundle_path,
                    attempt_id=attempt_id,
                    request_hash=request_hash,
                    event="option_failed",
                    option_id=option.id,
                    input_digest=input_digests[option.id],
                    code=exc.code,
                )
                raise
            recorded = redact_secrets_in_result(
                option, resolved_inputs[option.id], result
            )
            option_results.append({"id": option.id, "result": recorded})
            append_journal_event(
                bundle_path,
                attempt_id=attempt_id,
                request_hash=request_hash,
                event="option_completed",
                option_id=option.id,
                input_digest=input_digests[option.id],
                result_digest=value_digest(result),
                result=recorded,
            )

        response: dict[str, Any] = {
            "schema_version": GATE_RESPONSE_SCHEMA_VERSION,
            "request_id": envelope["request_id"],
            "kind": adapter.kind,
            "selected_option_ids": [option.id for option in selected],
            "input": redact_shared_input(selected, normalized_input),
            "option_inputs": redact_option_inputs(selected, resolved_inputs),
            "option_results": option_results,
            "feedback": normalized_feedback,
            "source": source,
            "responded_at_unix": time.time(),
        }
        append_journal_event(
            bundle_path,
            attempt_id=attempt_id,
            request_hash=request_hash,
            event="stage_started",
            stage="terminal_prepare",
            acceptance_id=acceptance_id,
        )
        try:
            adapter.prepare_terminal_response(
                bundle_path=bundle_path,
                response=response,
            )
        except GateError as exc:
            record_failure_outcome(
                bundle_path,
                acceptance_id=acceptance_id,
                attempt_id=attempt_id,
                stage="terminal_prepare",
                error=exc,
                selected=selected,
                resolved_inputs=resolved_inputs,
                source=source,
                request_hash=request_hash,
            )
            raise
        except Exception as exc:
            wrapped = GateError(
                "terminal_prepare_failed",
                adapter.kind,
                f"host terminal preparation failed: {exc}",
            )
            record_failure_outcome(
                bundle_path,
                acceptance_id=acceptance_id,
                attempt_id=attempt_id,
                stage="terminal_prepare",
                error=wrapped,
                selected=selected,
                resolved_inputs=resolved_inputs,
                source=source,
                request_hash=request_hash,
            )
            raise wrapped from exc
        try:
            atomic_write_json(response_path, response, exclusive=True)
        except FileExistsError:
            append_journal_event(
                bundle_path,
                attempt_id=attempt_id,
                request_hash=request_hash,
                event="attempt_superseded",
                acceptance_id=acceptance_id,
            )
            existing = read_json_object(response_path)
            settle_gate_notification(envelope, existing, source=source)
            return GateExecutionResult(response=existing, already_completed=True)
        append_journal_event(
            bundle_path,
            attempt_id=attempt_id,
            request_hash=request_hash,
            event="attempt_completed",
            acceptance_id=acceptance_id,
        )
        settle_gate_notification(envelope, response, source=source)
        append_journal_event(
            bundle_path,
            attempt_id=attempt_id,
            request_hash=request_hash,
            event="stage_started",
            stage="side_effects",
            acceptance_id=acceptance_id,
        )
        try:
            adapter.apply_side_effects(
                bundle_path=bundle_path,
                response=response,
                epic_launch_origin=epic_launch_origin,
            )
        except GateError as exc:
            record_failure_outcome(
                bundle_path,
                acceptance_id=acceptance_id,
                attempt_id=attempt_id,
                stage="side_effects",
                error=exc,
                selected=selected,
                resolved_inputs=resolved_inputs,
                source=source,
                request_hash=request_hash,
            )
            raise
        except Exception as exc:
            wrapped = GateError(
                "side_effect_failed",
                adapter.kind,
                f"host side effect failed: {exc}",
            )
            record_failure_outcome(
                bundle_path,
                acceptance_id=acceptance_id,
                attempt_id=attempt_id,
                stage="side_effects",
                error=wrapped,
                selected=selected,
                resolved_inputs=resolved_inputs,
                source=source,
                request_hash=request_hash,
            )
            raise wrapped from exc
        append_journal_event(
            bundle_path,
            attempt_id=attempt_id,
            request_hash=request_hash,
            event="stage_completed",
            stage="side_effects",
            acceptance_id=acceptance_id,
        )
        dismiss_gate_execution_failed(
            bundle_path=bundle_path,
            envelope=envelope,
        )
        return GateExecutionResult(response=response)


def _resume_side_effects(
    bundle_path: Path,
    *,
    adapter: Any,
    response: dict[str, Any],
    acceptance_id: str | None,
    epic_launch_origin: EpicLaunchOrigin | None,
    source: str,
) -> None:
    """Re-run only ``apply_side_effects`` for a resumed, already-answered gate.

    Design decision 8: a post-response failure offers resume only, and
    ``apply_side_effects`` itself must skip any launch whose id
    ``response.json`` already records so a resumed retry never launches a
    second successor.
    """
    request_hash = str(response.get("request_id") or "")
    append_journal_event(
        bundle_path,
        attempt_id=SIDE_EFFECTS_ATTEMPT_ID,
        request_hash=request_hash,
        event="stage_started",
        stage="side_effects",
        acceptance_id=acceptance_id,
    )
    try:
        adapter.apply_side_effects(
            bundle_path=bundle_path,
            response=response,
            epic_launch_origin=epic_launch_origin,
        )
    except GateError as exc:
        record_failure_outcome(
            bundle_path,
            acceptance_id=acceptance_id,
            attempt_id=SIDE_EFFECTS_ATTEMPT_ID,
            stage="side_effects",
            error=exc,
            source=source,
            request_hash=request_hash,
        )
        raise
    except Exception as exc:
        wrapped = GateError(
            "side_effect_failed", adapter.kind, f"host side effect failed: {exc}"
        )
        record_failure_outcome(
            bundle_path,
            acceptance_id=acceptance_id,
            attempt_id=SIDE_EFFECTS_ATTEMPT_ID,
            stage="side_effects",
            error=wrapped,
            source=source,
            request_hash=request_hash,
        )
        raise wrapped from exc
    append_journal_event(
        bundle_path,
        attempt_id=SIDE_EFFECTS_ATTEMPT_ID,
        request_hash=request_hash,
        event="stage_completed",
        stage="side_effects",
        acceptance_id=acceptance_id,
    )


def _reject_unavailable_option_transport(
    kind: str, selected: tuple[GateOption, ...], source: str
) -> None:
    """Refuse terminal-only decisions before they accept the gate."""
    tty_options = tuple(option for option in selected if option.requires_tty)
    if not tty_options:
        return
    option_ids = ", ".join(option.id for option in tty_options)
    if not has_controlling_tty():
        raise GateError(
            "tty_required",
            option_ids,
            "this gate option requires a controlling TTY; the gate remains pending",
        )
    if kind == "sudo" and source != "sudo_cli":
        raise GateError(
            "unsupported_sudo_approval",
            option_ids,
            "sudo approval must use `sase sudo answer <id>` so the reviewed "
            "manifest is sealed and executed by the sudo runner",
        )


def _preflight_sudo_approval_inputs(
    envelope: Mapping[str, Any],
    kind: str,
    selected: tuple[GateOption, ...],
    option_inputs: Mapping[str, object] | None,
) -> None:
    """Validate sudo runner receipts before accepting the gate decision."""
    if kind != "sudo" or all(option.id != "approve" for option in selected):
        return
    from sase.sudo.receipt import validate_sudo_receipt
    from sase.sudo.manifest import selected_sudo_manifest

    approve_input = (
        option_inputs.get("approve") if isinstance(option_inputs, Mapping) else None
    )
    receipt = (
        approve_input.get("receipt") if isinstance(approve_input, Mapping) else None
    )
    command_ids_value = (
        approve_input.get("command_ids") if isinstance(approve_input, Mapping) else None
    )
    if not isinstance(command_ids_value, list) or not command_ids_value:
        raise GateError(
            "invalid_sudo_selection",
            "option_inputs.approve.command_ids",
            "sudo approve requires reviewed command ids",
        )
    sudo_payload = _sudo_payload_for_preflight(envelope)
    manifest = sudo_payload["manifest"]
    _subset, command_ids, manifest_sha256 = selected_sudo_manifest(
        manifest,
        command_ids_value,
    )
    normalized = validate_sudo_receipt(
        receipt,
        manifest_sha256=manifest_sha256,
        selected_command_ids=command_ids,
    )
    for index, entry in enumerate(normalized.get("ledger", [])):
        if not isinstance(entry, Mapping):
            continue
        status = str(entry.get("status") or "")
        if status in {"authentication_failed", "cancelled", "canceled", "timeout"}:
            raise GateError(
                status,
                f"receipt.ledger[{index}]",
                "sudo runner did not approve execution; the gate remains pending",
            )


def _sudo_payload_for_preflight(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = envelope.get("payload")
    sudo_payload = payload.get("sudo") if isinstance(payload, Mapping) else None
    if not isinstance(sudo_payload, Mapping):
        raise GateError(
            "invalid_sudo_payload", "payload.sudo", "sudo payload is missing"
        )
    manifest = sudo_payload.get("manifest")
    if not isinstance(manifest, Mapping):
        raise GateError(
            "invalid_sudo_payload",
            "payload.sudo.manifest",
            "sudo manifest is missing",
        )
    if not isinstance(sudo_payload.get("manifest_sha256"), str):
        raise GateError(
            "invalid_sudo_payload",
            "payload.sudo.manifest_sha256",
            "sudo manifest hash is missing",
        )
    return sudo_payload


def has_controlling_tty() -> bool:
    """Return whether this process can open its controlling terminal."""
    try:
        fd = os.open("/dev/tty", os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return False
    os.close(fd)
    return True


def cancel_gate(
    bundle_path: Path,
    *,
    reason: str = "requester_cancelled",
    source: str = "requester",
    lock_timeout_seconds: float | None = CANCEL_LOCK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Persist a write-once cancellation if the lifecycle policy allows it.

    Waits on ``.acceptance.lock``, the same short, bounded lock acceptance
    itself uses -- never ``.response.lock``, which a running option command
    or archive/launch side effect can hold for its full runtime. A gate
    whose decision was already durably accepted can only be cancelled after
    the Rust lifecycle policy says the current execution failed or its owner
    is proven dead. Live or unknown owners keep raising ``already_answered``.
    ``lock_timeout_seconds`` bounds that wait; it raises :class:`GateError`
    (code ``lock_timeout``) on expiry instead of hanging. Pass ``None`` to
    wait indefinitely, matching the old behaviour.
    """
    bundle_path = assert_owned_bundle(bundle_path)
    with file_lock(
        bundle_path / ACCEPTANCE_LOCK_FILENAME, timeout=lock_timeout_seconds
    ):
        envelope, _adapter = load_and_verify_bundle(bundle_path)
        response_path = bundle_path / RESPONSE_FILENAME
        if response_path.exists():
            raise GateError(
                "already_answered", str(response_path), "gate already has a response"
            )
        path = bundle_path / CANCELLATION_FILENAME
        if path.exists():
            return read_json_object(path)
        receipt_path = bundle_path / DECISION_RECEIPT_FILENAME
        if receipt_path.exists():
            facts = collect_gate_lifecycle_facts(
                bundle_path,
                envelope,
                now=time.time(),
                deadline=None,
                grace_seconds=0.0,
            )
            try:
                lifecycle = classify_gate_lifecycle(facts)
            except ValueError as exc:
                raise GateError(
                    "invalid_gate_decision_receipt", str(receipt_path), str(exc)
                ) from exc
            if not bool(lifecycle.get("can_cancel")):
                raise GateError(
                    "already_answered",
                    str(receipt_path),
                    "gate decision is already accepted",
                )
            if lifecycle.get("disposition") == DISPOSITION_ACCEPTED_OWNER_LOST:
                record_owner_lost_outcome(
                    bundle_path,
                    receipt=facts.receipt,
                    source=source,
                )
        cancellation = {
            "schema_version": GATE_RESPONSE_SCHEMA_VERSION,
            "request_id": envelope["request_id"],
            "kind": envelope["kind"],
            "reason": reason,
            "source": source,
            "cancelled_at_unix": time.time(),
        }
        atomic_write_json(path, cancellation, exclusive=True)
        settle_gate_notification(envelope, {}, source=source, action="cancelled")
        dismiss_gate_execution_failed(
            bundle_path=bundle_path,
            envelope=envelope,
        )
        return cancellation


__all__ = ["cancel_gate", "execute_gate_selection", "has_controlling_tty"]
