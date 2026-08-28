"""Directive extraction and agent metadata setup for the run agent runner."""

import json
import os
from dataclasses import dataclass
from typing import Any, NamedTuple

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
from sase.axe.run_agent_markers import write_agent_meta
from sase.bead.work import SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV


@dataclass(frozen=True)
class ClanSummaryResolutionRequest:
    """Stable inputs for a member's post-preparation clan-summary run."""

    script: str
    clan_name: str
    clan_generation: str
    clan_tribe: str | None


class AgentInfo(NamedTuple):
    """Result of directive extraction and metadata writing."""

    name: str | None
    bead_id: str | None
    wait_names: list[str]
    wait_identity_deps: list[dict[str, str]]
    wait_fork_sources: list[dict[str, str]]
    wait_beads: list[str]
    wait_duration: float | None
    wait_until: str | None
    wait_runners: int | None
    wait_priority: int | None
    model: str | None
    llm_provider: str | None
    vcs_provider: str | None
    hidden: bool
    approve: bool
    plan: bool
    tribe: str | None
    clan_summary_resolution: ClanSummaryResolutionRequest | None
    meta: dict[str, Any]
    local_xprompts: dict[str, Any]


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

    from sase.vcs_provider._registry import detect_vcs
    from sase.xprompt import (
        LAUNCH_DEFERRED_XPROMPT_NAMES,
        process_xprompt_references,
    )
    from sase.xprompt.directives import extract_prompt_directives

    # Parse user-prompt frontmatter to extract local xprompts.
    from sase.agent.multi_prompt import parse_multi_prompt
    from sase.agent.names import ensure_historical_auto_name_migration

    ensure_historical_auto_name_migration()

    multi = parse_multi_prompt(prompt)
    prompt_body = "\n---\n".join(multi.segments)

    # Merge env-var-delivered local xprompts (from multi-prompt launcher)
    # with frontmatter-defined ones. Frontmatter takes precedence.
    env_xprompts_path = os.environ.pop("SASE_AGENT_LOCAL_XPROMPTS", None)
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

    # Expand xprompts before extracting directives so directives embedded in
    # xprompts are discovered for agent metadata.
    expanded_for_directives = process_xprompt_references(
        prompt_body,
        extra_xprompts=multi.local_xprompts or None,
        defer_xprompt_names=LAUNCH_DEFERRED_XPROMPT_NAMES,
    )
    from sase.agent.agent_name_keys import has_unresolved_agent_name_key_marker

    if has_unresolved_agent_name_key_marker(expanded_for_directives):
        raise RuntimeError(
            "Agent prompt still contains an unresolved keyed agent-name marker. "
            "The parent launch pipeline failed to resolve keyed markers before "
            "starting the runner."
        )
    _, directives = extract_prompt_directives(expanded_for_directives)
    bead_id = directives.bead_id
    if bead_id is not None:
        from sase.bead.work import SASE_BEAD_ID_ENV

        existing_bead_id = os.environ.get(SASE_BEAD_ID_ENV, "")
        if existing_bead_id.strip() and existing_bead_id != bead_id:
            raise RuntimeError(
                f"%id bead association '{bead_id}' does not match "
                f"{SASE_BEAD_ID_ENV}='{existing_bead_id}'"
            )
        os.environ[SASE_BEAD_ID_ENV] = bead_id

    fork_reference_prompt = expanded_for_directives
    if "#fork" not in fork_reference_prompt and raw_resolved_prompt:
        # Compatibility fallback for callers whose supplied catalog does not
        # retain the built-in fork reference during analysis.
        fork_reference_prompt = raw_resolved_prompt

    from sase.agent.family_attach import load_family_attach_plan_from_env

    family_attach_plan = load_family_attach_plan_from_env()
    from sase.agent.clan_membership import (
        ClanMembershipError,
        consume_clan_membership_plan_from_env,
    )

    clan_membership_plan = consume_clan_membership_plan_from_env()
    if clan_membership_plan is not None and directives.clan is None:
        raise ClanMembershipError(
            "Clan membership payload requires a %clan directive or "
            "%id(..., clan=...) keyword"
        )
    if (
        directives.tribe is not None
        and directives.clan is not None
        and not directives.clan_declared
    ):
        raise ClanMembershipError(
            "Cannot use %id(..., tribe=...) when joining a clan with "
            "%id(..., clan=...); joining a clan joins its tribe. Put tribe= "
            "on the clan's %clan declaration instead."
        )
    if (
        directives.tribe is not None
        and family_attach_plan is not None
        and family_attach_plan.parent_agent_clan
    ):
        raise ClanMembershipError(
            "Cannot use %id(..., tribe=...) on a family attachment that "
            "inherits clan membership; tribe membership belongs to the "
            "inherited clan and must be supplied by a clan member's "
            "%clan(<clan>, tribe=<tribe>) declaration."
        )

    from sase.llm_provider.launch_alias_overrides import (
        active_launch_alias_overrides,
        export_launch_alias_overrides,
    )

    explicit_alias_overrides = dict(directives.model_alias_overrides)
    if not explicit_alias_overrides and family_attach_plan is not None:
        explicit_alias_overrides = dict(family_attach_plan.model_alias_overrides)
    model_alias_overrides = dict(
        active_launch_alias_overrides(explicit_alias_overrides or None)
    )
    export_launch_alias_overrides(model_alias_overrides)

    # Top-level `#fork:<name,...>` parents imply `%wait:<name,...>`. Bare
    # `#fork` and `#fork_by_chat` resolve their targets dynamically and are
    # excluded, while explicit waits are not duplicated.
    from sase.agent.names import fork_agent_names

    wait_names = list(directives.wait)
    wait_identity_deps: list[dict[str, str]] = []
    wait_fork_sources: list[dict[str, str]] = []
    wait_beads = list(directives.wait_beads)
    from sase.core.agent_tribe import (
        is_reserved_tribe_name,
        parse_tribe_reference,
        reserved_tribe_target_reason,
    )

    implicit_fork_wait_targets: list[str] = []
    for fork_wait_target in fork_agent_names(fork_reference_prompt):
        fork_tribe = parse_tribe_reference(fork_wait_target)
        if fork_tribe is not None and is_reserved_tribe_name(fork_tribe):
            raise RuntimeError(
                f"Invalid '#fork' tribe reference {fork_wait_target!r}: "
                f"{reserved_tribe_target_reason(fork_tribe)}"
            )
        if fork_wait_target in wait_names:
            continue
        wait_names.append(fork_wait_target)
        if fork_tribe is None:
            implicit_fork_wait_targets.append(fork_wait_target)
    if family_attach_plan and family_attach_plan.parent_is_running:
        if family_attach_plan.parent_name not in wait_names:
            wait_names.append(family_attach_plan.parent_name)
        wait_identity_deps.append(
            {
                "project_name": family_attach_plan.parent_project_name,
                "timestamp": family_attach_plan.parent_timestamp,
                "artifact_dir": family_attach_plan.parent_artifacts_dir,
                "name": family_attach_plan.parent_name,
            }
        )

    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        normalize_owned_agent_name,
    )

    machine_identity = AgentIdentitySnapshot.current()

    def normalized_wait_name(name: str) -> str:
        if parse_tribe_reference(name) is not None:
            return name
        return normalize_owned_agent_name(name, machine_identity)

    explicit_wait_names = {normalized_wait_name(name) for name in directives.wait}
    wait_names = list(dict.fromkeys(normalized_wait_name(name) for name in wait_names))
    if implicit_fork_wait_targets:
        from sase.agent.fork_waits import fork_wait_dependency

        wait_fork_sources = [
            fork_wait_dependency(normalized_wait_name(name))
            for name in implicit_fork_wait_targets
            if normalized_wait_name(name) not in explicit_wait_names
        ]

    auto_dismiss = os.environ.get("SASE_AGENT_AUTO_DISMISS")
    name_request = prepare_agent_name_request(
        directives=directives,
        family_attach_plan=family_attach_plan,
        fork_reference_prompt=fork_reference_prompt,
        wait_names=wait_names,
        auto_dismiss=auto_dismiss,
    )

    preserved_model = preserved_metadata.get("model")
    preserved_provider = preserved_metadata.get("llm_provider")
    agent_model: str | None
    agent_llm_provider: str
    agent_reasoning_effort: str | None
    agent_model_alias: str | None
    agent_model_alias_trail: list[str]
    agent_model_alias_origin: str | None
    agent_model_alias_reservation: dict[str, Any] | None
    if isinstance(preserved_model, str) and isinstance(preserved_provider, str):
        # Runner re-execs/resumptions reuse the authoritative launch selection
        # recorded in metadata and must not advance a load-balanced pool again.
        agent_model = preserved_model
        agent_llm_provider = preserved_provider
        preserved_effort = preserved_metadata.get("reasoning_effort")
        preserved_model_alias = preserved_metadata.get("model_alias")
        preserved_model_alias_trail = preserved_metadata.get("model_alias_trail")
        preserved_model_alias_origin = preserved_metadata.get("model_alias_origin")
        preserved_model_alias_reservation = preserved_metadata.get(
            "model_alias_reservation"
        )
        agent_reasoning_effort = (
            preserved_effort if isinstance(preserved_effort, str) else None
        )
        agent_model_alias = (
            preserved_model_alias if isinstance(preserved_model_alias, str) else None
        )
        agent_model_alias_trail = (
            preserved_model_alias_trail
            if (
                isinstance(preserved_model_alias_trail, list)
                and all(
                    isinstance(item, str) and item
                    for item in preserved_model_alias_trail
                )
            )
            else []
        )
        agent_model_alias_origin = (
            preserved_model_alias_origin
            if isinstance(preserved_model_alias_origin, str)
            else None
        )
        agent_model_alias_reservation = (
            dict(preserved_model_alias_reservation)
            if isinstance(preserved_model_alias_reservation, dict)
            else None
        )
    else:
        # Reserve the launch selection now, before dependency and runner-slot
        # waits. The first prompt step redeems this metadata instead of
        # advancing the same load-balanced pool a second time.
        from sase.llm_provider.config import (
            DEFAULT_MODEL_FIELD,
            launch_model_setting_alias,
        )
        from sase.llm_provider.launch_selection import (
            reservation_from_launch_selection,
            resolve_launch_selection,
        )

        selection = resolve_launch_selection(
            directives,
            model_alias_overrides,
            consume=True,
        )
        assert selection is not None
        agent_model = selection.model
        agent_llm_provider = selection.provider
        agent_reasoning_effort = selection.reasoning_effort
        agent_model_alias_trail = list(selection.alias_trail)
        agent_model_alias_origin = selection.alias_origin
        agent_model_alias = directives.model_alias
        if not directives.model:
            agent_model_alias = launch_model_setting_alias(
                DEFAULT_MODEL_FIELD,
                model_alias_overrides,
            )
        agent_model_alias_reservation = (
            reservation_from_launch_selection(
                selection,
                alias=selection.cursor_alias,
            )
            if selection.cursor_alias
            else None
        )

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
        bead_id=bead_id,
        wait_names=wait_names,
        wait_identity_deps=wait_identity_deps,
        wait_fork_sources=wait_fork_sources,
        wait_beads=wait_beads,
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
        family_attach_plan=family_attach_plan,
        clan_membership_plan=clan_membership_plan,
        artifacts_dir=artifacts_dir,
        metadata_inputs=metadata_inputs,
    )
    agent_name = identity.name
    agent_tribe = identity.tribe
    clan_membership_plan = identity.clan_membership_plan
    agent_meta = identity.meta
    clan_summary_resolution: ClanSummaryResolutionRequest | None = None

    if clan_membership_plan and (directives.clan_declared or epic_clan_summary_script):
        from sase.axe.clan_summary_script import (
            normalize_clan_summary,
            resolve_clan_summary_script,
        )

        clan_summary = (
            normalize_clan_summary(directives.clan_summary or "")
            if directives.clan_declared
            else None
        )
        summary_script = directives.clan_summary_script
        if not directives.clan_declared and epic_clan_summary_script:
            summary_script = epic_clan_summary_script
        if summary_script:
            clan_tribe = directives.clan_tribe
            if not directives.clan_declared and clan_tribe is None:
                epic_clan_tribe = epic_work_metadata.get("clan_tribe")
                if isinstance(epic_clan_tribe, str) and epic_clan_tribe:
                    clan_tribe = epic_clan_tribe
            clan_summary_resolution = ClanSummaryResolutionRequest(
                script=summary_script,
                clan_name=clan_membership_plan.clan_name,
                clan_generation=clan_membership_plan.generation,
                clan_tribe=clan_tribe,
            )
            clan_summary = resolve_clan_summary_script(
                summary_script,
                workspace_dir=workspace_dir,
                clan_name=clan_membership_plan.clan_name,
                clan_generation=clan_membership_plan.generation,
                clan_tribe=clan_tribe,
                agent_log_path=output_path,
                artifacts_dir=artifacts_dir,
                environment=launch_environment,
            )
        if clan_summary:
            agent_meta["clan_summary"] = clan_summary

    # Write metadata after the name reservation succeeds. Summary scripts run
    # outside the allocation lock because their timeout is comparatively long.
    if agent_meta:
        write_agent_meta(artifacts_dir, agent_meta)

    # Persist %id tribe= for the Agents tab's workflow identity.
    if directives.tribe and cl_name:
        from sase.ace.agent_tribes import update_agent_tribe
        from sase.core.agent_types import AgentType

        raw_suffix = os.path.basename(artifacts_dir.rstrip(os.sep)) or None
        identity_key = (AgentType.WORKFLOW, cl_name, raw_suffix)
        update_agent_tribe(identity_key, directives.tribe)

    auto_mode = directives.auto_mode
    return AgentInfo(
        name=agent_name,
        bead_id=bead_id,
        wait_names=wait_names,
        wait_identity_deps=wait_identity_deps,
        wait_fork_sources=wait_fork_sources,
        wait_beads=wait_beads,
        wait_duration=directives.wait_duration,
        wait_until=directives.wait_until,
        wait_runners=directives.wait_runners,
        wait_priority=directives.wait_priority,
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
    )
