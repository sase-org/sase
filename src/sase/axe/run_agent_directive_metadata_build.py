"""Assemble launch metadata for run-agent directives."""

from __future__ import annotations

import json
import os
from typing import Any, TYPE_CHECKING

from sase.axe._run_agent_directive_metadata_shared import (
    invalid_queue_weight_message,
)
from sase.axe.run_agent_directive_metadata_inputs import (
    AgentMetadataInputs,
    DEFAULT_QUEUE_WEIGHT,
)
from sase.axe.run_agent_directive_metadata_preserved import session_root_tab
from sase.core.process_identity import process_identity_token
from sase.core.runner_slots import inheritable_queue_weight
from sase.plan_chain import AGENT_SESSION_KEY, set_agent_session_fields

if TYPE_CHECKING:
    from sase.agent.clan_membership import ClanMembershipPlan
    from sase.agent.agent_session_attach import AgentSessionAttachLaunchPlan
    from sase.macro.directives import PromptDirectives


def build_agent_meta(
    inputs: AgentMetadataInputs,
    *,
    directives: PromptDirectives,
    agent_name: str | None,
    agent_tribe: str | None,
    agent_session_attach_plan: AgentSessionAttachLaunchPlan | None,
    clan_membership_plan: ClanMembershipPlan | None,
) -> dict[str, Any]:
    """Build launch metadata after the agent identity has been allocated."""
    pid = os.getpid()
    agent_meta: dict[str, Any] = {
        "pid": pid,
        "process_identity": process_identity_token(pid),
        "workspace_dir": inputs.workspace_dir,
        "workspace_num": inputs.workspace_num,
    }
    if inputs.output_path:
        agent_meta["output_path"] = inputs.output_path
    if agent_name:
        agent_meta["name"] = agent_name
    if inputs.bead_id:
        agent_meta["bead_id"] = inputs.bead_id
    if inputs.wait_names:
        agent_meta["wait_for"] = inputs.wait_names
    if inputs.wait_identity_deps:
        agent_meta["wait_for_artifacts"] = inputs.wait_identity_deps
    if inputs.wait_fork_sources:
        agent_meta["wait_for_fork_sources"] = inputs.wait_fork_sources
    if inputs.wait_beads:
        agent_meta["wait_for_beads"] = inputs.wait_beads
    if inputs.wait_hoods:
        agent_meta["wait_for_hoods"] = inputs.wait_hoods
    if inputs.wait_for_epics_of:
        agent_meta["wait_for_epics_of"] = list(inputs.wait_for_epics_of)
    if directives.wait_duration is not None:
        agent_meta["wait_duration"] = directives.wait_duration
    if directives.wait_until is not None:
        agent_meta["wait_until"] = directives.wait_until
    if directives.queue_capacity is not None:
        agent_meta["queue_capacity"] = directives.queue_capacity
        agent_meta["queue_capacity_explicit"] = True
        agent_meta.pop("queue_capacity_multiplier", None)
    elif directives.queue_capacity_multiplier is not None:
        agent_meta["queue_capacity_multiplier"] = directives.queue_capacity_multiplier
        agent_meta.pop("queue_capacity", None)
        agent_meta.pop("queue_capacity_explicit", None)
    if directives.wait_priority is not None:
        agent_meta["wait_priority"] = directives.wait_priority
    authored_queue_weight = (
        directives.queue_weight
        if directives.queue_weight_explicit and directives.queue_weight is not None
        else DEFAULT_QUEUE_WEIGHT
    )
    authored_queue_weight_explicit = directives.queue_weight_explicit
    agent_meta["queue_weight"] = authored_queue_weight
    agent_meta["queue_weight_explicit"] = directives.queue_weight_explicit
    if inputs.model:
        agent_meta["model"] = inputs.model
    if inputs.llm_provider:
        agent_meta["llm_provider"] = inputs.llm_provider
    if inputs.reasoning_effort:
        agent_meta["reasoning_effort"] = inputs.reasoning_effort
    if inputs.model_alias:
        agent_meta["model_alias"] = inputs.model_alias
    if inputs.model_alias_trail:
        agent_meta["model_alias_trail"] = inputs.model_alias_trail
    if inputs.model_alias_origin:
        agent_meta["model_alias_origin"] = inputs.model_alias_origin
    if inputs.model_alias_reservation:
        agent_meta["model_alias_reservation"] = inputs.model_alias_reservation
    if inputs.model_alias_overrides:
        agent_meta["model_alias_overrides"] = inputs.model_alias_overrides
    if inputs.vcs_provider:
        agent_meta["vcs_provider"] = inputs.vcs_provider
    from sase.autonomy.record import (
        apply_record_meta_patch,
        autonomy_inherit_record,
        read_record,
        resolve_selection,
    )

    if directives.auto_enabled and directives.auto_argument is not None:
        auto_selection: str | None = directives.auto_argument
    elif directives.auto_enabled:
        auto_selection = ""
    else:
        auto_selection = None
    host_composed = bool(
        agent_session_attach_plan
        and getattr(agent_session_attach_plan, "host_composed", False)
    )
    inherited_record: dict[str, Any] | None = None
    if host_composed and agent_session_attach_plan is not None:
        # Host-composed attach children inherit the parent member's live
        # record; the prompt's own %auto, if any, narrows under agent
        # semantics. A human %id(..., session=...) launch keeps resolving
        # from its own prompt (host_composed False).
        parent_meta = _read_parent_agent_meta(agent_session_attach_plan)
        predecessor = read_record(parent_meta) if parent_meta else None
        if predecessor is not None:
            try:
                outcome = autonomy_inherit_record(
                    predecessor,
                    predecessor_name=str(
                        parent_meta.get("name", "")
                        if isinstance(parent_meta, dict)
                        else ""
                    ),
                    explicit_selection=auto_selection,
                    actor_kind="host",
                )
            except Exception:
                outcome = None
            if isinstance(outcome, dict) and isinstance(outcome.get("record"), dict):
                inherited_record = dict(outcome["record"])
    if inherited_record is not None:
        apply_record_meta_patch(agent_meta, inherited_record)
    else:
        apply_record_meta_patch(
            agent_meta,
            resolve_selection(auto_selection, source="prompt", surface="launch"),
        )
    if directives.hide or inputs.auto_dismiss:
        agent_meta["hidden"] = True
    if agent_tribe:
        agent_meta["tribe"] = agent_tribe
    if directives.name_template and directives.name:
        agent_meta["agent_name_template"] = directives.name

    from sase.linked_repos import linked_repo_metadata_from_env

    linked_repos = linked_repo_metadata_from_env()
    if linked_repos:
        # Canonical key plus the deprecated alias for existing readers.
        agent_meta["linked_repos"] = linked_repos
        agent_meta["sibling_repos"] = linked_repos

    from sase.axe.chop_agents import agent_meta_from_chop_env

    agent_meta.update(agent_meta_from_chop_env())
    agent_meta.update(inputs.preserved)
    _apply_agent_tab_directive(agent_meta, directives)
    if authored_queue_weight_explicit:
        agent_meta["queue_weight"] = authored_queue_weight
        agent_meta["queue_weight_explicit"] = True
    agent_meta.update(inputs.epic_work)
    if inputs.vcs_ref:
        agent_meta["vcs_ref"] = [inputs.vcs_ref[0], inputs.vcs_ref[1]]
    if inputs.cl_name:
        agent_meta["patch_name"] = inputs.cl_name
        agent_meta["changespec_name"] = inputs.cl_name
        agent_meta.setdefault("cl_name", inputs.cl_name)
    if agent_session_attach_plan:
        _add_agent_session_metadata(agent_meta, agent_session_attach_plan)
    if clan_membership_plan:
        _add_clan_metadata(
            agent_meta,
            directives=directives,
            agent_name=agent_name,
            clan_membership_plan=clan_membership_plan,
        )
    _qualify_agent_identity_metadata(agent_meta)
    return agent_meta


