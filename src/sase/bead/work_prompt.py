"""Prompt rendering for ``sase bead work`` automation.

Renders the multi-prompt string that ``launch_agent_from_cwd`` dispatches:
one ``---``-separated segment per phase agent plus a final land segment.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

from sase.bead.config import get_big_epic_phase_threshold
from sase.bead.model import PhaseSize
from sase.bead.work_plan import EpicWorkPlan
from sase.bead.work_types import (
    EPIC_CLAN_SUMMARY_SCRIPT,
    EPIC_CLAN_TRIBE,
    PatchLaunchContext,
    VCSLaunchContext,
)
from sase.core.model_route_facade import size_model_route_alias
from sase.llm_provider.config import format_model_directive_value
from sase.llm_provider.config import select_epic_land_model_expression

if TYPE_CHECKING:
    from sase.xprompt.directive_edit import PromptWaitDirective
    from sase.xprompt.workflow_models import Workflow


def epic_land_model_directive_value(
    explicit_model: str | None,
    *,
    total_phase_count: int,
) -> str:
    """Return the authoritative ``%model`` value for an epic land agent.

    Explicit plan models always win. Otherwise, the authored phase-count
    threshold selects ``llm_provider.epic_lander_model`` or
    ``llm_provider.big_epic_lander_model``.
    """
    model = select_epic_land_model_expression(
        explicit_model,
        total_phase_count=total_phase_count,
        threshold=get_big_epic_phase_threshold(),
    )
    return format_model_directive_value(model)


def phase_model_directive_value(
    explicit_model: str | None,
    *,
    size: PhaseSize | str | None,
) -> str:
    """Return the authoritative ``%model`` value for a phase agent."""
    if explicit_model:
        return format_model_directive_value(explicit_model)
    return size_model_route_alias(_phase_size(size).value)


def task_model_directive_value(
    explicit_model: str | None,
    *,
    size: PhaseSize | str | None,
) -> str:
    """Return the authoritative ``%model`` value for a task-bead agent."""
    if explicit_model:
        return format_model_directive_value(explicit_model)
    return phase_model_directive_value(None, size=size)


def render_task_prompt(
    bead_id: str,
    *,
    model: str = "",
    size: PhaseSize | str | None = None,
    work_task_xprompt: Workflow,
    vcs_context: VCSLaunchContext,
    feedback: str | None = None,
) -> str:
    """Render one deterministic, single-segment task-bead launch prompt."""
    _validate_vcs_context(vcs_context)
    feedback_text = feedback.strip() if feedback else ""
    if feedback_text and _contains_top_level_segment_separator(feedback_text):
        raise ValueError(
            "task launch feedback cannot contain a top-level '---' "
            "prompt segment separator"
        )

    lines = [
        _vcs_launch_prefix(vcs_context.vcs_workflow, vcs_context.project_name),
        f"%id(!{bead_id}, bead={bead_id})",
        f"%m:{task_model_directive_value(model, size=size)}",
        f"#{work_task_xprompt.name}:{bead_id}",
    ]
    if phase_requires_plan(size):
        lines.append("#plan")
    if feedback_text:
        lines.append(feedback_text)
    return "\n".join(lines)


def phase_requires_plan(size: PhaseSize | str | None) -> bool:
    """Return whether a phase needs a separate planning handoff."""
    return _phase_size(size) in {PhaseSize.LARGE, PhaseSize.XLARGE}


def render_multi_prompt(
    plan: EpicWorkPlan,
    work_phase_xprompt: Workflow,
    land_epic_xprompt: Workflow,
    vcs_context: VCSLaunchContext | None = None,
    patch_context: PatchLaunchContext | None = None,
    *,
    declare_clan: bool = True,
    launch_names: frozenset[str] | None = None,
    extra_waits: PromptWaitDirective | None = None,
    capacity: int | None = None,
    segment_capacity: Mapping[str, int] | None = None,
) -> str:
    """Render *plan* as a ``---``-separated multi-prompt string.

    The first phase declares ``%clan(<epic_id>, tribe=epic)`` when
    ``declare_clan`` is true. Its full-name ``%id`` associates the phase bead;
    every later phase combines its suffix, clan membership, and phase bead in
    one ``%id``. The final land segment similarly joins the clan while
    associating the epic bead. When re-working an existing epic clan, callers
    pass ``declare_clan=False`` so every segment uses the join form. Segments
    invoke the corresponding work xprompt, and the final land segment invokes
    ``#<land_epic_xprompt.name>:<epic_id>``, and waits on every launched phase
    agent. Tag-resolved xprompt names are substituted into the ``#...``
    references so user overrides flow through unchanged.

    The emitted ``%id`` directives use the force-reuse prefix
    (``%id:!<name>``) so re-running ``sase bead work`` after a prior failed
    or killed launch wipes stale owner records before relaunching. Callers
    are responsible for the wipe/rewrite handshake before passing the rendered
    prompt to the launcher.

    When *vcs_context* is provided, every segment is prefixed with the project
    VCS xprompt. When *patch_context* is provided, the first phase segment
    targets the project ref and includes ``#pr`` to create/own the Patch;
    later phase segments and the land segment target the Patch ref
    directly.

    When *extra_waits* is provided, its agents and beads are appended after
    each unblocked segment's existing wait lines and before its ``#<xprompt>``
    line. Unblocked means a phase whose ``waits_on`` is empty, or the land
    segment when ``plan.land_waits_on`` is empty. Dependent segments inherit
    the wait transitively and do not repeat it.

    When *segment_capacity* is a non-empty mapping, each phase and land
    segment renders ``%queue(capacity=...)`` from its agent-name entry.
    Otherwise *capacity* is used uniformly. ``None`` (the default) emits no
    ``%queue`` line.
    """
    if vcs_context is not None and patch_context is not None:
        raise ValueError("provide either vcs_context or patch_context, not both")
    launch_context = patch_context or vcs_context
    if launch_context is not None:
        _validate_vcs_context(launch_context)
    if patch_context is not None:
        _validate_patch_context(patch_context)

    segments: list[str] = []
    is_first_phase = True
    for wave in plan.waves:
        for assignment in wave:
            if launch_names is not None and assignment.agent_name not in launch_names:
                continue
            lines = _segment_prefix(launch_context, is_first_phase)
            declares_clan = declare_clan and is_first_phase
            is_first_phase = False
            lines.extend(
                _clan_identity_directives(
                    plan.epic_id,
                    assignment.agent_name,
                    bead_id=assignment.bead_id,
                    declare=declares_clan,
                )
            )
            model_value = phase_model_directive_value(
                assignment.model,
                size=assignment.size,
            )
            lines.append(f"%model:{model_value}")
            lines.append("%auto")
            lines.extend(
                _queue_capacity_lines(
                    _capacity_for_agent(
                        assignment.agent_name,
                        capacity=capacity,
                        segment_capacity=segment_capacity,
                    )
                )
            )
            if assignment.waits_on:
                lines.append(f"%w:{','.join(assignment.waits_on)}")
            lines.extend(
                f"%w(bead={bead_id})" for bead_id in assignment.blocker_bead_ids
            )
            if not assignment.waits_on:
                lines.extend(_extra_wait_lines(extra_waits))
            lines.append(f"#{work_phase_xprompt.name}:{assignment.bead_id}")
            if phase_requires_plan(assignment.size):
                lines.append("#plan")
            segments.append("\n".join(lines))

    if launch_names is None or plan.land_agent_name in launch_names:
        land_lines = _segment_prefix(launch_context, is_first_phase=False)
        land_lines.extend(
            _clan_identity_directives(
                plan.epic_id,
                plan.land_agent_name,
                bead_id=plan.epic_id,
                declare=declare_clan and is_first_phase,
            )
        )
        land_model = epic_land_model_directive_value(
            plan.land_model,
            total_phase_count=plan.total_phase_count,
        )
        land_lines.append(f"%model:{land_model}")
        land_lines.append("%auto")
        land_lines.extend(
            _queue_capacity_lines(
                _capacity_for_agent(
                    plan.land_agent_name,
                    capacity=capacity,
                    segment_capacity=segment_capacity,
                )
            )
        )
        if plan.land_waits_on:
            land_lines.append(f"%w:{','.join(plan.land_waits_on)}")
        land_lines.extend(f"%w(bead={bead_id})" for bead_id in plan.phase_bead_ids)
        if not plan.land_waits_on:
            land_lines.extend(_extra_wait_lines(extra_waits))
        land_lines.append(f"#{land_epic_xprompt.name}:{plan.epic_id}")
        segments.append("\n".join(land_lines))

    return "\n---\n".join(segments)


def _capacity_for_agent(
    agent_name: str,
    *,
    capacity: int | None,
    segment_capacity: Mapping[str, int] | None,
) -> int | None:
    """Return the queue budget for *agent_name*, preferring a per-agent map."""
    if segment_capacity:
        return segment_capacity.get(agent_name)
    return capacity


def _queue_capacity_lines(capacity: int | None) -> list[str]:
    """Render the epic-launch capacity directive, preserving omitted defaults."""
    if capacity is None:
        return []
    from sase.xprompt.queue_directive import format_queue_directive

    line = format_queue_directive(capacity=capacity)
    return [line] if line else []


def _extra_wait_lines(extra_waits: PromptWaitDirective | None) -> list[str]:
    """Render approval/CLI extra waits after a segment's intra-epic waits."""
    if not extra_waits:
        return []
    lines: list[str] = []
    if extra_waits.agents:
        lines.append(f"%w:{','.join(extra_waits.agents)}")
    lines.extend(f"%w(bead={bead_id})" for bead_id in extra_waits.beads)
    return lines


