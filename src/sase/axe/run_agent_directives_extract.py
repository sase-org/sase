"""Directive extraction orchestration for the run agent runner.

Expands xprompt references, extracts directives (model, name, waits, clan),
resolves LLM/VCS providers, writes metadata, and claims the agent name.
Phase implementations live in the sibling ``run_agent_directives_*``
modules; this module only sequences them.
"""

from __future__ import annotations

import json
import os

from sase.axe.run_agent_directive_clans import record_clan_attributes_at_launch
from sase.axe.run_agent_directive_identity import (
    prepare_agent_name_request,
    resolve_agent_identity,
)
from sase.axe.run_agent_directive_metadata import (
    AgentMetadataInputs,
    consume_epic_clan_summary_script_from_env,
    epic_work_metadata_from_env,
    preserved_agent_metadata,
)
from sase.axe.run_agent_directives_flow import (
    LaunchModelSelection,
    WaitResolution,
    resolve_launch_model_selection,
    resolve_wait_state,
)
from sase.axe.run_agent_directives_prompt import PreparedPrompt, prepare_prompt
from sase.axe.run_agent_directives_summary import (
    ClanSummaryOutcome,
    resolve_clan_summary_outcome,
)
from sase.axe.run_agent_directives_types import AgentInfo
from sase.axe.run_agent_directives_validation import (
    PendingAgentTribeWrite,
    persist_pending_tribe_write,
    resolve_launch_tribe_directives,
    validate_agent_tab_directives,
)
from sase.axe.run_agent_markers import write_agent_meta
from sase.bead.work import SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV


