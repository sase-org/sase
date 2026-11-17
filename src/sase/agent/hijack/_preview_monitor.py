"""Monitor keep-work recovery facts and recorded-follow-up composition."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.hijack._preview_models import (
    HijackContinuationPrompt,
    HijackRecoveryRefusal,
)
from sase.agent.hijack._preview_values import string
from sase.core.continuation_facade import plan_continuation_budget
from sase.llm_provider.continuation_budget import normalized_decision, refusal_message
from sase.llm_provider.continuation_budget_decision import verify_projection
from sase.llm_provider.continuation_budget_projection import (
    project_prompt,
    prompt_projection,
    utf8_len,
)
from sase.llm_provider.continuation_budget_request import budget_request
from sase.llm_provider.types import LLMInvocationOptions


MONITOR_FOLLOWUP_KIND = "monitor_followup"
MISSING_FOLLOWUP_REASON = (
    "recorded monitor follow-up is missing; cannot Continue or Escalate"
)
CORRUPT_FOLLOWUP_REASON = (
    "recorded monitor follow-up is corrupt; cannot Continue or Escalate"
)
NO_NEXT_ACTION_REASON = (
    "recorded monitor follow-up has no next action; cannot Continue or Escalate"
)
NO_FOLLOWUP_MODEL_REASON = "recorded follow-up has no model selection"

RERUN_NO_DESCRIPTOR_REASON = (
    "monitor recovery descriptor is unavailable; cannot Re-run command"
)
RERUN_NO_COMMAND_REASON = "monitor command is unavailable; cannot Re-run command"
RERUN_NO_WORKSPACE_REASON = "held workspace is unavailable; cannot Re-run command"


@dataclass(frozen=True)
class _MonitorFollowupFacts:
    """Inputs the Rust monitor preview and Python composer share."""

    available: bool
    reason: str | None
    continue_target: str | None
    next_action: str | None
    descriptor: Mapping[str, Any] | None
    view_reason: str | None
    shell_reason: str | None


def monitor_followup_facts(
    record: Mapping[str, Any], artifacts_dir: str
) -> _MonitorFollowupFacts:
    """Load the custody descriptor and decide Continue/Escalate availability."""
    view_reason, shell_reason = _access_reasons(record)
    suppressed = record.get("suppressed_followup")
    if (
        not isinstance(suppressed, Mapping)
        or suppressed.get("kind") != MONITOR_FOLLOWUP_KIND
    ):
        return _MonitorFollowupFacts(
            available=False,
            reason=MISSING_FOLLOWUP_REASON,
            continue_target=None,
            next_action=None,
            descriptor=None,
            view_reason=view_reason,
            shell_reason=shell_reason,
        )
    ref = string(suppressed.get("ref"))
    if not ref:
        return _MonitorFollowupFacts(
            available=False,
            reason=MISSING_FOLLOWUP_REASON,
            continue_target=None,
            next_action=None,
            descriptor=None,
            view_reason=view_reason,
            shell_reason=shell_reason,
        )
    descriptor, error = _load_monitor_recovery_descriptor(ref)
    if descriptor is None:
        return _MonitorFollowupFacts(
            available=False,
            reason=error or CORRUPT_FOLLOWUP_REASON,
            continue_target=None,
            next_action=None,
            descriptor=None,
            view_reason=view_reason,
            shell_reason=shell_reason,
        )
    next_action, continue_target = _followup_selection(descriptor, artifacts_dir)
    if not next_action:
        return _MonitorFollowupFacts(
            available=False,
            reason=NO_NEXT_ACTION_REASON,
            continue_target=None,
            next_action=None,
            descriptor=descriptor,
            view_reason=view_reason,
            shell_reason=shell_reason,
        )
    if not continue_target:
        return _MonitorFollowupFacts(
            available=False,
            reason=NO_FOLLOWUP_MODEL_REASON,
            continue_target=None,
            next_action=next_action,
            descriptor=descriptor,
            view_reason=view_reason,
            shell_reason=shell_reason,
        )
    return _MonitorFollowupFacts(
        available=True,
        reason=None,
        continue_target=continue_target,
        next_action=next_action,
        descriptor=descriptor,
        view_reason=view_reason,
        shell_reason=shell_reason,
    )


def _load_monitor_recovery_descriptor(
    ref: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return the immutable monitor recovery descriptor, or a refusal reason."""
    path = Path(ref)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, MISSING_FOLLOWUP_REASON
    except OSError as exc:
        return None, f"recorded monitor follow-up could not be read: {exc}"
    try:
        payload = json.loads(raw)
    except ValueError:
        return None, CORRUPT_FOLLOWUP_REASON
    if not isinstance(payload, dict):
        return None, CORRUPT_FOLLOWUP_REASON
    return payload, None


