"""Claim settlement helpers shared by supervised family shell kinds."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.paths import sase_projects_dir

from .followup import FollowupLaunchResult

FollowupLauncher = Callable[..., bool | FollowupLaunchResult]
ClaimReleaser = Callable[[dict[str, Any], str | None], str | None]
UpdateMetaFieldFn = Callable[[str, str, Any], None]


@dataclass(frozen=True, slots=True)
class ShellSettlementConfig:
    """Metadata field names and states used by shell settlement."""

    next_action_field: str
    agent_field: str
    outcome_field: str
    error_field: str
    degraded_reason_field: str
    prompt_path_field: str
    lost_state: str
    stopped_state: str
    lost_followup_error: str
    degraded_outcome: str
    fallback_followup_error: str
    missing_project_error: str


def settle_shell_claim_and_followup(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    shell_state: str,
    project_name: str | None,
    config: ShellSettlementConfig,
    release_claim: ClaimReleaser,
    launch_followup: FollowupLauncher | None,
    launch_kwargs: Mapping[str, Any],
    update_meta_field: UpdateMetaFieldFn,
) -> str | None:
    """Launch or record follow-up disposition and dispose of the shell claim."""
    next_action = meta.get(config.next_action_field)
    if next_action and shell_state == config.lost_state:
        _record_followup_outcome(
            artifacts_dir,
            meta,
            config=config,
            outcome="not-launchable",
            update_meta_field=update_meta_field,
        )
        _record_followup_error(
            artifacts_dir,
            meta,
            message=config.lost_followup_error,
            config=config,
            update_meta_field=update_meta_field,
        )
        release_error = release_claim(meta, project_name)
        return release_error or config.lost_followup_error

    if next_action and shell_state != config.stopped_state:
        if project_name and launch_followup is not None:
            launch_result = _coerce_followup_result(
                launch_followup(artifacts_dir, meta, **dict(launch_kwargs)),
                meta,
                config=config,
            )
        else:
            launch_result = FollowupLaunchResult(
                launched=False,
                error=config.missing_project_error,
            )
        if launch_result.launched:
            if launch_result.degraded_reason:
                _record_followup_outcome(
                    artifacts_dir,
                    meta,
                    config=config,
                    outcome=config.degraded_outcome,
                    degraded_reason=launch_result.degraded_reason,
                    update_meta_field=update_meta_field,
                )
                release_error = release_claim(meta, project_name)
                return release_error
            _record_followup_outcome(
                artifacts_dir,
                meta,
                config=config,
                outcome="launched",
                update_meta_field=update_meta_field,
            )
            return None
        _record_followup_outcome(
            artifacts_dir,
            meta,
            config=config,
            outcome="not-launchable",
            prompt_path=launch_result.prompt_path,
            update_meta_field=update_meta_field,
        )
        release_error = release_claim(meta, project_name)
        followup_error = (
            launch_result.error
            or str(meta.get(config.error_field) or "")
            or config.fallback_followup_error
        )
        return release_error or followup_error

    return release_claim(meta, project_name)


def _coerce_followup_result(
    raw: bool | FollowupLaunchResult,
    meta: dict[str, Any],
    *,
    config: ShellSettlementConfig,
) -> FollowupLaunchResult:
    """Coerce legacy bool launchers into structured follow-up results."""
    if isinstance(raw, FollowupLaunchResult):
        return raw
    if raw:
        return FollowupLaunchResult(
            launched=True,
            agent_name=(
                str(meta[config.agent_field]) if meta.get(config.agent_field) else None
            ),
        )
    return FollowupLaunchResult(
        launched=False,
        error=str(meta.get(config.error_field) or "") or None,
        prompt_path=(
            str(meta[config.prompt_path_field])
            if meta.get(config.prompt_path_field)
            else None
        ),
    )


def _record_followup_error(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    message: str,
    config: ShellSettlementConfig,
    update_meta_field: UpdateMetaFieldFn,
) -> None:
    """Record a follow-up error field."""
    meta[config.error_field] = message
    update_meta_field(artifacts_dir, config.error_field, message)


def _record_followup_outcome(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    outcome: str,
    config: ShellSettlementConfig,
    update_meta_field: UpdateMetaFieldFn,
    degraded_reason: str | None = None,
    prompt_path: str | None = None,
) -> None:
    """Record follow-up outcome metadata."""
    meta[config.outcome_field] = outcome
    update_meta_field(artifacts_dir, config.outcome_field, outcome)
    if degraded_reason:
        meta[config.degraded_reason_field] = degraded_reason
        update_meta_field(
            artifacts_dir,
            config.degraded_reason_field,
            degraded_reason,
        )
    if prompt_path:
        meta[config.prompt_path_field] = prompt_path
        update_meta_field(artifacts_dir, config.prompt_path_field, prompt_path)


def touch_shell_refresh_pulse(project_name: str | None) -> None:
    """Nudge artifact watchers after shell metadata changes."""
    if project_name is None:
        return
    pulse_path = sase_projects_dir() / project_name / "artifacts" / ".ace_refresh_pulse"
    try:
        pulse_path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def finalize_shell_workflow_state(artifacts_dir: str) -> None:
    """Rewrite a settled shell member's workflow state to terminal status."""
    state_path = Path(artifacts_dir) / "workflow_state.json"
    try:
        with state_path.open(encoding="utf-8") as f:
            state_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(state_data, dict):
        return
    state_data["status"] = "completed"
    try:
        with state_path.open("w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2)
    except OSError:
        return
    update_agent_artifact_index_for_marker_mutation(artifacts_dir)


def project_name_from_artifacts_dir(artifacts_dir: str) -> str | None:
    """Return the project containing a shell artifacts directory."""
    try:
        relative = (
            Path(artifacts_dir)
            .expanduser()
            .resolve()
            .relative_to(sase_projects_dir().resolve())
        )
    except ValueError:
        return None
    return relative.parts[0] if relative.parts else None


__all__ = [
    "ClaimReleaser",
    "FollowupLauncher",
    "ShellSettlementConfig",
    "finalize_shell_workflow_state",
    "project_name_from_artifacts_dir",
    "settle_shell_claim_and_followup",
    "touch_shell_refresh_pulse",
]
