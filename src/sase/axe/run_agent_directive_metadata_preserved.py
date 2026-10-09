"""Preserved and epic-work metadata for run-agent directives."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from typing import Any, TYPE_CHECKING

from sase.axe._run_agent_directive_metadata_shared import (
    invalid_queue_weight_message,
)
from sase.axe.run_agent_directive_metadata_inputs import (
    EPIC_WORK_ENV_METADATA_NAMES,
)
from sase.bead.work import SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV
from sase.core.runner_slots import valid_queue_weight
from sase.plan_chain import (
    AGENT_SESSION_KEY,
    AGENT_SESSION_PARALLEL_KEY,
    AGENT_SESSION_ROLE_KEY,
    agent_session_parallel_value,
    agent_session_role_value,
    agent_session_value,
)

if TYPE_CHECKING:
    from sase.agent.agent_session_attach import AgentSessionAttachLaunchPlan


def preserved_agent_metadata(artifacts_dir: str) -> dict[str, Any]:
    """Preserve durable launch metadata across a runner re-exec."""
    try:
        with open(
            os.path.join(artifacts_dir, "agent_meta.json"), encoding="utf-8"
        ) as f:
            existing_meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(existing_meta, dict):
        return {}
    preserved: dict[str, Any] = {}
    for key in (
        "wait_completed_at",
        "sdd_plan_path",
        "epic_plan_ref",
        "epic_plan_snapshot",
        "epic_bead_id",
        "phase_bead_id",
        "bead_id",
        "model",
        "llm_provider",
        "reasoning_effort",
        "model_alias",
        "model_alias_origin",
        "prompt_origin",
        "prompt_source_surface",
    ):
        value = existing_meta.get(key)
        if isinstance(value, str) and value:
            preserved[key] = value
    model_alias_trail = existing_meta.get("model_alias_trail")
    if isinstance(model_alias_trail, list) and all(
        isinstance(item, str) and item for item in model_alias_trail
    ):
        preserved["model_alias_trail"] = model_alias_trail
    model_alias_reservation = existing_meta.get("model_alias_reservation")
    if isinstance(model_alias_reservation, dict):
        preserved["model_alias_reservation"] = dict(model_alias_reservation)
    # Boot code identity and lifecycle breadcrumbs survive a refresh
    # re-exec: the refreshed pass re-extracts directives into a rebuilt
    # record, and these keys must ride along. A refreshed bootstrap already
    # overwrote them with the new image's own values before this runs.
    code_identity = existing_meta.get("code_identity")
    if isinstance(code_identity, dict):
        preserved["code_identity"] = code_identity
    booted_at = existing_meta.get("booted_at")
    if isinstance(booted_at, str) and booted_at:
        preserved["booted_at"] = booted_at
    lifecycle_phase = existing_meta.get("lifecycle_phase")
    if isinstance(lifecycle_phase, str) and lifecycle_phase:
        preserved["lifecycle_phase"] = lifecycle_phase
    lifecycle_phase_at = existing_meta.get("lifecycle_phase_at")
    if isinstance(lifecycle_phase_at, str) and lifecycle_phase_at:
        preserved["lifecycle_phase_at"] = lifecycle_phase_at
    lifecycle_phases = existing_meta.get("lifecycle_phases")
    if isinstance(lifecycle_phases, list) and all(
        isinstance(item, dict) for item in lifecycle_phases
    ):
        preserved["lifecycle_phases"] = lifecycle_phases
    batch_predecessor_context = existing_meta.get("batch_predecessor_context")
    if isinstance(batch_predecessor_context, dict):
        preserved["batch_predecessor_context"] = dict(batch_predecessor_context)
    workspace_num = existing_meta.get("workspace_num")
    if isinstance(workspace_num, int):
        preserved["workspace_num"] = workspace_num
    queue_weight = _existing_queue_weight(existing_meta, source="agent metadata")
    if queue_weight is not None:
        preserved["queue_weight"] = queue_weight
        preserved["queue_weight_explicit"] = (
            existing_meta.get("queue_weight_explicit") is True
        )
    if existing_meta.get("plan_committed") is True:
        preserved["plan_committed"] = True
    vcs_ref = existing_meta.get("vcs_ref")
    if (
        isinstance(vcs_ref, list)
        and len(vcs_ref) == 2
        and all(isinstance(item, str) and item for item in vcs_ref)
    ):
        preserved["vcs_ref"] = vcs_ref
    for key in (
        "agent_clan",
        "agent_clan_generation",
        "clan_tribe",
        "clan_summary",
    ):
        value = existing_meta.get(key)
        if isinstance(value, str) and value:
            preserved[key] = value
    tab_value = existing_meta.get("agent_tab")
    if isinstance(tab_value, str) and tab_value:
        preserved["agent_tab"] = tab_value
    tab_source = existing_meta.get("agent_tab_source")
    if tab_source in {"prompt", "moved"}:
        preserved["agent_tab_source"] = tab_source
    if agent_session_parallel_value(existing_meta) is True:
        for key in (
            AGENT_SESSION_KEY,
            AGENT_SESSION_ROLE_KEY,
            "parent_timestamp",
        ):
            value = (
                agent_session_value(existing_meta)
                if key == AGENT_SESSION_KEY
                else (
                    agent_session_role_value(existing_meta)
                    if key == AGENT_SESSION_ROLE_KEY
                    else existing_meta.get(key)
                )
            )
            if isinstance(value, str) and value:
                preserved[key] = value
        preserved[AGENT_SESSION_PARALLEL_KEY] = True
    try:
        from sase.axe.run_agent_runner_refresh import RUNNER_CODE_REFRESHED_ENV

        refreshed = os.environ.get(RUNNER_CODE_REFRESHED_ENV) == "1"
    except Exception:
        refreshed = False
    if refreshed:
        # Same-agent runner refresh re-exec: the refreshed pass rewrote the
        # prompt from the live record, so the freshly resolved record would
        # lose revision/last/digest/source. Preserve the live full record so
        # A-off then refresh then A-on restores tale. A genuinely new human
        # launch never carries the refreshed marker, so it resolves fresh.
        autonomy = existing_meta.get("autonomy")
        if isinstance(autonomy, dict) and autonomy:
            preserved["autonomy"] = dict(autonomy)
    return preserved


def epic_work_metadata_from_env() -> dict[str, Any]:
    """Consume host-only epic-work launch fields for agent metadata.

    These values describe only the current child. Popping them prevents a
    phase or land agent from accidentally attributing its own nested launches
    to the same epic role. ``SASE_BEAD_ID`` is intentionally left untouched:
    it remains the commit workflow's bead attribution.
    """
    metadata: dict[str, Any] = {}
    for env_name, meta_name in EPIC_WORK_ENV_METADATA_NAMES:
        value = os.environ.pop(env_name, "").strip()
        if value:
            metadata[meta_name] = value
    if "epic_plan_ref" in metadata:
        # Keep the overloaded field for consumers that have not adopted the
        # explicit parent relationship yet. A phase-authored handoff may later
        # replace only this compatibility value.
        metadata["sdd_plan_path"] = metadata["epic_plan_ref"]
        metadata["plan_committed"] = True
    return metadata


def consume_epic_clan_summary_script_from_env() -> str | None:
    """Consume the host-only summary script nominated for this epic member."""
    value = os.environ.pop(SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV, "").strip()
    return value or None


def epic_work_environment_from_metadata(
    agent_meta: Mapping[str, Any],
) -> dict[str, str]:
    """Reconstruct consumed epic-work launch variables from agent metadata."""
    environment: dict[str, str] = {}
    for env_name, meta_name in EPIC_WORK_ENV_METADATA_NAMES:
        value = agent_meta.get(meta_name)
        if isinstance(value, str) and value.strip():
            environment[env_name] = value
    return environment


def export_agent_tab_env(agent_tab: str | None) -> None:
    """Mirror the ``SASE_AGENT_NAME`` export for the presentation-root tab.

    A turn whose root has a named tab runs with ``SASE_AGENT_TAB=<name>`` so
    agent-initiated launches can inherit it. Turns without a stored tab pop
    the variable so a stale parent value never leaks sideways. Spawn-time
    scrubbing of ``SASE_AGENT_*`` stays correct: each child re-derives the
    variable from its own resolved tab at startup.
    """
    if agent_tab:
        os.environ["SASE_AGENT_TAB"] = agent_tab
    else:
        os.environ.pop("SASE_AGENT_TAB", None)


def session_root_tab(
    agent_session_attach_plan: AgentSessionAttachLaunchPlan,
) -> str | None:
    """Return the session root's stored tab, or None for the default tab."""
    parent_dir = agent_session_attach_plan.parent_artifacts_dir
    parent_meta_path = os.path.join(parent_dir, "agent_meta.json")
    try:
        with open(parent_meta_path, encoding="utf-8") as f:
            parent_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        parent_data = None
    if isinstance(parent_data, dict) and _is_session_root_meta(parent_data):
        value = parent_data.get("agent_tab")
        return value if isinstance(value, str) and value else None
    # Otherwise locate the root member's agent_meta.json from the attach
    # snapshot (the session's first turn, not the named parent).
    try:
        from sase.agent.agent_session_attach import agent_session_snapshot
        from sase.core.agent_identity_facade import current_owner_agent_name_key

        snapshot = agent_session_snapshot(agent_session_attach_plan.parent_project_name)
        parent_key = current_owner_agent_name_key(agent_session_attach_plan.parent_base)

        def _matches(record: Any) -> bool:
            meta = getattr(record, "agent_meta", None)
            if meta is None:
                return False
            for value in (
                getattr(meta, "agent_session", None),
                getattr(meta, "workflow_name", None),
                getattr(meta, "name", None),
            ):
                if isinstance(value, str) and value:
                    try:
                        if current_owner_agent_name_key(value) == parent_key:
                            return True
                    except Exception:  # noqa: BLE001 - best-effort lookup.
                        continue
            return False

        candidates = [
            record for record in getattr(snapshot, "records", []) if _matches(record)
        ]
        if not candidates:
            # Fall back to the attach parent's stored tab.
            if isinstance(parent_data, dict):
                value = parent_data.get("agent_tab")
                return value if isinstance(value, str) and value else None
            return None
        candidates.sort(key=lambda record: str(getattr(record, "timestamp", "")))
        root_dir = str(getattr(candidates[0], "artifact_dir", "") or "")
        if not root_dir:
            return None
        return _read_tab_from_meta_file(os.path.join(root_dir, "agent_meta.json"))
    except Exception:  # noqa: BLE001 - session tab inheritance is best-effort.
        if isinstance(parent_data, dict):
            value = parent_data.get("agent_tab")
            return value if isinstance(value, str) and value else None
        return None


def _existing_queue_weight(meta: Mapping[str, Any], *, source: str) -> float | None:
    if meta.get("queue_weight_invalid") is True:
        raise RuntimeError(
            invalid_queue_weight_message(source, meta.get("queue_weight"))
        )
    if "queue_weight" not in meta:
        return None
    queue_weight = valid_queue_weight(
        meta.get("queue_weight"),
        explicit=meta.get("queue_weight_explicit") is True,
    )
    if queue_weight is None:
        raise RuntimeError(
            invalid_queue_weight_message(source, meta.get("queue_weight"))
        )
    return queue_weight


def _read_tab_from_meta_file(meta_path: str) -> str | None:
    """Return the stored ``agent_tab`` from an ``agent_meta.json`` file."""
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("agent_tab")
    return value if isinstance(value, str) and value else None


def _is_session_root_meta(data: dict[str, Any]) -> bool:
    """Return whether an ``agent_meta.json`` payload is a session root."""
    parent_ts = data.get("parent_timestamp")
    if isinstance(parent_ts, str) and parent_ts:
        return False
    # Legacy plan-chain spelling.
    chain_parent = data.get("plan_chain_parent_timestamp")
    if isinstance(chain_parent, str) and chain_parent:
        return False
    return True