def extract_directives_and_write_meta(
    prompt: str,
    workspace_dir: str,
    artifacts_dir: str,
    cl_name: str | None = None,
    *,
    workspace_num: int = 0,
    output_path: str | None = None,
    raw_resolved_prompt: str | None = None,
) -> AgentInfo:
    """Extract prompt directives and write agent_meta.json.

    Expands xprompt references, extracts directives (model, name, etc.),
    resolves LLM/VCS providers, writes metadata, and claims agent name.

    Returns AgentInfo with all extracted info.
    """
    launch_environment = dict(os.environ)
    preserved_metadata = preserved_agent_metadata(artifacts_dir)
    epic_clan_summary_script = consume_epic_clan_summary_script_from_env()
    launch_environment.pop(SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV, None)
    epic_work_metadata = epic_work_metadata_from_env()

    # Parse user-prompt frontmatter to extract local xprompts.
    from sase.agent.multi_prompt import parse_multi_prompt
    from sase.agent.names import ensure_historical_auto_name_migration

    ensure_historical_auto_name_migration()

    multi = parse_multi_prompt(prompt)
    prompt_body = "\n---\n".join(multi.segments)

    # Merge env-var-delivered local xprompts (from multi-prompt launcher)
    # with frontmatter-defined ones. Frontmatter takes precedence.
    from sase.agent.multi_prompt_macros import take_local_macros_path

    env_xprompts_path = take_local_macros_path(os.environ)
    if env_xprompts_path:
        try:
            from sase.agent.multi_prompt_launcher import deserialize_local_xprompts

            env_xprompts = deserialize_local_xprompts(env_xprompts_path)
            multi.local_xprompts = {**env_xprompts, **multi.local_xprompts}
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
        finally:
            try:
                os.unlink(env_xprompts_path)
            except OSError:
                pass

    prepared: PreparedPrompt = prepare_prompt(
        prompt_body,
        dict(multi.local_xprompts or {}),
        raw_resolved_prompt=raw_resolved_prompt,
        preserved_metadata=preserved_metadata,
    )
    directives = prepared.directives
    expanded_for_directives = prepared.expanded_for_directives
    fork_reference_prompt = prepared.fork_reference_prompt
    agent_session_attach_plan = prepared.agent_session_attach_plan
    clan_membership_plan = prepared.clan_membership_plan
    batch_predecessor_binding = prepared.batch_predecessor_binding

    directives = validate_agent_tab_directives(
        directives,
        agent_session_attach_plan=agent_session_attach_plan,
        clan_membership_plan=clan_membership_plan,
        artifacts_dir=artifacts_dir,
    )

    pending_tribe_write: PendingAgentTribeWrite | None
    directives, pending_tribe_write = resolve_launch_tribe_directives(
        directives,
        artifacts_dir=artifacts_dir,
        cl_name=cl_name,
        preserved_metadata=preserved_metadata,
    )

    from sase.llm_provider.launch_alias_overrides import (
        active_launch_alias_overrides,
        export_launch_alias_overrides,
    )

    explicit_alias_overrides = dict(directives.model_alias_overrides)
    if not explicit_alias_overrides and agent_session_attach_plan is not None:
        explicit_alias_overrides = dict(agent_session_attach_plan.model_alias_overrides)
    model_alias_overrides = dict(
        active_launch_alias_overrides(explicit_alias_overrides or None)
    )
    export_launch_alias_overrides(model_alias_overrides)

    wait_state: WaitResolution = resolve_wait_state(
        directives,
        fork_reference_prompt=fork_reference_prompt,
        batch_predecessor_binding=batch_predecessor_binding,
        agent_session_attach_plan=agent_session_attach_plan,
    )
    wait_names = wait_state.wait_names
    wait_identity_deps = wait_state.wait_identity_deps
    wait_fork_sources = wait_state.wait_fork_sources
    wait_beads = wait_state.wait_beads
    wait_hoods = wait_state.wait_hoods
    batch_predecessor_context_payload = wait_state.batch_predecessor_context_payload

    auto_dismiss = os.environ.get("SASE_AGENT_AUTO_DISMISS")
    name_request = prepare_agent_name_request(
        directives=directives,
        agent_session_attach_plan=agent_session_attach_plan,
        fork_reference_prompt=fork_reference_prompt,
        wait_names=wait_names,
        auto_dismiss=auto_dismiss,
    )

    model_selection: LaunchModelSelection = resolve_launch_model_selection(
        directives,
        preserved_metadata=preserved_metadata,
        model_alias_overrides=model_alias_overrides,
    )
    agent_model = model_selection.model
    agent_llm_provider = model_selection.llm_provider
    agent_reasoning_effort = model_selection.reasoning_effort
    agent_model_alias = model_selection.model_alias
    agent_model_alias_trail = model_selection.model_alias_trail
    agent_model_alias_origin = model_selection.model_alias_origin
    agent_model_alias_reservation = model_selection.model_alias_reservation

    from sase.vcs_provider._registry import detect_vcs

    vcs_name = detect_vcs(workspace_dir)
    if vcs_name:
        from sase.workspace_provider import get_display_name_by_vcs

        agent_vcs_provider = get_display_name_by_vcs(vcs_name)
    else:
        agent_vcs_provider = None

    from sase.agent.multi_prompt_vcs import extract_vcs_ref

    vcs_ref = extract_vcs_ref(prompt) or extract_vcs_ref(expanded_for_directives)

    metadata_inputs = AgentMetadataInputs(
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        output_path=output_path,
        bead_id=directives.bead_id,
        wait_names=wait_names,
        wait_identity_deps=wait_identity_deps,
        wait_fork_sources=wait_fork_sources,
        wait_beads=wait_beads,
        wait_hoods=wait_hoods,
        model=agent_model,
        llm_provider=agent_llm_provider,
        reasoning_effort=agent_reasoning_effort,
        model_alias=agent_model_alias,
        model_alias_trail=agent_model_alias_trail,
        model_alias_origin=agent_model_alias_origin,
        model_alias_reservation=agent_model_alias_reservation,
        model_alias_overrides=model_alias_overrides,
        vcs_provider=agent_vcs_provider,
        auto_dismiss=auto_dismiss,
        preserved=preserved_metadata,
        epic_work=epic_work_metadata,
        cl_name=cl_name,
        vcs_ref=vcs_ref,
    )
    identity = resolve_agent_identity(
        name_request,
        directives=directives,
        agent_session_attach_plan=agent_session_attach_plan,
        clan_membership_plan=clan_membership_plan,
        artifacts_dir=artifacts_dir,
        metadata_inputs=metadata_inputs,
    )
    agent_name = identity.name
    agent_tribe = identity.tribe
    clan_membership_plan = identity.clan_membership_plan
    agent_meta = identity.meta
    if batch_predecessor_context_payload is not None:
        agent_meta["batch_predecessor_context"] = batch_predecessor_context_payload

    summary_outcome: ClanSummaryOutcome = resolve_clan_summary_outcome(
        directives=directives,
        clan_membership_plan=clan_membership_plan,
        epic_clan_summary_script=epic_clan_summary_script,
        epic_work_metadata=epic_work_metadata,
        preserved_metadata=preserved_metadata,
        agent_meta=agent_meta,
        workspace_dir=workspace_dir,
        output_path=output_path,
        artifacts_dir=artifacts_dir,
        launch_environment=launch_environment,
    )
    clan_summary_resolution = summary_outcome.resolution
    explicit_summary = summary_outcome.explicit_summary
    explicit_script = summary_outcome.explicit_script

    # Write metadata after the name reservation succeeds. Summary scripts run
    # outside the allocation lock because their timeout is comparatively long.
    if agent_meta:
        write_agent_meta(artifacts_dir, agent_meta)

    if clan_membership_plan is not None:
        record_clan_attributes_at_launch(
            artifacts_dir=artifacts_dir,
            clan_membership_plan=clan_membership_plan,
            directives=directives,
            epic_clan_summary_script=epic_clan_summary_script,
            epic_work_metadata=epic_work_metadata,
            resolved_summary=explicit_summary,
            used_summary_script=explicit_script,
        )

    # Persist %id tribe= for the Agents tab's workflow identity.
    persist_pending_tribe_write(pending_tribe_write, directives.tribe)

    from sase.macro.hold_directive import HoldFields

    auto_mode = directives.auto_mode
    return AgentInfo(
        name=agent_name,
        bead_id=directives.bead_id,
        wait_names=wait_names,
        wait_identity_deps=wait_identity_deps,
        wait_fork_sources=wait_fork_sources,
        wait_beads=wait_beads,
        wait_hoods=wait_hoods,
        wait_duration=directives.wait_duration,
        wait_until=directives.wait_until,
        wait_runners=directives.wait_runners,
        queue_capacity_multiplier=directives.queue_capacity_multiplier,
        wait_priority=directives.wait_priority,
        queue_weight=float(agent_meta.get("queue_weight", 1.0)),
        queue_weight_explicit=agent_meta.get("queue_weight_explicit") is True,
        model=agent_model,
        llm_provider=agent_llm_provider,
        vcs_provider=agent_vcs_provider,
        hidden=bool(directives.hide or auto_dismiss),
        approve=auto_mode == "plan",
        plan=auto_mode in {"epic", "tale"},
        tribe=agent_tribe,
        clan_summary_resolution=clan_summary_resolution,
        meta=agent_meta,
        local_xprompts=multi.local_xprompts,
        hold=HoldFields.from_mapping(directives.hold),
    )


__all__ = ["extract_directives_and_write_meta"]