def _phase_size(size: PhaseSize | str | None) -> PhaseSize:
    """Normalize missing legacy size metadata to the small-phase behavior."""
    if size is None or size == "":
        return PhaseSize.SMALL
    return size if isinstance(size, PhaseSize) else PhaseSize(size)


def _clan_identity_directives(
    clan_name: str,
    agent_name: str,
    *,
    bead_id: str,
    declare: bool,
) -> list[str]:
    prefix = f"{clan_name}."
    member_id = agent_name.removeprefix(prefix)
    if member_id == agent_name or not member_id:
        raise ValueError(
            f"Epic agent name '{agent_name}' must be inside clan hood "
            f"'{prefix}<suffix>'"
        )
    if declare:
        return [
            f"%id(!{agent_name}, bead={bead_id})",
            (
                f"%clan({clan_name}, tribe={EPIC_CLAN_TRIBE}, "
                f"summary_script={EPIC_CLAN_SUMMARY_SCRIPT})"
            ),
        ]
    return [f"%id(!{member_id}, clan={clan_name}, bead={bead_id})"]


def _contains_top_level_segment_separator(text: str) -> bool:
    """Return whether *text* has an unfenced prompt segment separator."""
    from sase.xprompt._fenced_blocks import protect_fenced_blocks

    protected = protect_fenced_blocks(text, [])
    return bool(re.search(r"^---\s*$", protected, flags=re.MULTILINE))