def monitor_rerun_reason(record: Mapping[str, Any], artifacts_dir: str) -> str | None:
    """Return ``None`` when Re-run is available, else the disabled reason.

    Re-run needs only the immutable command descriptor and the held claim;
    a missing or corrupt follow-up does not block it. The descriptor is the
    same immutable record custody persists, so duplicate and crash
    reconciliation can re-resolve the exact command, cwd, and workspace.
    """
    suppressed = record.get("suppressed_followup")
    if (
        not isinstance(suppressed, Mapping)
        or suppressed.get("kind") != MONITOR_FOLLOWUP_KIND
    ):
        return RERUN_NO_DESCRIPTOR_REASON
    ref = string(suppressed.get("ref"))
    if not ref:
        return RERUN_NO_DESCRIPTOR_REASON
    descriptor, error = _load_monitor_recovery_descriptor(ref)
    if descriptor is None:
        if error in (MISSING_FOLLOWUP_REASON, CORRUPT_FOLLOWUP_REASON):
            return RERUN_NO_DESCRIPTOR_REASON
        return error or RERUN_NO_DESCRIPTOR_REASON
    command = string(descriptor.get("command"))
    if not command:
        return RERUN_NO_COMMAND_REASON
    workspace_num = record.get("workspace_num")
    if (
        not isinstance(workspace_num, int)
        or isinstance(workspace_num, bool)
        or workspace_num <= 0
    ):
        return RERUN_NO_WORKSPACE_REASON
    if not string(record.get("workspace_dir")):
        return RERUN_NO_WORKSPACE_REASON
    return None


def compose_monitor_recovery_prompt(
    record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    model_target: str | None = None,
) -> HijackContinuationPrompt:
    """Compose the recorded monitor follow-up as a keep-work recovery prompt.

    Reuses frozen-intent, result-selection, and continuation-budget machinery.
    Interrupted output and descriptor contents are labeled untrusted and bounded
    before assembly. Never launches an ordinary follow-up or host completion.
    """
    facts = monitor_followup_facts(record, artifacts_dir)
    if not facts.available or facts.descriptor is None:
        raise HijackRecoveryRefusal(
            "missing_followup",
            facts.reason or MISSING_FOLLOWUP_REASON,
        )
    selected_model = model_target or facts.continue_target
    if not selected_model:
        raise HijackRecoveryRefusal("unknown_model", NO_FOLLOWUP_MODEL_REASON)
    prompt = _compose_from_descriptor(
        record,
        facts.descriptor,
        artifacts_dir=artifacts_dir,
        next_action=facts.next_action or "",
        next_model=selected_model,
    )
    decision = _budget_decision(prompt, model_target=selected_model)
    if str(decision.get("kind") or "") == "refuse":
        raise HijackRecoveryRefusal(
            "continuation_budget_exceeded", refusal_message(decision)
        )
    return HijackContinuationPrompt(
        prompt=prompt,
        model_target=selected_model,
        context_mode="monitor",
        transcript_path=None,
        expanded_prompt_bytes=utf8_len(prompt),
        budget_decision=decision,
    )


