"""Fan-out branches for CWD-based agent launches.

Covers the three ways one submitted prompt becomes several agents: explicit
``---`` multi-prompt segments, ``%r:N`` repeat fan-out, and ``%{a | b}``
alt-split variants. Each helper either launches its slots or returns
``None`` when its fan-out does not apply.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from sase.agent.launch_cwd_common import internal_agent_name_bypass_for_launch
from sase.agent.launch_types import AgentLaunchResult

if TYPE_CHECKING:
    from sase.xprompt.models import XPrompt


def launch_multi_prompt_branch(
    segments: Sequence[str],
    local_xprompts: dict[str, XPrompt],
    *,
    project_file: str,
    project_name: str,
    is_home_mode: bool,
    extra_env: dict[str, str] | None,
    segment_extra_env: Sequence[dict[str, str] | None] | None,
    segment_template_groups: Sequence[str | None],
    segment_swarm_xprompts: Sequence[tuple[str, ...]],
    submitted_query: str,
    record_failed_launch_prompt: Callable[[str], None],
) -> list[AgentLaunchResult]:
    """Launch one agent per ``---`` segment."""
    from sase.agent.launch_projects import (
        enable_known_project_vcs_refs_for_launch_prompt,
    )
    from sase.xprompt._parsing import normalize_default_vcs_workflow_segment

    normalized_segments = [
        normalize_default_vcs_workflow_segment(segment) for segment in segments
    ]
    normalized_query = "\n---\n".join(normalized_segments)
    enable_known_project_vcs_refs_for_launch_prompt(normalized_query)

    # Determine cl_name from VCS refs (lightweight pattern check).
    from sase.workspace_provider import get_ref_patterns

    mp_cl_name = project_name
    mp_vcs_ref: tuple[str, str] | None = None
    for wf_name, pattern in get_ref_patterns().items():
        match = pattern.search(normalized_query)
        if match is not None:
            ref_value = match.group(1) or match.group(2)
            if ref_value:
                mp_cl_name = ref_value
                mp_vcs_ref = (wf_name, ref_value)
                break

    try:
        from sase.agent.launch_validation import (
            AgentNameLaunchCollisionError,
            AgentNameReuseConfirmationRequiredError,
            AgentNameSyntaxError,
            validate_launch_name_requests,
        )

        validate_launch_name_requests(
            normalized_segments,
            allow_reserved_family_separator_names=internal_agent_name_bypass_for_launch(
                extra_env,
                segment_extra_env,
            ),
        )
    except (
        AgentNameLaunchCollisionError,
        AgentNameReuseConfirmationRequiredError,
        AgentNameSyntaxError,
    ):
        record_failed_launch_prompt(submitted_query)
        raise

    from sase.history.prompt import add_or_update_prompt

    add_or_update_prompt(
        submitted_query,
        allow_short=True,
    )
    try:
        from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents

        results = launch_multi_prompt_agents(
            segments=normalized_segments,
            local_xprompts=local_xprompts,
            cl_name=mp_cl_name,
            project_file=project_file,
            project_name=project_name,
            is_home_mode=is_home_mode,
            vcs_ref=mp_vcs_ref,
            extra_env=extra_env,
            segment_extra_env=segment_extra_env,
            segment_template_groups=segment_template_groups,
            segment_swarm_xprompts=segment_swarm_xprompts,
            allow_reserved_family_separator_names=internal_agent_name_bypass_for_launch(
                extra_env,
                segment_extra_env,
            ),
            default_bare_segments_to_home=True,
            multi_agent_prompt_text=submitted_query,
        )
    except Exception:
        record_failed_launch_prompt(submitted_query)
        raise
    return results


def launch_repeat_branch_if_applicable(
    query: str,
    *,
    extra_env: dict[str, str] | None,
    recursive_launch: Callable[..., list[AgentLaunchResult]],
    record_failed_launch_prompt: Callable[[str], None],
) -> list[AgentLaunchResult] | None:
    """Spawn N independent agents when ``%r:N`` is present, else ``None``."""
    from sase.agent.repeat_launcher import (
        REPEAT_ITERATION_ENV,
        REPEAT_NAME_ENV,
        REPEAT_PREV_NAME_ENV,
        REPEAT_TOTAL_ENV,
        RepeatAgentSpec,
        extract_repeat_and_name,
        spawn_repeat_batch,
    )
    from sase.core.agent_launch_facade import reserve_launch_timestamp_batch

    repeat_count, _, _ = extract_repeat_and_name(query)
    if repeat_count is None or repeat_count <= 1:
        return None
    slot_results: list[AgentLaunchResult] = []
    try:
        repeat_timestamps = reserve_launch_timestamp_batch(repeat_count)
        repeat_specs: list[RepeatAgentSpec] = []

        spawn_repeat_batch(
            query,
            base_spawn_fn=repeat_specs.append,
            timestamps=repeat_timestamps,
        )

        from sase.agent.launch_validation import validate_launch_name_requests

        validate_launch_name_requests(
            [spec.prompt for spec in repeat_specs],
            allow_reserved_family_separator_names=internal_agent_name_bypass_for_launch(
                extra_env,
            ),
        )

        def _spawn_repeat_slot(spec: RepeatAgentSpec) -> None:
            assert spec.timestamp is not None
            slot_env = {
                REPEAT_NAME_ENV: spec.name,
                REPEAT_ITERATION_ENV: str(spec.iteration),
                REPEAT_TOTAL_ENV: str(spec.total),
            }
            if spec.prev_name is not None:
                slot_env[REPEAT_PREV_NAME_ENV] = spec.prev_name
            if extra_env:
                slot_env.update(extra_env)
            slot_results.extend(
                recursive_launch(
                    spec.prompt,
                    extra_env=slot_env,
                    timestamp=spec.timestamp,
                )
            )

        for spec in repeat_specs:
            _spawn_repeat_slot(spec)
    except Exception:
        record_failed_launch_prompt(query)
        raise
    return slot_results


def launch_alt_branch_if_applicable(
    query: str,
    *,
    local_xprompts: dict[str, XPrompt],
    project_file: str,
    project_name: str,
    is_home_mode: bool,
    extra_env: dict[str, str] | None,
    record_failed_launch_prompt: Callable[[str], None],
) -> list[AgentLaunchResult] | None:
    """Launch one agent per ``%{a | b}`` alt-split slot, else ``None``."""
    from sase.xprompt.directives import plan_prompt_fanout_variants

    alt_plan = plan_prompt_fanout_variants(query)
    if alt_plan is None and "#" in query:
        from sase.xprompt.processor import (
            LAUNCH_DEFERRED_XPROMPT_NAMES,
            process_xprompt_references,
            prompt_may_reference_xprompt,
        )

        if prompt_may_reference_xprompt(query):
            expanded = process_xprompt_references(
                query,
                defer_xprompt_names=LAUNCH_DEFERRED_XPROMPT_NAMES,
            )
            alt_plan = plan_prompt_fanout_variants(expanded)
    if alt_plan is None:
        return None

    from sase.agent.launch_projects import (
        enable_known_project_vcs_refs_for_launch_prompt,
    )
    from sase.workspace_provider import get_ref_patterns

    enable_known_project_vcs_refs_for_launch_prompt(
        "\n---\n".join(slot.prompt for slot in alt_plan.slots)
    )
    alt_cl_name = project_name
    alt_vcs_ref: tuple[str, str] | None = None
    for wf_name, pattern in get_ref_patterns().items():
        match = pattern.search(query)
        if match is not None:
            ref_value = match.group(1) or match.group(2)
            if ref_value:
                alt_cl_name = ref_value
                alt_vcs_ref = (wf_name, ref_value)
                break

    try:
        from sase.agent.launch_validation import validate_launch_name_requests

        validate_launch_name_requests(
            [slot.prompt for slot in alt_plan.slots],
            allow_reserved_family_separator_names=internal_agent_name_bypass_for_launch(
                extra_env,
            ),
        )
    except RuntimeError:
        record_failed_launch_prompt(query)
        raise

    from sase.history.prompt import add_or_update_prompt

    add_or_update_prompt(query)
    try:
        from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents

        results = launch_multi_prompt_agents(
            segments=[query],
            local_xprompts=local_xprompts,
            cl_name=alt_cl_name,
            project_file=project_file,
            project_name=project_name,
            is_home_mode=is_home_mode,
            vcs_ref=alt_vcs_ref,
            extra_env=extra_env,
            preplanned_fanout_plans=[alt_plan],
            allow_reserved_family_separator_names=internal_agent_name_bypass_for_launch(
                extra_env
            ),
            default_bare_segments_to_home=True,
        )
    except Exception:
        record_failed_launch_prompt(query)
        raise
    return results
