"""Fast launch adapter for preplanned bead-work prompts."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from sase.agent.launch_cwd_common import internal_agent_name_bypass_for_launch
from sase.agent.launch_types import AgentLaunchResult
from sase.core.paths import sase_projects_dir


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
    (``#bd/work_phase_bead`` / ``#bd/land_epic``) and never fans out.

    This adapter skips the generic discovery -- xprompt swarm expansion,
    per-segment fan-out probing, and the CWD project re-parse -- by feeding
    :func:`launch_multi_prompt_agents` preplanned one-slot fan-out plans. Name
    collision safety is unchanged: the launcher still validates every explicit
    name before spawning.

    Used only when ``sase bead work`` resolved a VCS/ChangeSpec launch context,
    so every segment carries an explicit ``#<workflow>:<ref>`` prefix. The
    no-context case keeps using :func:`launch_agent_from_cwd`.
    """
    if len(segments) != len(segment_extra_env):
        raise ValueError("segment_extra_env must have one entry per bead-work segment")
    if not segments:
        return []

    from sase.agent.launch_projects import (
        enable_known_project_vcs_refs_for_launch_prompt,
    )
    from sase.agent.launch_validation import validate_launch_name_requests
    from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents
    from sase.agent.multi_prompt_references import extract_static_name_directive
    from sase.core.agent_launch_facade import plan_fake_fanout
    from sase.history.prompt import add_or_update_prompt, record_failed_launch_prompt
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
    # below are guaranteed correct, and assert the rendered %name directives
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

    from sase.ace.changespec.project_spec_path import preferred_project_spec_path

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
        validate_launch_name_requests(
            normalized_segments,
            allow_reserved_family_separator_names=allow_bypass,
        )
    except RuntimeError:
        record_failed_launch_prompt(normalized_query)
        raise

    add_or_update_prompt(normalized_query, allow_short=True)

    preplanned_fanout_plans = [
        plan_fake_fanout("multi_prompt", [segment]) for segment in normalized_segments
    ]
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
        )
    except Exception:
        record_failed_launch_prompt(normalized_query)
        raise
