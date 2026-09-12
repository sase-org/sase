"""Load, freeze, and apply versioned monitor outcome policies."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from sase.core.continuation_facade import (
    freeze_continuation_policy,
    validate_continuation_policy,
)
from sase.core.continuation_wire import (
    CONTINUATION_WIRE_SCHEMA_VERSION,
    ContinuationAction,
    ContinuationEvidencePolicy,
    JsonObject,
    MonitorOutcome,
)

from .request import StartMonitorRequest
from .result_projection import LEGACY_NEXT_OUTPUT, NEXT_OUTPUT_CHOICES

_POLICY_OUTCOMES: tuple[MonitorOutcome, ...] = (
    "completed",
    "failed",
    "timeout",
    "stopped",
    "lost",
)
_CANCELLED_OUTCOMES = frozenset({"stopped", "lost"})


def load_outcome_policy_file(path: str) -> JsonObject:
    """Parse and validate a JSON/YAML outcome-policy file without evaluating code."""

    policy_path = Path(path).expanduser()
    try:
        raw = policy_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"could not read -P/--policy file: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"-P/--policy {path!r} is not valid UTF-8: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        from sase._yaml_safe import yaml_safe_load

        try:
            payload = yaml_safe_load(text)
        except Exception as exc:
            raise ValueError(
                f"-P/--policy {path!r} is not JSON or YAML: {exc}"
            ) from exc
    if not isinstance(payload, dict):
        raise ValueError("-P/--policy file must contain a JSON/YAML object")
    try:
        return validate_continuation_policy(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"-P/--policy {path!r} is not a valid outcome policy: {exc}"
        ) from exc


def freeze_start_outcome_policy(
    request: StartMonitorRequest,
    *,
    inherited_model: str | None = None,
    inherited_effort: str | None = None,
) -> JsonObject | None:
    """Freeze every outcome branch for *request* before claim changes.

    Returns ``None`` when the start is fire-and-forget with no profile, policy,
    next action, or prepared completion intent.
    """

    if not _requires_frozen_policy(request):
        return None
    freeze_request: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "explicit_policy": request.outcome_policy,
        "profile": request.profile,
        "shared_next": request.next_action,
        "shared_model": request.next_model,
        "cli_model": request.next_model,
        "cli_evidence": request.cli_evidence,
        "inherited_model": inherited_model,
        "inherited_effort": inherited_effort,
        "prepared_completion_ref": request.completion_ref,
    }
    return freeze_continuation_policy(freeze_request)


def inherited_route_from_meta(
    meta: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    """Return the parent agent's model and effort, if recorded."""

    if not meta:
        return None, None
    return _optional_text(meta.get("model")), _optional_text(
        meta.get("reasoning_effort")
    )


def settlement_policy_decision(
    artifacts_dir: str,
    meta: Mapping[str, Any],
    monitor_state: str,
) -> JsonObject:
    """Return the frozen or reconstructed decision for *monitor_state*."""

    outcome = _settlement_outcome(monitor_state)
    frozen = _load_frozen_policy(artifacts_dir, meta)
    if frozen is not None:
        branches = frozen.get("branches")
        if isinstance(branches, Mapping):
            selected = branches.get(outcome) or branches.get("failed")
            if isinstance(selected, Mapping):
                return dict(selected)
    return _legacy_decision(meta, outcome)


def apply_frozen_branch(
    artifacts_dir: str,
    meta: dict[str, Any],
    decision: Mapping[str, Any],
) -> None:
    """Write the resolved continue-branch fields onto the monitor member."""

    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    next_action = _optional_text(decision.get("next_action"))
    if next_action:
        meta["monitor_next_action"] = next_action
        update_meta_field(artifacts_dir, "monitor_next_action", next_action)
    next_model = _followup_model(decision)
    if next_model:
        meta["monitor_next_model"] = next_model
        update_meta_field(artifacts_dir, "monitor_next_model", next_model)
    evidence = _evidence_policy(decision.get("evidence_policy"))
    if evidence:
        meta["monitor_next_output"] = evidence
        update_meta_field(artifacts_dir, "monitor_next_output", evidence)


def should_launch_frozen_followup(
    decision: Mapping[str, Any],
    monitor_state: str,
) -> bool:
    """Return whether ordinary follow-up launch should run for *decision*."""

    if monitor_state in _CANCELLED_OUTCOMES:
        return False
    action = decision.get("action")
    return action == "continue" and bool(_optional_text(decision.get("next_action")))


def frozen_action(decision: Mapping[str, Any]) -> ContinuationAction:
    """Return the resolved continuation action, defaulting to ``none``."""

    action = decision.get("action")
    if action in {"continue", "none", "complete"}:
        return action
    return "none"


def _requires_frozen_policy(request: StartMonitorRequest) -> bool:
    return bool(
        request.outcome_policy
        or request.profile
        or request.next_action
        or request.completion_ref
        or request.cli_evidence
    )


def _load_frozen_policy(
    artifacts_dir: str,
    meta: Mapping[str, Any],
) -> JsonObject | None:
    inline = meta.get("continuation_frozen_policy")
    if isinstance(inline, Mapping):
        return dict(inline)
    from sase.continuation_capture.policy import load_frozen_outcome_policy

    return load_frozen_outcome_policy(artifacts_dir)


def _legacy_decision(meta: Mapping[str, Any], outcome: MonitorOutcome) -> JsonObject:
    next_action = _optional_text(meta.get("monitor_next_action"))
    cancelled = outcome in _CANCELLED_OUTCOMES
    action: ContinuationAction = "none" if cancelled or not next_action else "continue"
    reasons = ["legacy_record"]
    if cancelled:
        reasons.append("cancelled_or_lost_outcome_does_not_auto_continue")
    evidence = _evidence_policy(meta.get("monitor_next_output")) or LEGACY_NEXT_OUTPUT
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "outcome": outcome,
        "branch": outcome if outcome != "unknown" else "failed",
        "action": action,
        "evidence_policy": evidence,
        "next_action": None if cancelled else next_action,
        "model": _optional_text(meta.get("monitor_next_model")),
        "effort": _optional_text(meta.get("reasoning_effort")),
        "completion_ref": _optional_text(meta.get("monitor_completion_ref")),
        "launchable": action == "continue" and bool(next_action),
        "reasons": reasons,
    }


def _settlement_outcome(monitor_state: str) -> MonitorOutcome:
    if monitor_state in _POLICY_OUTCOMES:
        return monitor_state  # type: ignore[return-value]
    return "unknown"


def _followup_model(decision: Mapping[str, Any]) -> str | None:
    model = _optional_text(decision.get("model"))
    effort = _optional_text(decision.get("effort"))
    if model and effort and "@" not in model:
        return f"{model}@{effort}"
    return model


def _evidence_policy(value: object) -> ContinuationEvidencePolicy | None:
    if isinstance(value, str) and value in NEXT_OUTPUT_CHOICES:
        return value  # type: ignore[return-value]
    return None


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


__all__ = [
    "apply_frozen_branch",
    "freeze_start_outcome_policy",
    "frozen_action",
    "inherited_route_from_meta",
    "load_outcome_policy_file",
    "settlement_policy_decision",
    "should_launch_frozen_followup",
]
