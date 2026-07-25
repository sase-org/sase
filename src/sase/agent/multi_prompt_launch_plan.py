"""Preflight planning for multi-prompt agent launches."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from sase.agent.clan_membership import (
    ClanMembershipPlan,
    derive_clan_name_from_member,
    encode_clan_membership_plan,
)
from sase.agent.multi_prompt_references import (
    PlannedNameAllocator,
    StaticClanDirective,
    extract_static_clan_directive,
    extract_static_name_directive,
)
from sase.agent.multi_prompt_vcs import (
    SegmentVcsContext,
    resolve_segment_vcs_context,
)
from sase.agent.multi_prompt_xprompts import local_xprompts_for_segment
from sase.core.agent_launch_facade import LaunchTimestampBatchAllocator
from sase.core.agent_launch_wire import LaunchFanoutPlanWire
from sase.xprompt.models import XPrompt


def future_agent_artifacts_dir(*, project_name: str, timestamp: str) -> Path:
    from sase.artifacts import convert_timestamp_to_artifacts_format
    from sase.core.agent_artifact_paths import canonical_agent_artifact_path

    return canonical_agent_artifact_path(
        project_name,
        "ace-run",
        convert_timestamp_to_artifacts_format(timestamp),
    )


def assign_missing_slot_timestamps(
    plan: LaunchFanoutPlanWire,
    timestamp_allocator: LaunchTimestampBatchAllocator,
) -> LaunchFanoutPlanWire:
    missing_count = sum(1 for slot in plan.slots if slot.timestamp is None)
    if missing_count == 0:
        return plan
    allocated = iter(timestamp_allocator.allocate(missing_count))
    return replace(
        plan,
        slots=[
            slot
            if slot.timestamp is not None
            else replace(slot, timestamp=next(allocated))
            for slot in plan.slots
        ],
    )


def plan_segment_fanout(
    segment: str,
    *,
    segment_local_xprompts: dict[str, XPrompt],
    preplanned_fanout_plan: LaunchFanoutPlanWire | None,
) -> tuple[LaunchFanoutPlanWire, bool]:
    """Return one segment's launch plan and whether it is a real fan-out."""
    from sase.core.agent_launch_facade import plan_fake_fanout
    from sase.xprompt.directives import plan_prompt_fanout_variants

    fanout_plan = (
        preplanned_fanout_plan
        if preplanned_fanout_plan is not None
        else plan_prompt_fanout_variants(
            segment,
            extra_xprompts=segment_local_xprompts or None,
        )
    )
    if fanout_plan is None and preplanned_fanout_plan is None and "#" in segment:
        from sase.xprompt.processor import (
            LAUNCH_DEFERRED_XPROMPT_NAMES,
            process_xprompt_references,
        )

        expanded = process_xprompt_references(
            segment,
            extra_xprompts=segment_local_xprompts or None,
            defer_xprompt_names=LAUNCH_DEFERRED_XPROMPT_NAMES,
        )
        fanout_plan = plan_prompt_fanout_variants(
            expanded,
            extra_xprompts=segment_local_xprompts or None,
        )
    if fanout_plan is not None:
        return fanout_plan, True
    return plan_fake_fanout("multi_prompt", [segment]), False


@dataclass
class _ClanPrepass:
    """Clan launch values pinned before any member can spawn."""

    plans_by_segment: dict[int, LaunchFanoutPlanWire]
    contexts_by_slot: dict[tuple[int, int], SegmentVcsContext]
    artifacts_dirs_by_slot: dict[tuple[int, int], Path]
    planned_names_by_slot: dict[tuple[int, int], str]
    planned_env_names_by_slot: dict[tuple[int, int], str | None]
    membership_env_by_segment: dict[int, str]
    membership_by_segment: dict[int, ClanMembershipPlan]
    planned_clan_reservations: list[tuple[str, str, Path]]

    def release_uncommitted_clan_reservations(self) -> None:
        from sase.agent.names import release_planned_registered_clan_name

        for clan_name, generation, artifacts_dir in self.planned_clan_reservations:
            release_planned_registered_clan_name(
                clan_name,
                generation,
                artifacts_dir,
            )


