"""Agent identity allocation and claiming for run-agent directives."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
import logging
import os
from typing import Any, TYPE_CHECKING

from sase.axe.run_agent_directive_metadata import (
    AgentMetadataInputs,
    build_agent_meta,
)

if TYPE_CHECKING:
    from sase.agent.clan_membership import ClanMembershipPlan
    from sase.agent.family_attach import FamilyAttachLaunchPlan
    from sase.xprompt.directives import PromptDirectives

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _AgentNameRequest:
    """Inputs captured before resolving providers and claiming a name."""

    initial_name: str | None
    resume_name: str | None
    wait_name: str | None
    repeat_name: str | None
    planned_name: str | None
    user_explicit: bool
    requires_lock: bool


@dataclass(frozen=True)
class AgentIdentity:
    """Allocated identity and metadata produced under the name lock."""

    name: str | None
    tribe: str | None
    clan_membership_plan: ClanMembershipPlan | None
    meta: dict[str, Any]


def prepare_agent_name_request(
    *,
    directives: PromptDirectives,
    family_attach_plan: FamilyAttachLaunchPlan | None,
    fork_reference_prompt: str,
    wait_names: list[str],
    auto_dismiss: str | None,
) -> _AgentNameRequest:
    """Capture environment-driven name inputs before provider resolution."""
    agent_name = (
        family_attach_plan.agent_name if family_attach_plan else directives.name
    )
    resume_name: str | None = None
    wait_name: str | None = None
    if not directives.name_explicit and not auto_dismiss:
        from sase.agent.names import sole_resume_agent_name
        from sase.core.agent_tribe import parse_tribe_reference

        resume_name = sole_resume_agent_name(fork_reference_prompt)
        if (
            resume_name is None
            and len(wait_names) == 1
            and parse_tribe_reference(wait_names[0]) is None
        ):
            wait_name = wait_names[0]

    repeat_name = os.environ.get("SASE_REPEAT_NAME")
    planned_name = os.environ.get("SASE_AGENT_PLANNED_NAME")
    # Pop: the marker describes this launch only. Leaving it in the
    # environment makes nested launches from this agent treat their own
    # explicit %id directives as generated, silently skipping name
    # collision checks.
    generated_name = os.environ.pop("SASE_AGENT_GENERATED_NAME", None) == "1"
    user_explicit = (
        bool(family_attach_plan) or directives.name_explicit
    ) and not generated_name
    requires_lock = bool(
        agent_name or repeat_name or resume_name or wait_name or not auto_dismiss
    )
    return _AgentNameRequest(
        initial_name=agent_name,
        resume_name=resume_name,
        wait_name=wait_name,
        repeat_name=repeat_name,
        planned_name=planned_name,
        user_explicit=user_explicit,
        requires_lock=requires_lock,
    )


def resolve_agent_identity(
    request: _AgentNameRequest,
    *,
    directives: PromptDirectives,
    family_attach_plan: FamilyAttachLaunchPlan | None,
    clan_membership_plan: ClanMembershipPlan | None,
    artifacts_dir: str,
    metadata_inputs: AgentMetadataInputs,
) -> AgentIdentity:
    """Allocate, enrich, and claim an agent identity atomically."""
    name_lock_context: AbstractContextManager[None]
    if request.requires_lock:
        from sase.agent.names import agent_name_allocation_lock

        name_lock_context = agent_name_allocation_lock()
    else:
        name_lock_context = nullcontext()

    agent_name = request.initial_name
    planned_name = request.planned_name
    with name_lock_context:
        from sase.core.machine_hood_facade import (
            MachineHoodIdentity,
            qualify_local_agent_name,
        )

        machine_identity = MachineHoodIdentity.current()
        if planned_name and not _planned_name_is_reserved_for_artifacts(
            planned_name, artifacts_dir
        ):
            log.warning(
                "Ignoring stale SASE_AGENT_PLANNED_NAME=%r because its "
                "registry reservation does not belong to artifacts directory %s",
                planned_name,
                artifacts_dir,
            )
            planned_name = None

        agent_name_from_template = False
        if directives.name_explicit and directives.name_template and agent_name:
            from sase.agent.names import (
                allocate_agent_name_template,
                match_agent_name_template,
            )

            if planned_name and match_agent_name_template(agent_name, planned_name):
                agent_name = planned_name
            else:
                agent_name = allocate_agent_name_template(agent_name)
            agent_name_from_template = True

        planned_name_matches_resume = (
            planned_name is not None
            and request.resume_name is not None
            and _planned_name_matches_resume_target(
                planned_name,
                request.resume_name,
            )
        )
        planned_name_is_usable = (
            planned_name is not None
            and not metadata_inputs.auto_dismiss
            and (request.resume_name is None or planned_name_matches_resume)
        )
        if agent_name_from_template:
            pass
        elif not request.user_explicit and planned_name_is_usable:
            agent_name = planned_name
        elif not request.user_explicit and request.resume_name is not None:
            from sase.agent.names import allocate_resume_name

            agent_name = allocate_resume_name(request.resume_name)
        elif (
            not request.user_explicit
            and request.repeat_name is None
            and request.wait_name is not None
        ):
            from sase.agent.names import allocate_wait_name

            agent_name = allocate_wait_name(request.wait_name)
        if agent_name is None:
            agent_name = request.repeat_name
        if agent_name is None and not metadata_inputs.auto_dismiss:
            from sase.agent.names import get_next_auto_name

            agent_name = get_next_auto_name()

        if agent_name is not None:
            agent_name = qualify_local_agent_name(agent_name, machine_identity)

        if clan_membership_plan is None and directives.clan is not None:
            clan_membership_plan = _resolve_clan_membership(
                directives=directives,
                artifacts_dir=artifacts_dir,
                agent_name=agent_name,
            )

        agent_tribe = directives.tribe
        agent_meta = build_agent_meta(
            metadata_inputs,
            directives=directives,
            agent_name=agent_name,
            agent_tribe=agent_tribe,
            family_attach_plan=family_attach_plan,
            clan_membership_plan=clan_membership_plan,
        )

        if agent_name:
            _claim_agent_identity(
                agent_name,
                artifacts_dir=artifacts_dir,
                user_explicit=request.user_explicit,
                force_reuse=directives.name_force_reuse,
                clan_membership_plan=clan_membership_plan,
            )

    return AgentIdentity(
        name=agent_name,
        tribe=agent_tribe,
        clan_membership_plan=clan_membership_plan,
        meta=agent_meta,
    )


def _resolve_clan_membership(
    *,
    directives: PromptDirectives,
    artifacts_dir: str,
    agent_name: str | None,
) -> ClanMembershipPlan:
    from pathlib import Path

    from sase.agent.clan_membership import (
        ClanMembershipError,
        declare_clan_membership,
        resolve_or_create_clan_membership,
    )

    clan_name = directives.clan
    assert clan_name is not None
    membership_resolver = (
        declare_clan_membership
        if directives.clan_declared
        else resolve_or_create_clan_membership
    )
    clan_membership_plan = membership_resolver(
        clan_name,
        generation=Path(artifacts_dir).name,
        claiming_dir=artifacts_dir,
        member_name=agent_name,
        member_name_template=directives.name,
    )
    clan_prefix = f"{clan_membership_plan.clan_name}."
    if (
        not agent_name
        or not agent_name.startswith(clan_prefix)
        or not agent_name.removeprefix(clan_prefix)
    ):
        from sase.agent.names import release_planned_registered_clan_name

        release_planned_registered_clan_name(
            clan_membership_plan.clan_name,
            clan_membership_plan.generation,
            artifacts_dir,
        )
        raise ClanMembershipError(
            f"Agent '{agent_name or ''}' cannot join clan "
            f"'{clan_membership_plan.clan_name}': clan members must use "
            f"the '{clan_prefix}<suffix>' hood"
        )
    return clan_membership_plan


def _claim_agent_identity(
    agent_name: str,
    *,
    artifacts_dir: str,
    user_explicit: bool,
    force_reuse: bool,
    clan_membership_plan: ClanMembershipPlan | None,
) -> None:
    from sase.agent.launch_validation import (
        internal_agent_name_bypass_enabled,
        validate_user_agent_name,
    )
    from sase.agent.names import claim_agent_name

    if user_explicit and not internal_agent_name_bypass_enabled(os.environ):
        validate_user_agent_name(agent_name)

    claim_agent_name(
        agent_name,
        artifacts_dir,
        explicit=user_explicit,
        force_reuse=force_reuse,
    )
    if clan_membership_plan:
        from sase.agent.names import claim_registered_clan_name

        claim_registered_clan_name(
            clan_membership_plan.clan_name,
            clan_membership_plan.generation,
            artifacts_dir,
        )
    os.environ["SASE_AGENT_NAME"] = agent_name


def _planned_name_matches_resume_target(planned_name: str, resume_name: str) -> bool:
    from sase.agent.names import (
        AgentNameTemplateError,
        match_agent_name_template,
        resume_agent_name_template,
    )

    template = resume_agent_name_template(resume_name)
    try:
        if match_agent_name_template(template, planned_name) is not None:
            return True
    except AgentNameTemplateError:
        pass

    from sase.core.machine_hood_facade import strip_local_agent_name

    local_planned_name = strip_local_agent_name(planned_name)
    local_resume_name = strip_local_agent_name(resume_name)
    prefix = f"{local_resume_name}.f"
    if not local_planned_name.startswith(prefix):
        return False

    rendered_token = local_planned_name.removeprefix(prefix).split(".", 1)[0]
    if not rendered_token:
        return False
    try:
        return (
            match_agent_name_template(template, f"{prefix}{rendered_token}") is not None
        )
    except AgentNameTemplateError:
        return False


def _planned_name_is_reserved_for_artifacts(
    planned_name: str, artifacts_dir: str
) -> bool:
    """Return whether *planned_name* is durably reserved for this run."""
    from sase.agent.names import lookup_registered_name

    entry = lookup_registered_name(planned_name)
    if entry is None:
        return False
    reserved_dir = entry.get("artifacts_dir")
    if not isinstance(reserved_dir, str) or not reserved_dir:
        return False
    return os.path.realpath(os.path.expanduser(reserved_dir)) == os.path.realpath(
        os.path.expanduser(artifacts_dir)
    )