def preserve_monitor_followup_suppression(artifacts_dir: str) -> None:
    """Keep automatic monitor delivery suppressed after explicit recovery."""
    from sase.axe.run_agent_helpers_artifacts import update_meta_field
    from sase.history.chat_fork.common import load_json_object
    from sase.notification_gates.durability import atomic_write_json

    try:
        update_meta_field(artifacts_dir, "monitor_followup_outcome", "hijacked")
    except Exception:
        pass
    done_path = Path(artifacts_dir) / "done.json"
    payload = load_json_object(done_path)
    if not isinstance(payload, dict) or not payload:
        return
    if payload.get("monitor_followup_outcome") == "hijacked":
        return
    payload["monitor_followup_outcome"] = "hijacked"
    try:
        atomic_write_json(done_path, payload)
    except OSError:
        return


def _access_reasons(record: Mapping[str, Any]) -> tuple[str | None, str | None]:
    workspace_dir = string(record.get("workspace_dir"))
    snapshots = record.get("snapshots")
    has_snapshot = isinstance(snapshots, list) and any(
        isinstance(item, Mapping) and string(item.get("reference"))
        for item in snapshots
    )
    view_reason = (
        None
        if has_snapshot or workspace_dir
        else "No recovery snapshot or held workspace is available"
    )
    shell_reason = None if workspace_dir else "No held workspace is available"
    return view_reason, shell_reason


def _followup_selection(
    descriptor: Mapping[str, Any], artifacts_dir: str
) -> tuple[str | None, str | None]:
    followup = descriptor.get("followup")
    followup = followup if isinstance(followup, Mapping) else {}
    intent = _load_frozen_intent(artifacts_dir, followup)
    from sase.monitor.followup_continuation import (
        next_action_from_intent,
        next_model_from_intent,
    )

    next_action = next_action_from_intent(intent) or string(
        followup.get("monitor_next_action")
    )
    next_model = _concrete_followup_target(
        next_model_from_intent(intent)
    ) or _concrete_followup_target(string(followup.get("monitor_next_model")))
    return next_action, next_model


def _concrete_followup_target(value: str | None) -> str | None:
    """Return *value* only when it is a concrete ``provider/model[@effort]``."""
    if not value:
        return None
    base, separator, raw_effort = value.rpartition("@")
    if not separator or raw_effort not in {
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }:
        base = value
    provider, slash, model = base.partition("/")
    if not slash or not provider or not model:
        return None
    if provider.startswith("@") or model.startswith("@"):
        return None
    return value


