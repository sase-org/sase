"""Fast launch adapter for preplanned bead-work prompts."""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from sase.agent.launch_cwd_common import internal_agent_name_bypass_for_launch
from sase.agent.launch_executor_types import LaunchNameReservationEvidence
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_wire import LaunchFanoutPlanWire
from sase.core.paths import sase_projects_dir

log = logging.getLogger(__name__)


def _canonicalize_bead_work_ref(ref: str) -> str:
    """Return the canonical project name for a bead-work launch ref."""
    from sase.project_aliases import resolve_project_alias_ref

    alias_ref = resolve_project_alias_ref(ref)
    if alias_ref != ref:
        return alias_ref

    try:
        from sase.xprompt._parsing import resolve_known_project_ref
        from sase.xprompt.loader import get_known_project_workspaces

        return resolve_known_project_ref(ref, get_known_project_workspaces()) or ref
    except Exception:
        return ref


def launch_planned_bead_work_agents(
    *,
    segments: Sequence[str],
    segment_extra_env: Sequence[dict[str, str] | None],
    expected_names: Collection[str],
    project_name: str,
) -> list[AgentLaunchResult]:
    """Launch a fully-planned ``sase bead work`` multi-prompt directly.

    ``sase bead work`` already knows everything the generic
    :func:`launch_agents_from_cwd` would otherwise rediscover: the segment
    split, the deterministic per-agent names, the per-segment env, and the
    project context. Every rendered segment references exactly one bead xprompt
    (``#bd/work_phase_bead`` / ``#bd/work_task`` / ``#bd/land_epic``) and
    never fans out.

    This adapter skips the generic discovery -- xprompt swarm expansion,
    per-segment fan-out probing, and the CWD project re-parse -- by feeding
    :func:`launch_multi_prompt_agents` preplanned one-slot fan-out plans. Name
    collision safety is unchanged: the launcher still validates every explicit
    name before spawning.

    Used only when ``sase bead work`` resolved a VCS/Patch launch context,
    so every segment carries an explicit ``#<workflow>:<ref>`` prefix. The
    no-context case keeps using :func:`launch_agent_from_cwd`.
    """
    if len(segments) != len(segment_extra_env):
        raise ValueError("segment_extra_env must have one entry per bead-work segment")
    if not segments:
        return []

    def record_failed_launch_prompt(text: str) -> None:
        from sase.axe.chop_agents import is_chop_launch_env

        if any(is_chop_launch_env(env) for env in segment_extra_env):
            return
        from sase.history.prompt import (
            record_failed_launch_prompt as record_interactive_failed_launch,
        )

        record_interactive_failed_launch(text)

    from sase.agent.launch_projects import (
        enable_known_project_vcs_refs_for_launch_prompt,
    )
    from sase.agent.launch_validation import preflight_launch_name_requests
    from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents
    from sase.agent.multi_prompt_references import extract_static_name_directive
    from sase.history.prompt import add_or_update_prompt
    from sase.project_aliases import canonicalize_project_aliases_in_prompt
    from sase.workspace_provider import get_ref_patterns
    from sase.xprompt._parsing import normalize_default_vcs_workflow_segment
    from sase.xprompt.directives import plan_prompt_fanout_variants

    try:
        normalized_segments = [
            normalize_default_vcs_workflow_segment(
                canonicalize_project_aliases_in_prompt(segment)
            )
            for segment in segments
        ]
    except Exception:
        # Alias canonicalization escapes before the existing validation/launch
        # catch blocks; preserve the original submitted segments in the stash.
        record_failed_launch_prompt("\n---\n".join(segments))
        raise

    # Bead work renders deterministic single-agent segments. Assert no segment
    # carries a parent-side fan-out directive so the preplanned one-slot plans
    # below are guaranteed correct, and assert the rendered %id directives
    # match the planned names so a render bug cannot launch agents under the
    # wrong deterministic names.
    try:
        rendered_names: set[str] = set()
        for index, segment in enumerate(normalized_segments):
            if plan_prompt_fanout_variants(segment) is not None:
                raise ValueError(
                    f"bead-work segment {index} unexpectedly contains a "
                    "fan-out directive"
                )
            name = extract_static_name_directive(segment)
            if name:
                rendered_names.add(name)
        expected = set(expected_names)
        if rendered_names != expected:
            raise ValueError(
                f"bead-work rendered agent names {sorted(rendered_names)} do not "
                f"match planned names {sorted(expected)}"
            )
    except Exception:
        # Pre-launch validation failed before the existing catch blocks; the
        # normalized prompt is the user-submitted bundle to keep recoverable.
        record_failed_launch_prompt("\n---\n".join(normalized_segments))
        raise

    allow_bypass = internal_agent_name_bypass_for_launch(None, segment_extra_env)

    from sase.ace.patch.project_spec_path import preferred_project_spec_path

    project_dir = sase_projects_dir() / project_name
    project_file = preferred_project_spec_path(str(project_dir), project_name)

    normalized_query = "\n---\n".join(normalized_segments)
    enable_known_project_vcs_refs_for_launch_prompt(normalized_query)

    cl_name = project_name
    vcs_ref: tuple[str, str] | None = None
    for wf_name, pattern in get_ref_patterns().items():
        match = pattern.search(normalized_query)
        if match is not None:
            ref_value = match.group(1) or match.group(2)
            if ref_value:
                canonical_ref = _canonicalize_bead_work_ref(ref_value)
                cl_name = canonical_ref
                vcs_ref = (wf_name, canonical_ref)
                break

    try:
        preflight_launch_name_requests(
            normalized_segments,
            allow_reserved_family_separator_names=allow_bypass,
        )
    except RuntimeError:
        record_failed_launch_prompt(normalized_query)
        raise

    add_or_update_prompt(normalized_query, allow_short=True)

    _guard_hard_disabled_bead_work(
        normalized_query,
        segments=normalized_segments,
        record_failed_launch_prompt=record_failed_launch_prompt,
    )

    preplanned_fanout_plans = _preplanned_one_slot_fanout_plans(normalized_segments)
    try:
        reservation_batch = _reserve_planned_bead_work_launch(
            normalized_segments,
            preplanned_fanout_plans=preplanned_fanout_plans,
            cl_name=cl_name,
            project_file=project_file,
            project_name=project_name,
            vcs_ref=vcs_ref,
        )
    except RuntimeError:
        record_failed_launch_prompt(normalized_query)
        raise

    try:
        return launch_multi_prompt_agents(
            segments=normalized_segments,
            local_xprompts={},
            cl_name=cl_name,
            project_file=project_file,
            project_name=project_name,
            is_home_mode=False,
            vcs_ref=vcs_ref,
            segment_extra_env=list(segment_extra_env),
            preplanned_fanout_plans=preplanned_fanout_plans,
            allow_reserved_family_separator_names=allow_bypass,
            default_bare_segments_to_home=True,
            name_reservation_evidence=reservation_batch.name_evidence,
        )
    except Exception as exc:
        _release_unconsumed_bead_work_reservations(
            reservation_batch,
            launched_results=getattr(exc, "results", ()),
        )
        record_failed_launch_prompt(normalized_query)
        raise


