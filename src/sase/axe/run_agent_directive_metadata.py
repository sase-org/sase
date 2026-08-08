"""Metadata assembly helpers for run-agent prompt directives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from typing import Any, TYPE_CHECKING

from sase.bead.work import (
    SASE_EPIC_BEAD_ID_ENV,
    SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV,
    SASE_EPIC_CLAN_TRIBE_ENV,
    SASE_EPIC_PLAN_REF_ENV,
    SASE_EPIC_PLAN_SNAPSHOT_ENV,
    SASE_PHASE_BEAD_ID_ENV,
)

if TYPE_CHECKING:
    from sase.agent.clan_membership import ClanMembershipPlan
    from sase.agent.family_attach import FamilyAttachLaunchPlan
    from sase.xprompt.directives import PromptDirectives


EPIC_WORK_ENV_METADATA_NAMES = (
    (SASE_EPIC_PLAN_REF_ENV, "epic_plan_ref"),
    (SASE_EPIC_PLAN_SNAPSHOT_ENV, "epic_plan_snapshot"),
    (SASE_EPIC_BEAD_ID_ENV, "epic_bead_id"),
    (SASE_PHASE_BEAD_ID_ENV, "phase_bead_id"),
    (SASE_EPIC_CLAN_TRIBE_ENV, "clan_tribe"),
)


@dataclass(frozen=True)
class AgentMetadataInputs:
    """Resolved launch values used to assemble ``agent_meta.json``."""

    workspace_dir: str
    output_path: str | None
    bead_id: str | None
    wait_names: list[str]
    wait_identity_deps: list[dict[str, str]]
    wait_beads: list[str]
    model: str | None
    llm_provider: str | None
    reasoning_effort: str | None
    model_alias_overrides: dict[str, str]
    vcs_provider: str | None
    auto_dismiss: str | None
    preserved: dict[str, Any]
    epic_work: dict[str, Any]
    cl_name: str | None


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
    ):
        value = existing_meta.get(key)
        if isinstance(value, str) and value:
            preserved[key] = value
    if existing_meta.get("plan_committed") is True:
        preserved["plan_committed"] = True
    for key in (
        "agent_clan",
        "agent_clan_generation",
        "clan_tribe",
        "clan_summary",
    ):
        value = existing_meta.get(key)
        if isinstance(value, str) and value:
            preserved[key] = value
    if existing_meta.get("agent_family_parallel") is True:
        for key in (
            "agent_family",
            "agent_family_role",
            "parent_timestamp",
        ):
            value = existing_meta.get(key)
            if isinstance(value, str) and value:
                preserved[key] = value
        preserved["agent_family_parallel"] = True
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


def build_agent_meta(
    inputs: AgentMetadataInputs,
    *,
    directives: PromptDirectives,
    agent_name: str | None,
    agent_tribe: str | None,
    family_attach_plan: FamilyAttachLaunchPlan | None,
    clan_membership_plan: ClanMembershipPlan | None,
) -> dict[str, Any]:
    """Build launch metadata after the agent identity has been allocated."""
    agent_meta: dict[str, Any] = {
        "pid": os.getpid(),
        "workspace_dir": inputs.workspace_dir,
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
    if inputs.wait_beads:
        agent_meta["wait_for_beads"] = inputs.wait_beads
    if directives.wait_duration is not None:
        agent_meta["wait_duration"] = directives.wait_duration
    if directives.wait_until is not None:
        agent_meta["wait_until"] = directives.wait_until
    if directives.wait_runners is not None:
        agent_meta["wait_runners"] = directives.wait_runners
    if directives.wait_priority is not None:
        agent_meta["wait_priority"] = directives.wait_priority
    if inputs.model:
        agent_meta["model"] = inputs.model
    if inputs.llm_provider:
        agent_meta["llm_provider"] = inputs.llm_provider
    if inputs.reasoning_effort:
        agent_meta["reasoning_effort"] = inputs.reasoning_effort
    if inputs.model_alias_overrides:
        agent_meta["model_alias_overrides"] = inputs.model_alias_overrides
    if inputs.vcs_provider:
        agent_meta["vcs_provider"] = inputs.vcs_provider
    auto_mode = directives.auto_mode
    if auto_mode == "plan":
        agent_meta["approve"] = True
    if directives.auto_argument is not None:
        agent_meta["auto_approve_argument"] = directives.auto_argument
    if auto_mode == "epic":
        agent_meta["auto_approve_plan_action"] = "epic"
    if auto_mode == "tale":
        agent_meta["auto_approve_plan_action"] = "tale"
    if directives.hide or inputs.auto_dismiss:
        agent_meta["hidden"] = True
    if auto_mode in {"epic", "tale"}:
        agent_meta["plan"] = True
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
    agent_meta.update(inputs.epic_work)
    if inputs.cl_name:
        agent_meta["patch_name"] = inputs.cl_name
        agent_meta["changespec_name"] = inputs.cl_name
        agent_meta.setdefault("cl_name", inputs.cl_name)
    if family_attach_plan:
        _add_family_metadata(agent_meta, family_attach_plan)
    if clan_membership_plan:
        _add_clan_metadata(
            agent_meta,
            directives=directives,
            agent_name=agent_name,
            clan_membership_plan=clan_membership_plan,
        )
    _qualify_agent_identity_metadata(agent_meta)
    return agent_meta


def _qualify_agent_identity_metadata(agent_meta: dict[str, Any]) -> None:
    """Normalize newly written identity and relationship fields once."""
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        normalize_owned_agent_name,
    )

    identity = AgentIdentitySnapshot.current()
    for key in ("name", "workflow_name", "agent_family", "agent_clan"):
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


def _add_family_metadata(
    agent_meta: dict[str, Any],
    family_attach_plan: FamilyAttachLaunchPlan,
) -> None:
    from sase.agent.family_attach import promote_family_parent_for_attach
    from sase.plan_chain import (
        AGENT_FAMILY_FIELD,
        AGENT_FAMILY_ROLE_FIELD,
        PLAN_CHAIN_PARENT_TIMESTAMP_FIELD,
    )

    promote_family_parent_for_attach(family_attach_plan)
    agent_meta["name"] = family_attach_plan.agent_name
    agent_meta["workflow_name"] = family_attach_plan.parent_base
    agent_meta["role_suffix"] = family_attach_plan.role_suffix
    agent_meta["parent_timestamp"] = family_attach_plan.parent_timestamp
    agent_meta[PLAN_CHAIN_PARENT_TIMESTAMP_FIELD] = family_attach_plan.parent_timestamp
    agent_meta[AGENT_FAMILY_FIELD] = family_attach_plan.parent_base
    agent_meta[AGENT_FAMILY_ROLE_FIELD] = family_attach_plan.agent_family_role
    if family_attach_plan.parent_workspace_dir:
        agent_meta["workspace_dir"] = family_attach_plan.parent_workspace_dir
    if family_attach_plan.parent_workspace_num is not None:
        agent_meta["workspace_num"] = family_attach_plan.parent_workspace_num
    if family_attach_plan.parent_cl_name:
        agent_meta["patch_name"] = family_attach_plan.parent_cl_name
        agent_meta["changespec_name"] = family_attach_plan.parent_cl_name
        agent_meta["cl_name"] = family_attach_plan.parent_cl_name
    if family_attach_plan.parent_agent_clan:
        from sase.agent.clan_membership import (
            AGENT_CLAN_FIELD,
            AGENT_CLAN_GENERATION_FIELD,
        )

        agent_meta[AGENT_CLAN_FIELD] = family_attach_plan.parent_agent_clan
        if family_attach_plan.parent_agent_clan_generation:
            agent_meta[AGENT_CLAN_GENERATION_FIELD] = (
                family_attach_plan.parent_agent_clan_generation
            )


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
