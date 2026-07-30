"""Public API and compatibility exports for multi-prompt agent launches.

When a prompt splits into multiple segments (via ``---`` separators), each
segment launches as a separate agent. Planning and execution live in focused
sibling modules; this module retains the established import and patch surface.
"""

from collections.abc import Callable, Sequence

from sase.agent.launch_types import AgentLaunchResult
from sase.agent.multi_prompt_launch_execution import spawn_segments_into
from sase.agent.multi_prompt_references import (
    PlannedNameAllocator as _PlannedNameAllocator,
    StaticClanDirective as _StaticClanDirective,
    extract_static_clan_directive as _extract_static_clan_directive,
    extract_static_name_directive as _extract_static_name_directive,
    has_bare_resume_reference as _has_bare_resume_reference,
    has_bare_wait_directive as _has_bare_wait_directive,
    rewrite_bare_resume_references as _rewrite_bare_resume_references,
    rewrite_bare_wait_directives as _rewrite_bare_wait_directives,
    wait_for_agent_naming as _wait_for_agent_naming,
)
from sase.agent.multi_prompt_vcs import (
    SegmentVcsContext as _SegmentVcsContext,
    extract_vcs_ref as _extract_vcs_ref,
)
from sase.agent.multi_prompt_xprompts import (
    deserialize_local_xprompts as deserialize_local_xprompts,
    extract_called_xprompt_names as _extract_called_xprompt_names,
    local_xprompts_for_segment as _local_xprompts_for_segment,
    serialize_local_xprompts as _serialize_local_xprompts,
)
from sase.core.agent_launch_facade import LaunchTimestampBatchAllocator
from sase.core.agent_launch_wire import LaunchFanoutPlanWire
from sase.xprompt.models import XPrompt

__all__ = [
    "MultiPromptPartialLaunchError",
    "_MultiPromptPartialLaunchError",
    "_SegmentVcsContext",
    "_extract_called_xprompt_names",
    "_extract_static_name_directive",
    "_extract_vcs_ref",
    "_has_bare_resume_reference",
    "_has_bare_wait_directive",
    "_local_xprompts_for_segment",
    "_rewrite_bare_resume_references",
    "_rewrite_bare_wait_directives",
    "_serialize_local_xprompts",
    "_wait_for_agent_naming",
    "deserialize_local_xprompts",
    "launch_multi_prompt_agents",
]


class _MultiPromptPartialLaunchError(RuntimeError):
    """Report a failed segment while retaining previously launched results."""

    def __init__(self, results: list[AgentLaunchResult], cause: BaseException) -> None:
        super().__init__(f"partial multi-prompt launch failed: {cause}")
        self.results = results
        self.cause = cause


MultiPromptPartialLaunchError = _MultiPromptPartialLaunchError


def launch_multi_prompt_agents(
    *,
    segments: list[str],
    local_xprompts: dict[str, XPrompt],
    cl_name: str,
    project_file: str,
    project_name: str,
    is_home_mode: bool,
    vcs_ref: tuple[str, str] | None,
    on_agent_spawned: Callable[[], None] | None = None,
    extra_env: dict[str, str] | None = None,
    segment_extra_env: Sequence[dict[str, str] | None] | None = None,
    segment_template_groups: Sequence[str | None] | None = None,
    segment_swarm_xprompts: Sequence[Sequence[str]] | None = None,
    preplanned_fanout_plans: Sequence[LaunchFanoutPlanWire | None] | None = None,
    allow_reserved_family_separator_names: bool = False,
    allow_hyphenated_names: bool | None = None,
    default_bare_segments_to_home: bool = False,
    multi_agent_prompt_text: str | None = None,
) -> list[AgentLaunchResult]:
    """Launch each segment as a separate agent.

    On partial failure, raise :class:`_MultiPromptPartialLaunchError` with the
    already-spawned results so callers can roll them back.
    """
    if allow_hyphenated_names is not None:
        allow_reserved_family_separator_names = allow_hyphenated_names

    from sase.agent.agent_name_keys import resolve_agent_name_key_markers

    segments = resolve_agent_name_key_markers(segments)
    results: list[AgentLaunchResult] = []
    timestamp_allocator = LaunchTimestampBatchAllocator()

    try:
        spawn_segments_into(
            segments=segments,
            local_xprompts=local_xprompts,
            cl_name=cl_name,
            project_file=project_file,
            project_name=project_name,
            is_home_mode=is_home_mode,
            vcs_ref=vcs_ref,
            on_agent_spawned=on_agent_spawned,
            extra_env=extra_env,
            segment_extra_env=segment_extra_env,
            segment_template_groups=segment_template_groups,
            segment_swarm_xprompts=segment_swarm_xprompts,
            preplanned_fanout_plans=preplanned_fanout_plans,
            allow_reserved_family_separator_names=(
                allow_reserved_family_separator_names
            ),
            default_bare_segments_to_home=default_bare_segments_to_home,
            multi_agent_prompt_text=multi_agent_prompt_text,
            timestamp_allocator=timestamp_allocator,
            results=results,
            wait_for_agent_naming=_wait_for_agent_naming,
        )
    except Exception as exc:
        if results:
            raise _MultiPromptPartialLaunchError(results, exc) from exc
        raise
    return results