def _validate_vcs_context(ctx: VCSLaunchContext) -> None:
    missing = []
    if not ctx.vcs_workflow:
        missing.append("vcs_workflow")
    if not ctx.project_name:
        missing.append("project_name")
    if missing:
        raise ValueError(
            "VCS launch context is missing required field(s): " + ", ".join(missing)
        )


def _validate_patch_context(ctx: PatchLaunchContext) -> None:
    missing = []
    if not ctx.changespec_name:
        missing.append("changespec_name")
    if missing:
        raise ValueError(
            "Patch launch context is missing required field(s): " + ", ".join(missing)
        )


def _vcs_launch_prefix(vcs_workflow: str, project_name: str) -> str:
    """Return the launch prefix for *project_name*, defaulting to tags.

    Produces ``+<project>`` when the name is in the tag grammar and known
    to the catalog, falling back to ``#<workflow>:<name>`` otherwise. Patch
    callers keep their ``#gh:<patch>`` spelling and never call this.
    """

    fallback = f"#{vcs_workflow}:{project_name}"
    try:
        from sase.project_tags import project_tag_for

        tag = project_tag_for(project_name)
    except Exception:  # noqa: BLE001 - generators degrade to `#wf:` refs.
        return fallback
    if tag.startswith(("+", "#")):
        return tag
    return fallback


def _segment_prefix(
    ctx: VCSLaunchContext | None,
    is_first_phase: bool,
) -> list[str]:
    if ctx is None:
        return []

    if isinstance(ctx, PatchLaunchContext):
        if not is_first_phase:
            # Later Patch phases keep `#gh:<patch>`.
            line = f"#{ctx.vcs_workflow}:{ctx.changespec_name}"
            return [line]
        ref = ctx.project_name
    else:
        ref = ctx.project_name
    line = _vcs_launch_prefix(ctx.vcs_workflow, ref)
    if is_first_phase and isinstance(ctx, PatchLaunchContext):
        line = f"{line} {_pr_reference(ctx)}"
    return [line]


def _pr_reference(ctx: PatchLaunchContext) -> str:
    if ctx.bug_id:
        return f"#pr(name={ctx.changespec_name}, bug_id={ctx.bug_id})"
    return f"#pr:{ctx.changespec_name}"


__all__ = [
    "_capacity_for_agent",
    "_clan_identity_directives",
    "_contains_top_level_segment_separator",
    "_extra_wait_lines",
    "_phase_size",
    "_pr_reference",
    "_queue_capacity_lines",
    "_segment_prefix",
    "_validate_patch_context",
    "_validate_vcs_context",
    "_vcs_launch_prefix",
    "epic_land_model_directive_value",
    "phase_model_directive_value",
    "phase_requires_plan",
    "render_multi_prompt",
    "render_task_prompt",
    "task_model_directive_value",
]