def _apply_agent_tab_directive(
    agent_meta: dict[str, Any],
    directives: PromptDirectives,
) -> None:
    """Apply the ``%tab`` directive after preserved metadata is merged."""
    tab = getattr(directives, "agent_tab", None)
    explicit_default = bool(getattr(directives, "agent_tab_explicit_default", False))
    if tab:
        agent_meta["agent_tab"] = tab
        agent_meta["agent_tab_source"] = "prompt"
    elif explicit_default:
        agent_meta.pop("agent_tab", None)
        agent_meta.pop("agent_tab_source", None)


def _read_parent_agent_meta(
    agent_session_attach_plan: AgentSessionAttachLaunchPlan,
) -> dict[str, Any] | None:
    meta_path = os.path.join(
        agent_session_attach_plan.parent_artifacts_dir, "agent_meta.json"
    )
    try:
        with open(meta_path, encoding="utf-8") as f:
            parent_meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return parent_meta if isinstance(parent_meta, dict) else None


def _parent_queue_weight(
    agent_session_attach_plan: AgentSessionAttachLaunchPlan,
) -> tuple[float | None, bool]:
    parent_meta = _read_parent_agent_meta(agent_session_attach_plan)
    if parent_meta is None:
        return None, False
    if parent_meta.get("queue_weight_invalid") is True:
        raise RuntimeError(
            invalid_queue_weight_message(
                "agent-session parent metadata",
                parent_meta.get("queue_weight"),
            )
        )
    return inheritable_queue_weight(parent_meta)