@dataclass(frozen=True)
class _BeadWorkReservationBatch:
    """Reservations created for one planned bead-work launch."""

    name_evidence: tuple[LaunchNameReservationEvidence | None, ...]
    clan_reservations: tuple[tuple[str, str, Path], ...]


def _preplanned_one_slot_fanout_plans(
    segments: Sequence[str],
) -> list[LaunchFanoutPlanWire]:
    from sase.core.agent_launch_facade import (
        LaunchTimestampBatchAllocator,
        plan_fake_fanout,
    )

    timestamps = LaunchTimestampBatchAllocator().allocate(len(segments))
    plans: list[LaunchFanoutPlanWire] = []
    for segment, timestamp in zip(segments, timestamps, strict=True):
        plan = plan_fake_fanout("multi_prompt", [segment])
        plans.append(
            replace(
                plan,
                slots=[replace(plan.slots[0], timestamp=timestamp)],
            )
        )
    return plans


def _reserve_planned_bead_work_launch(
    segments: Sequence[str],
    *,
    preplanned_fanout_plans: Sequence[LaunchFanoutPlanWire],
    cl_name: str,
    project_file: str,
    project_name: str,
    vcs_ref: tuple[str, str] | None,
) -> _BeadWorkReservationBatch:
    from sase.agent.multi_prompt_launch_plan import future_agent_artifacts_dir
    from sase.agent.multi_prompt_references import (
        extract_static_clan_directive,
        extract_static_name_directive,
    )
    from sase.agent.multi_prompt_vcs import resolve_segment_vcs_context
    from sase.agent.names import (
        RegisteredNameReservation,
        mutate_registered_name_reservations,
    )
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        normalize_owned_agent_name,
    )
    from sase.xprompt.directives import has_deferred_start_directive

    if len(preplanned_fanout_plans) != len(segments):
        raise ValueError("preplanned_fanout_plans must match bead-work segments")

    identity = AgentIdentitySnapshot.current()
    name_evidence: list[LaunchNameReservationEvidence | None] = []
    artifacts_dirs: list[Path] = []
    reservations: list[RegisteredNameReservation] = []
    clan_names_by_segment: list[str | None] = []
    declared_clans: set[str] = set()
    clan_members: dict[str, list[int]] = {}

    for index, (segment, plan) in enumerate(
        zip(segments, preplanned_fanout_plans, strict=True)
    ):
        if len(plan.slots) != 1:
            raise ValueError("bead-work launch plans must have exactly one slot")
        slot = plan.slots[0]
        if slot.timestamp is None:
            raise ValueError("bead-work launch plans must carry timestamps")
        context = resolve_segment_vcs_context(
            prompt=slot.prompt,
            fallback_cl_name=cl_name,
            fallback_project_file=project_file,
            fallback_project_name=project_name,
            fallback_is_home_mode=False,
            fallback_vcs_ref=vcs_ref,
            has_wait=has_deferred_start_directive(slot.prompt),
        )
        artifacts_dir = future_agent_artifacts_dir(
            project_name=context.project_name,
            timestamp=slot.timestamp,
        )
        artifacts_dirs.append(artifacts_dir)

        raw_name = extract_static_name_directive(segment)
        if raw_name is None:
            name_evidence.append(None)
        else:
            name = normalize_owned_agent_name(raw_name, identity)
            request_id = f"bead-work-name-{index}"
            evidence = LaunchNameReservationEvidence(
                agent_name=name,
                artifacts_dir=str(artifacts_dir),
                request_id=request_id,
            )
            name_evidence.append(evidence)
            reservations.append(
                RegisteredNameReservation(
                    request_id=request_id,
                    operation="reserve_planned",
                    name=name,
                    artifact_dir=artifacts_dir,
                )
            )

        clan_directive = extract_static_clan_directive(segment)
        if clan_directive is None:
            clan_names_by_segment.append(None)
            continue
        clan_name = normalize_owned_agent_name(clan_directive.name, identity)
        clan_names_by_segment.append(clan_name)
        clan_members.setdefault(clan_name, []).append(index)
        if clan_directive.declared:
            declared_clans.add(clan_name)

    clan_reservations: list[tuple[str, str, Path]] = []
    for clan_name in sorted(declared_clans):
        members = clan_members.get(clan_name, [])
        if not members:
            continue
        first_index = min(
            members,
            key=lambda member_index: str(
                preplanned_fanout_plans[member_index].slots[0].timestamp
            ),
        )
        generation = artifacts_dirs[first_index].name
        artifacts_dir = artifacts_dirs[first_index]
        request_id = f"bead-work-clan-{len(clan_reservations)}"
        reservations.append(
            RegisteredNameReservation(
                request_id=request_id,
                operation="reserve_clan",
                name=clan_name,
                artifact_dir=artifacts_dir,
                clan_generation=generation,
                create_only=True,
            )
        )
        clan_reservations.append((clan_name, generation, artifacts_dir))

    if reservations:
        mutate_registered_name_reservations(reservations)

    enriched_evidence: list[LaunchNameReservationEvidence | None] = []
    clan_reservation_by_name = {
        reserved_clan_name: (generation, clan_artifacts_dir)
        for reserved_clan_name, generation, clan_artifacts_dir in clan_reservations
    }
    for evidence_item, segment_clan_name in zip(
        name_evidence,
        clan_names_by_segment,
        strict=True,
    ):
        if evidence_item is None:
            enriched_evidence.append(None)
            continue
        clan_reservation = (
            None
            if segment_clan_name is None
            else clan_reservation_by_name.get(segment_clan_name)
        )
        if segment_clan_name is None or clan_reservation is None:
            enriched_evidence.append(evidence_item)
            continue
        enriched_evidence.append(
            replace(
                evidence_item,
                clan_name=segment_clan_name,
                clan_generation=clan_reservation[0],
            )
        )

    return _BeadWorkReservationBatch(
        name_evidence=tuple(enriched_evidence),
        clan_reservations=tuple(clan_reservations),
    )


