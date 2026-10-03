"""Multi-prompt segment expansion for CWD-based agent launches."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.agent.force_reuse_bead import SASE_AGENT_FORCE_REUSE_BEAD_ENV

if TYPE_CHECKING:
    from sase.agent.launch_guard import LaunchUnitInput
    from sase.macro.models import Macro


@dataclass
class _ExpandedLaunchSegments:
    """Post-swarm-expansion segments plus per-slot launch metadata."""

    segments: list[str]
    template_groups: list[str | None]
    swarm_macros: list[tuple[str, ...]]
    segment_extra_env: list[dict[str, str] | None] | None
    local_macros: dict[str, Macro]


def expand_launch_segments(
    query: str,
    *,
    launch_units: Sequence[LaunchUnitInput] | None = None,
    segment_extra_env: Sequence[dict[str, str] | None] | None = None,
) -> _ExpandedLaunchSegments:
    """Expand ACE units or ``---`` segments plus macro swarms into slots."""
    from sase.agent.launch_projects import (
        enable_known_project_vcs_refs_for_launch_prompt,
    )
    from sase.agent.multi_prompt import parse_multi_prompt
    from sase.agent.macro_swarm import expand_macro_swarms_with_metadata

    multi = parse_multi_prompt(query)
    enable_known_project_vcs_refs_for_launch_prompt("\n---\n".join(multi.segments))
    expanded_segment_extra_env: list[dict[str, str] | None] | None = None
    expanded_segment_template_groups: list[str | None] = []
    expanded_segment_swarm_macros: list[tuple[str, ...]] = []
    if launch_units is not None:
        if segment_extra_env is not None and len(segment_extra_env) != len(
            launch_units
        ):
            raise ValueError("segment_extra_env must have one entry per launch unit")
        expanded_segments = [unit.prompt for unit in launch_units]
        expanded_segment_template_groups = [
            unit.template_group for unit in launch_units
        ]
        expanded_segment_swarm_macros = [
            tuple(unit.swarm_macros) for unit in launch_units
        ]
        if segment_extra_env is not None:
            expanded_segment_extra_env = list(segment_extra_env)
    elif segment_extra_env is not None:
        if len(segment_extra_env) != len(multi.segments):
            raise ValueError(
                "segment_extra_env must have one entry per multi-prompt segment"
            )
        from itertools import count

        expanded_segments = []
        expanded_segment_extra_env = []
        # Share one invocation counter across the per-segment calls so two
        # invocations of the same macro swarm get distinct template
        # groups, exactly as the single-call branch below allocates them.
        macro_group_counter = count()
        macro_qualification_counter = count()
        for segment, env in zip(multi.segments, segment_extra_env, strict=True):
            segment_expansions = expand_macro_swarms_with_metadata(
                [segment],
                multi.local_macros,
                group_counter=macro_group_counter,
                qualification_counter=macro_qualification_counter,
            )
            expanded_segments.extend(record.prompt for record in segment_expansions)
            if env is not None and SASE_AGENT_FORCE_REUSE_BEAD_ENV in env:
                # The force-reuse bead marker is a one-shot authorization
                # (consumed by run_agent_runner_bootstrap.py) tied to exactly
                # one killed agent's name, so only the first macro-swarm
                # slot of this segment may claim it; other markers (e.g. a
                # bead epic/task association) apply to every expanded slot.
                expanded_segment_extra_env.extend(
                    env if slot_index == 0 else None
                    for slot_index, _record in enumerate(segment_expansions)
                )
            else:
                expanded_segment_extra_env.extend([env] * len(segment_expansions))
            expanded_segment_template_groups.extend(
                record.template_group for record in segment_expansions
            )
            expanded_segment_swarm_macros.extend(
                record.swarm_macros for record in segment_expansions
            )
    else:
        expanded_records = expand_macro_swarms_with_metadata(
            multi.segments, multi.local_macros
        )
        expanded_segments = [record.prompt for record in expanded_records]
        expanded_segment_template_groups = [
            record.template_group for record in expanded_records
        ]
        expanded_segment_swarm_macros = [
            record.swarm_macros for record in expanded_records
        ]

    return _ExpandedLaunchSegments(
        segments=expanded_segments,
        template_groups=expanded_segment_template_groups,
        swarm_macros=expanded_segment_swarm_macros,
        segment_extra_env=expanded_segment_extra_env,
        local_macros=multi.local_macros,
    )