def _parent_runner_claim_owner_key(
    agent_session_attach_plan: AgentSessionAttachLaunchPlan,
) -> str | None:
    """Return the parent's durable claim owner key, straight off its own file.

    Reading the parent's own ``agent_meta.json`` (rather than a live scan)
    means this lineage link survives a ``capacity_only`` runner-slot scan
    dropping the parent's directory once it is done: the child carries its
    predecessor's owner key forward durably instead of needing to re-derive
    it from a scan that may no longer include the parent at all.
    """
    parent_meta = _read_parent_agent_meta(agent_session_attach_plan)
    if parent_meta is None:
        return None
    owner_key = parent_meta.get("runner_claim_owner_key")
    return owner_key if isinstance(owner_key, str) and owner_key else None


def _qualify_agent_identity_metadata(agent_meta: dict[str, Any]) -> None:
    """Normalize newly written identity and relationship fields once."""
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        normalize_owned_agent_name,
    )

    identity = AgentIdentitySnapshot.current()
    for key in ("name", "workflow_name", AGENT_SESSION_KEY, "agent_clan"):
        value = agent_meta.get(key)
        if isinstance(value, str) and value:
            agent_meta[key] = normalize_owned_agent_name(value, identity)
    wait_for = agent_meta.get("wait_for")
    if isinstance(wait_for, list):
        agent_meta["wait_for"] = [
            value
            if not isinstance(value, str) or value.startswith("@")
            else normalize_owned_agent_name(value, identity)
            for value in wait_for
        ]