def _load_frozen_intent(
    artifacts_dir: str, followup: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    from sase.monitor.followup_continuation import load_frozen_monitor_intent

    meta = dict(followup)
    try:
        return load_frozen_monitor_intent(artifacts_dir, meta)
    except ValueError:
        return None


def _compose_from_descriptor(
    record: Mapping[str, Any],
    descriptor: Mapping[str, Any],
    *,
    artifacts_dir: str,
    next_action: str,
    next_model: str,
) -> str:
    from sase.monitor.followup_prompt import compose_followup_prompt
    from sase.monitor.output import OutputCapture
    from sase.monitor.result_projection import (
        LEGACY_NEXT_OUTPUT,
        build_monitor_result_wire,
        retained_log_is_truncated,
        retained_log_locator_for_monitor_result,
        retained_log_total_bytes,
        select_monitor_result_evidence,
    )
    from sase.monitor.followup_continuation import (
        load_checkpoint_body,
        load_frozen_monitor_result,
    )
    from sase.monitor.followup_output import frozen_output_text
    from sase.monitor.diagnostics import (
        diagnostic_manifest,
        read_selected_diagnostics_text,
        retained_log_metadata,
    )
    from sase.history.chat_fork.common import load_json_object

    followup = descriptor.get("followup")
    followup = followup if isinstance(followup, Mapping) else {}
    command_result = descriptor.get("command_result")
    command_result = command_result if isinstance(command_result, Mapping) else {}
    locators = descriptor.get("output_locators")
    locators = locators if isinstance(locators, Mapping) else {}
    meta = load_json_object(Path(artifacts_dir) / "agent_meta.json")
    if not isinstance(meta, Mapping):
        meta = {}
    merged = {**dict(meta), **dict(followup)}
    monitor_state = (
        string(command_result.get("state"))
        or string(merged.get("monitor_state"))
        or "stopped"
    )
    exit_code = command_result.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        exit_code = merged.get("monitor_exit_code")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            exit_code = None
    elapsed = command_result.get("elapsed_seconds")
    elapsed_seconds = float(elapsed) if isinstance(elapsed, (int, float)) else 0.0
    timeout = descriptor.get("timeout_seconds")
    if not isinstance(timeout, (int, float)):
        timeout = merged.get("monitor_timeout_seconds") or 0.0
    idle = descriptor.get("idle_timeout_seconds")
    if not isinstance(idle, (int, float)):
        idle = merged.get("monitor_idle_timeout_seconds") or 0.0
    command = (
        string(descriptor.get("command")) or string(merged.get("monitor_command")) or ""
    )
    cwd = string(descriptor.get("cwd")) or string(merged.get("monitor_cwd")) or ""
    monitor_id = (
        string(descriptor.get("monitor_id")) or string(merged.get("monitor_id")) or ""
    )
    next_output = (
        string(followup.get("monitor_next_output"))
        or string(descriptor.get("output_policy"))
        or LEGACY_NEXT_OUTPUT
    )
    capture = OutputCapture()
    output_path = string(locators.get("monitor_output_path"))
    if output_path:
        try:
            with Path(output_path).open("rb") as handle:
                while True:
                    chunk = handle.read(65536)
                    if not chunk:
                        break
                    capture.append_bytes(chunk)
        except OSError:
            pass
    try:
        loaded_result = load_frozen_monitor_result(artifacts_dir, dict(merged))
    except ValueError:
        loaded_result = None
    manifest = diagnostic_manifest(artifacts_dir)
    retained_log = retained_log_metadata(artifacts_dir)
    monitor_result: Mapping[str, Any]
    if loaded_result is None:
        monitor_result = build_monitor_result_wire(
            monitor_id=monitor_id,
            monitor_state=monitor_state,
            exit_code=exit_code,
            command=command,
            cwd=cwd,
            started_at=string(merged.get("run_started_at")),
            stopped_at=string(command_result.get("stopped_at"))
            or string(merged.get("stopped_at")),
            elapsed_seconds=elapsed_seconds,
            timeout_seconds=float(timeout or 0.0),
            timeout_kind=command_result.get("timeout_kind")
            or merged.get("monitor_timeout_kind"),
            starter_execution_id=string(followup.get("monitor_starter_agent"))
            or string(merged.get("parent_timestamp")),
            workspace_identity=string(descriptor.get("workspace_dir"))
            or string(record.get("workspace_dir")),
            diagnostic_manifest_ref=manifest.get("manifest_ref"),
            retained_log=retained_log,
        )
        output_text = capture.retained_text()
    else:
        monitor_result = loaded_result
        evidence_selection = select_monitor_result_evidence(
            monitor_result, next_output=next_output, diagnostic_manifest=manifest
        )
        output_text = frozen_output_text(
            artifacts_dir,
            result=monitor_result,
            selection=evidence_selection,
            fallback=capture.retained_text(),
        )
    evidence_selection = select_monitor_result_evidence(
        monitor_result, next_output=next_output, diagnostic_manifest=manifest
    )
    selected_diagnostics = read_selected_diagnostics_text(
        artifacts_dir, selection=evidence_selection, manifest=manifest
    )
    if loaded_result is not None:
        retained = monitor_result.get("retained_log")
        retained_for_prompt = dict(retained) if isinstance(retained, Mapping) else {}
        output_log_path = (
            retained_log_locator_for_monitor_result(
                monitor_result, fallback=output_path
            )
            or output_path
        )
        total_bytes = retained_log_total_bytes(
            monitor_result, fallback=capture.total_bytes
        )
        output_truncated = retained_log_is_truncated(
            monitor_result, fallback=capture.truncated
        )
    else:
        retained_for_prompt = retained_log
        output_log_path = output_path
        total_bytes = capture.total_bytes
        output_truncated = capture.truncated
    checkpoint_ref = string(followup.get("continuation_checkpoint_ref"))
    lane = string(followup.get("agent_session")) or string(record.get("session"))
    return compose_followup_prompt(
        starter_name=string(followup.get("monitor_starter_agent")),
        agent_session_name=lane,
        command=command,
        cwd=cwd,
        reason=string(merged.get("monitor_reason")) or "",
        monitor_state=monitor_state,
        exit_code=exit_code,
        started_at=string(merged.get("run_started_at")),
        stopped_at=string(command_result.get("stopped_at"))
        or string(merged.get("stopped_at")),
        elapsed_seconds=elapsed_seconds,
        timeout_seconds=float(timeout or 0.0),
        idle_timeout_seconds=float(idle or 0.0),
        timeout_kind=command_result.get("timeout_kind")
        or merged.get("monitor_timeout_kind"),
        monitor_id=monitor_id,
        output_text=output_text,
        tail_lines=int(merged.get("monitor_tail_lines") or 200),
        total_bytes=total_bytes,
        output_truncated=output_truncated,
        next_action=next_action,
        next_output=next_output,
        output_log_path=output_log_path,
        model=None,
        reasoning_effort=None,
        next_model=next_model,
        diagnostic_manifest=manifest,
        retained_log_metadata=retained_for_prompt,
        evidence_selection=evidence_selection,
        selected_diagnostics_text=selected_diagnostics.text,
        starter_execution_id=string(followup.get("monitor_starter_agent")),
        workspace_identity=string(descriptor.get("workspace_dir"))
        or string(record.get("workspace_dir")),
        monitor_result=monitor_result if loaded_result is not None else None,
        checkpoint_ref=checkpoint_ref,
        checkpoint_body=load_checkpoint_body(artifacts_dir, checkpoint_ref),
        tool_run_id=string(followup.get("monitor_tool_run_id")),
        host_completion_status=string(followup.get("monitor_host_completion_status")),
        host_completion_reason=string(followup.get("monitor_host_completion_reason")),
        host_completion_reasons=_string_list(
            followup.get("monitor_host_completion_reasons")
        ),
        host_completion_receipt_path=None,
    )


def _string_list(value: object) -> list[str] | None:
    if isinstance(value, (list, tuple)):
        cleaned = [str(item) for item in value if str(item)]
        return cleaned or None
    if isinstance(value, str) and value:
        return [value]
    return None


def _budget_decision(prompt: str, *, model_target: str) -> dict[str, Any]:
    provider, model, effort = _split_model_target(model_target)
    projection = prompt_projection(prompt)
    request = budget_request(
        prompt,
        os.environ,
        provider_name=provider,
        model_tier="large",
        model_name=model,
        options=LLMInvocationOptions(reasoning_effort=effort),
        projection=projection,
    )
    decision = normalized_decision(plan_continuation_budget(request))
    projected = project_prompt(prompt, decision, projection)
    return verify_projection(decision, projected)


def _split_model_target(value: str) -> tuple[str, str, str | None]:
    base, separator, raw_effort = value.rpartition("@")
    effort: str | None = raw_effort
    if not separator or effort not in {
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }:
        base, effort = value, None
    provider, slash, model = base.partition("/")
    if not slash or not provider or not model:
        raise HijackRecoveryRefusal(
            "invalid_model_target",
            f"Recovery target must be concrete provider/model: {value}",
        )
    return provider, model, effort


__all__ = [
    "MONITOR_FOLLOWUP_KIND",
    "RERUN_NO_COMMAND_REASON",
    "RERUN_NO_DESCRIPTOR_REASON",
    "RERUN_NO_WORKSPACE_REASON",
    "compose_monitor_recovery_prompt",
    "monitor_followup_facts",
    "monitor_rerun_reason",
    "preserve_monitor_followup_suppression",
]