def empty_clan_prepass() -> _ClanPrepass:
    return _ClanPrepass({}, {}, {}, {}, {}, {}, {}, [])


def prepare_clan_launches(
    *,
    segments: list[str],
    local_xprompts: dict[str, XPrompt],
    cl_name: str,
    project_file: str,
    project_name: str,
    is_home_mode: bool,
    vcs_ref: tuple[str, str] | None,
    segment_template_groups: Sequence[str | None] | None,
    preplanned_fanout_plans: Sequence[LaunchFanoutPlanWire | None] | None,
    default_bare_segments_to_home: bool,
    timestamp_allocator: LaunchTimestampBatchAllocator,
    name_allocator: PlannedNameAllocator,
) -> _ClanPrepass:
    """Resolve rootless clan identity and validate every member before spawn."""
    from sase.project_aliases import canonicalize_project_aliases_in_prompt
    from sase.xprompt._exceptions import DirectiveError
    from sase.xprompt._parsing import normalize_default_vcs_workflow_segment
    from sase.xprompt.directives import has_deferred_start_directive

    # Resolve xprompts before the static clan scan so a declaration or conflict
    # introduced by an xprompt fails the whole batch before timestamp/workspace
    # allocation. Literal fenced/disabled regions remain protected by the
    # shared directive collector used by ``extract_static_clan_directive``.
    from sase.xprompt import (
        LAUNCH_DEFERRED_XPROMPT_NAMES,
        process_xprompt_references,
    )

    effective_segments: list[str] = []
    for segment in segments:
        segment_xprompts = local_xprompts_for_segment(segment, local_xprompts)
        effective_segments.append(
            process_xprompt_references(
                segment,
                extra_xprompts=segment_xprompts or None,
                defer_xprompt_names=LAUNCH_DEFERRED_XPROMPT_NAMES,
            )
            if "#" in segment
            else segment
        )
    directives: list[StaticClanDirective | None] = [
        extract_static_clan_directive(segment) for segment in effective_segments
    ]
    if not any(directive is not None for directive in directives):
        return empty_clan_prepass()

    members_by_raw_clan: dict[str, list[int]] = {}
    for index, directive in enumerate(directives):
        if directive is None:
            continue
        members_by_raw_clan.setdefault(directive.name, []).append(index)

    plans_by_segment: dict[int, LaunchFanoutPlanWire] = {}
    contexts_by_slot: dict[tuple[int, int], SegmentVcsContext] = {}
    artifacts_dirs_by_slot: dict[tuple[int, int], Path] = {}
    planned_names_by_slot: dict[tuple[int, int], str] = {}
    planned_env_names_by_slot: dict[tuple[int, int], str | None] = {}
    membership_env_by_segment: dict[int, str] = {}
    membership_by_segment: dict[int, ClanMembershipPlan] = {}
    reservations: list[tuple[str, str, Path]] = []
    pending_reservations: list[tuple[str, str, Path, bool]] = []

    for index, directive in enumerate(directives):
        if directive is None:
            continue
        prepared_segment = canonicalize_project_aliases_in_prompt(segments[index])
        if default_bare_segments_to_home:
            prepared_segment = normalize_default_vcs_workflow_segment(prepared_segment)
        segment_local_xprompts = local_xprompts_for_segment(
            prepared_segment,
            local_xprompts,
        )
        preplanned = (
            None if preplanned_fanout_plans is None else preplanned_fanout_plans[index]
        )
        plan, _ = plan_segment_fanout(
            prepared_segment,
            segment_local_xprompts=segment_local_xprompts,
            preplanned_fanout_plan=preplanned,
        )
        plan = assign_missing_slot_timestamps(plan, timestamp_allocator)
        plans_by_segment[index] = plan
        has_wait = has_deferred_start_directive(prepared_segment)
        template_group = (
            None if segment_template_groups is None else segment_template_groups[index]
        )
        for slot in plan.slots:
            assert slot.timestamp is not None
            context = resolve_segment_vcs_context(
                prompt=slot.prompt,
                fallback_cl_name=cl_name,
                fallback_project_file=project_file,
                fallback_project_name=project_name,
                fallback_is_home_mode=is_home_mode,
                fallback_vcs_ref=vcs_ref,
                has_wait=has_wait,
            )
            key = (index, slot.slot_index)
            contexts_by_slot[key] = context
            artifacts_dir = future_agent_artifacts_dir(
                project_name=context.project_name,
                timestamp=slot.timestamp,
            )
            artifacts_dirs_by_slot[key] = artifacts_dir
            planned_name, env_name = name_allocator.planned_name_for_prompt(
                slot.prompt,
                artifacts_dir=artifacts_dir,
                template_group=template_group,
            )
            if planned_name is None:
                raise DirectiveError(
                    f"Clan member segment {index + 1} has no plannable agent name"
                )
            from sase.core.agent_identity_facade import normalize_owned_agent_name

            planned_name = normalize_owned_agent_name(planned_name)
            if env_name is not None:
                env_name = normalize_owned_agent_name(env_name)
            planned_names_by_slot[key] = planned_name
            planned_env_names_by_slot[key] = env_name

    # Name planning above records every template token in the batch. Rewrite
    # clan-member wait/fork references only after that shared namespace is
    # complete, then reuse these exact plans during execution.
    for index, plan in list(plans_by_segment.items()):
        plans_by_segment[index] = replace(
            plan,
            slots=[
                replace(
                    slot,
                    prompt=name_allocator.rewrite_template_references(slot.prompt),
                )
                for slot in plan.slots
            ],
        )

    from sase.agent.names import (
        AgentNameTemplateError,
        get_reserved_clan_names,
        is_agent_name_template,
        reserve_registered_clan_name,
        resolve_agent_name_template_reference,
    )
    from sase.artifacts import convert_timestamp_to_artifacts_format
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        foreign_agent_owner_root,
        normalize_owned_agent_name,
    )

    machine_identity = AgentIdentitySnapshot.current()
    resolved_clans_by_raw: dict[str, str] = {}
    for raw_clan, member_indexes in members_by_raw_clan.items():
        resolved_clan = raw_clan
        has_declaration = any(
            directives[index].declared  # type: ignore[union-attr]
            for index in member_indexes
        )
        if is_agent_name_template(raw_clan):
            if not has_declaration:
                try:
                    resolved_clan = resolve_agent_name_template_reference(
                        raw_clan,
                        names=get_reserved_clan_names(),
                    )
                except AgentNameTemplateError:
                    resolved_clan = ""
            else:
                resolved_clan = ""

            if not resolved_clan:
                for index in member_indexes:
                    plan = plans_by_segment[index]
                    for slot in plan.slots:
                        name_template = extract_static_name_directive(slot.prompt)
                        if not name_template or not is_agent_name_template(
                            name_template
                        ):
                            continue
                        planned_name = planned_names_by_slot[(index, slot.slot_index)]
                        resolved_clan = (
                            derive_clan_name_from_member(
                                raw_clan,
                                member_name=planned_name,
                                member_name_template=name_template,
                            )
                            or ""
                        )
                        if resolved_clan:
                            break
                    if resolved_clan:
                        break
                if not resolved_clan:
                    raise DirectiveError(
                        f"Cannot resolve %clan template '{raw_clan}' from any "
                        "member name in this launch"
                    ) from None
        from sase.plan_chain import AGENT_FAMILY_SEPARATOR

        if AGENT_FAMILY_SEPARATOR in resolved_clan:
            raise DirectiveError(
                f"Clan '{resolved_clan}' cannot contain "
                f"'{AGENT_FAMILY_SEPARATOR}': its members would be named "
                f"'{resolved_clan}.<suffix>', placing the family role suffix "
                "outside the final name segment."
            )
        foreign_machine = foreign_agent_owner_root(
            resolved_clan,
            machine_identity,
        )
        if foreign_machine is not None and machine_identity.owner is not None:
            raise DirectiveError(
                f"Clan '{resolved_clan}' belongs to known machine "
                f"'{foreign_machine}' and cannot be launched on local machine "
                f"'{machine_identity.owner.machine_name}'."
            )
        resolved_clans_by_raw[raw_clan] = normalize_owned_agent_name(
            resolved_clan,
            machine_identity,
        )

    members_by_resolved_clan: dict[str, list[int]] = {}
    for raw_clan, member_indexes in members_by_raw_clan.items():
        resolved_clan = resolved_clans_by_raw[raw_clan]
        members_by_resolved_clan.setdefault(resolved_clan, []).extend(member_indexes)

    for resolved_clan, member_indexes in members_by_resolved_clan.items():
        declaration_indexes = [
            index
            for index in member_indexes
            if directives[index].declared  # type: ignore[union-attr]
        ]
        if len(declaration_indexes) > 1:
            raise DirectiveError(
                f"Clan '{resolved_clan}' is declared in more than one prompt; "
                "only one prompt may declare a clan. Other members join with "
                f"%id(<id>, clan={resolved_clan})"
            )

        member_slots = [
            (index, slot)
            for index in member_indexes
            for slot in plans_by_segment[index].slots
        ]
        for index, slot in member_slots:
            agent_name = planned_names_by_slot[(index, slot.slot_index)]
            required_prefix = f"{resolved_clan}."
            if not agent_name.startswith(
                required_prefix
            ) or not agent_name.removeprefix(required_prefix):
                raise DirectiveError(
                    f"Agent '{agent_name}' cannot join clan '{resolved_clan}': "
                    f"clan members must use the '{required_prefix}<suffix>' hood"
                )

        first_index, first_slot = min(
            member_slots,
            key=lambda item: str(item[1].timestamp),
        )
        assert first_slot.timestamp is not None
        generation = convert_timestamp_to_artifacts_format(first_slot.timestamp)
        first_dir = artifacts_dirs_by_slot[(first_index, first_slot.slot_index)]
        pending_reservations.append(
            (resolved_clan, generation, first_dir, bool(declaration_indexes))
        )

    try:
        for (
            clan_name,
            proposed_generation,
            artifacts_dir,
            create_only,
        ) in pending_reservations:
            try:
                generation = reserve_registered_clan_name(
                    clan_name,
                    proposed_generation,
                    artifacts_dir,
                    create_only=create_only,
                )
            except Exception as exc:
                if create_only and "already exists" in str(exc):
                    raise DirectiveError(str(exc)) from None
                raise
            reservations.append((clan_name, generation, artifacts_dir))
            membership = ClanMembershipPlan(
                clan_name=clan_name,
                generation=generation,
            )
            payload = encode_clan_membership_plan(membership)
            for index in members_by_resolved_clan[clan_name]:
                membership_env_by_segment[index] = payload
                membership_by_segment[index] = membership
    except Exception:
        from sase.agent.names import release_planned_registered_clan_name

        for clan_name, generation, artifacts_dir in reservations:
            release_planned_registered_clan_name(
                clan_name,
                generation,
                artifacts_dir,
            )
        raise

    return _ClanPrepass(
        plans_by_segment=plans_by_segment,
        contexts_by_slot=contexts_by_slot,
        artifacts_dirs_by_slot=artifacts_dirs_by_slot,
        planned_names_by_slot=planned_names_by_slot,
        planned_env_names_by_slot=planned_env_names_by_slot,
        membership_env_by_segment=membership_env_by_segment,
        membership_by_segment=membership_by_segment,
        planned_clan_reservations=reservations,
    )