def _add_agent_session_metadata(
    agent_meta: dict[str, Any],
    agent_session_attach_plan: AgentSessionAttachLaunchPlan,
) -> None:
    from sase.agent.agent_session_attach import promote_agent_session_parent_for_attach
    from sase.plan_chain import PLAN_CHAIN_PARENT_TIMESTAMP_FIELD

    promote_agent_session_parent_for_attach(agent_session_attach_plan)
    agent_meta["name"] = agent_session_attach_plan.agent_name
    agent_meta["workflow_name"] = agent_session_attach_plan.parent_base
    agent_meta["role_suffix"] = agent_session_attach_plan.role_suffix
    agent_meta["parent_timestamp"] = agent_session_attach_plan.parent_timestamp
    agent_meta[PLAN_CHAIN_PARENT_TIMESTAMP_FIELD] = (
        agent_session_attach_plan.parent_timestamp
    )
    set_agent_session_fields(
        agent_meta,
        session=agent_session_attach_plan.parent_base,
        role=agent_session_attach_plan.agent_session_role,
    )
    claimed_workspace_num = agent_meta.get("workspace_num")
    run_has_claimed_workspace = (
        isinstance(claimed_workspace_num, int) and claimed_workspace_num > 0
    )
    if agent_session_attach_plan.parent_workspace_dir and not run_has_claimed_workspace:
        agent_meta["workspace_dir"] = agent_session_attach_plan.parent_workspace_dir
    if (
        agent_session_attach_plan.parent_workspace_num is not None
        and not run_has_claimed_workspace
    ):
        agent_meta["workspace_num"] = agent_session_attach_plan.parent_workspace_num
    if agent_session_attach_plan.parent_cl_name:
        agent_meta["patch_name"] = agent_session_attach_plan.parent_cl_name
        agent_meta["changespec_name"] = agent_session_attach_plan.parent_cl_name
        agent_meta["cl_name"] = agent_session_attach_plan.parent_cl_name
    if agent_meta.get("queue_weight_explicit") is not True:
        parent_queue_weight, parent_explicit = _parent_queue_weight(
            agent_session_attach_plan
        )
        if parent_queue_weight is not None:
            agent_meta["queue_weight"] = parent_queue_weight
            agent_meta["queue_weight_explicit"] = parent_explicit
    parent_owner_key = _parent_runner_claim_owner_key(agent_session_attach_plan)
    if parent_owner_key is not None:
        agent_meta["runner_claim_owner_key"] = parent_owner_key
    if agent_session_attach_plan.parent_agent_clan:
        from sase.agent.clan_membership import (
            AGENT_CLAN_FIELD,
            AGENT_CLAN_GENERATION_FIELD,
        )

        agent_meta[AGENT_CLAN_FIELD] = agent_session_attach_plan.parent_agent_clan
        if agent_session_attach_plan.parent_agent_clan_generation:
            agent_meta[AGENT_CLAN_GENERATION_FIELD] = (
                agent_session_attach_plan.parent_agent_clan_generation
            )
    _inherit_session_root_tab(agent_meta, agent_session_attach_plan)


def _inherit_session_root_tab(
    agent_meta: dict[str, Any],
    agent_session_attach_plan: AgentSessionAttachLaunchPlan,
) -> None:
    """Copy the session root's stored tab into the child meta."""
    root_tab = session_root_tab(agent_session_attach_plan)
    if root_tab:
        # Only fill when the child does not already carry an explicit tab;
        # an explicit matching tab was validated upstream.
        if not agent_meta.get("agent_tab"):
            agent_meta["agent_tab"] = root_tab
            agent_meta["agent_tab_source"] = "prompt"


def _add_clan_metadata(
    agent_meta: dict[str, Any],
    *,
    directives: PromptDirectives,
    agent_name: str | None,
    clan_membership_plan: ClanMembershipPlan,
) -> None:
    from sase.agent.clan_membership import (
        AGENT_CLAN_FIELD,
        AGENT_CLAN_GENERATION_FIELD,
        ClanMembershipError,
    )

    clan_prefix = f"{clan_membership_plan.clan_name}."
    if (
        not agent_name
        or not agent_name.startswith(clan_prefix)
        or not agent_name.removeprefix(clan_prefix)
    ):
        raise ClanMembershipError(
            f"Agent '{agent_name or ''}' cannot join clan "
            f"'{clan_membership_plan.clan_name}': clan members must use "
            f"the '{clan_prefix}<suffix>' hood"
        )
    agent_meta[AGENT_CLAN_FIELD] = clan_membership_plan.clan_name
    agent_meta[AGENT_CLAN_GENERATION_FIELD] = clan_membership_plan.generation
    if directives.clan_tribe:
        agent_meta["clan_tribe"] = directives.clan_tribe