def _release_unconsumed_bead_work_reservations(
    batch: _BeadWorkReservationBatch,
    *,
    launched_results: Sequence[AgentLaunchResult],
) -> None:
    launched_agent_names = {
        result.agent_name for result in launched_results if result.agent_name
    }
    launched_artifact_dirs = {
        str(Path(result.artifacts_dir).expanduser().resolve(strict=False))
        for result in launched_results
        if result.artifacts_dir
    }
    from sase.agent.names import (
        release_planned_registered_clan_name,
        release_planned_registered_name,
    )

    for evidence in batch.name_evidence:
        if evidence is None:
            continue
        evidence_artifacts_dir = str(Path(evidence.artifacts_dir).resolve(strict=False))
        if (
            evidence_artifacts_dir in launched_artifact_dirs
            or evidence.agent_name in launched_agent_names
        ):
            continue
        release_planned_registered_name(evidence.agent_name, evidence_artifacts_dir)

    if launched_artifact_dirs or launched_agent_names:
        return
    for clan_name, generation, clan_artifacts_dir in batch.clan_reservations:
        release_planned_registered_clan_name(
            clan_name,
            generation,
            clan_artifacts_dir,
        )


def _guard_hard_disabled_bead_work(
    submitted_query: str,
    *,
    segments: Sequence[str],
    record_failed_launch_prompt: Callable[[str], None],
) -> None:
    """Refuse a confirmed hard-disable block; fail open on guard surprises."""
    from sase.agent.launch_guard import (
        DisabledProviderLaunchError,
        LaunchUnitInput,
        guard_launch_units,
    )

    unit_inputs = tuple(LaunchUnitInput(prompt=segment) for segment in segments)
    try:
        guard_launch_units(submitted_query, units=unit_inputs)
    except DisabledProviderLaunchError:
        record_failed_launch_prompt(submitted_query)
        raise
    except Exception:
        log.warning(
            "provider-disable launch guard failed open; continuing with "
            "bead-work launch",
            exc_info=True,
        )
