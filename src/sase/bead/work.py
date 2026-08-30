"""DAG → wave plan → multi-prompt rendering for ``sase bead work`` automation.

Pure-library helpers that the ``sase bead work <epic_id>`` handler will call
to (a) compute a phase-wave schedule from an epic's dependency DAG and
(b) render a multi-prompt that ``launch_agent_from_cwd`` can dispatch.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from sase.bead import db
from sase.bead.close_history_codec import close_history_to_dicts
from sase.bead.config import get_big_epic_phase_threshold
from sase.bead.model import Dependency, Issue, PhaseSize
from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV
from sase.core.model_route_facade import size_model_route_alias
from sase.core.rust import require_rust_binding
from sase.llm_provider.config import format_model_directive_value
from sase.llm_provider.config import select_epic_land_model_expression

if TYPE_CHECKING:
    from sase.xprompt.directive_edit import PromptWaitDirective
    from sase.xprompt.workflow_models import Workflow

SASE_BEAD_ID_ENV = "SASE_BEAD_ID"
SASE_EPIC_PLAN_REF_ENV = "SASE_EPIC_PLAN_REF"
SASE_EPIC_PLAN_SNAPSHOT_ENV = "SASE_EPIC_PLAN_SNAPSHOT"
SASE_EPIC_BEAD_ID_ENV = "SASE_EPIC_BEAD_ID"
SASE_EPIC_CLAN_TRIBE_ENV = "SASE_EPIC_CLAN_TRIBE"
SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV = "SASE_EPIC_CLAN_SUMMARY_SCRIPT"
SASE_PHASE_BEAD_ID_ENV = "SASE_PHASE_BEAD_ID"
EPIC_CLAN_TRIBE = "epic"
EPIC_CLAN_SUMMARY_SCRIPT = "sase_clan_summary_epic"


@dataclass(frozen=True)
class _PhaseAssignment:
    """One phase bead's assignment to an agent in a wave."""

    bead_id: str
    agent_name: str
    waits_on: tuple[str, ...]
    blocker_bead_ids: tuple[str, ...]
    wave: int
    model: str = ""
    size: PhaseSize | None = None


@dataclass(frozen=True)
class EpicWorkPlan:
    """Wave-partitioned plan to work an epic plus its final land agent."""

    epic_id: str
    launch_tag_id: str
    total_phase_count: int
    phase_bead_ids: tuple[str, ...]
    waves: tuple[tuple[_PhaseAssignment, ...], ...]
    land_agent_name: str
    land_waits_on: tuple[str, ...]
    land_model: str = ""


@dataclass(frozen=True)
class VCSLaunchContext:
    """VCS launch wrapper for project-scoped epic work."""

    vcs_workflow: str
    project_name: str


@dataclass(frozen=True)
class PatchLaunchContext(VCSLaunchContext):
    """VCS launch wrapper for Patch-attached epic work."""

    changespec_name: str
    bug_id: str = ""


class EpicPlanError(ValueError):
    """Base error for epic-work-plan construction failures."""


class _CycleError(EpicPlanError):
    """Raised when the open phase children form a dependency cycle."""


class _CrossEpicBlockerError(EpicPlanError):
    """Raised when a phase has an out-of-epic blocker that is not closed."""


def _build_epic_work_plan(
    source: sqlite3.Connection | str | Path,
    epic_id: str,
) -> EpicWorkPlan:
    """Compute a wave-partitioned plan to work an epic's authored phases.

    Non-closed phase children are layered Kahn-style: wave 0 is every phase
    whose in-epic non-closed blockers are all already satisfied (closed);
    wave *k* is every phase whose remaining in-epic non-closed blockers fall
    in waves < *k*. An epic with authored phases that are all closed returns a
    land-only plan with no phase waves.

    Raises:
        EpicPlanError: If the epic does not exist, is not a plan-type bead,
            or has no authored phase children.
        _CrossEpicBlockerError: If a phase depends on an out-of-epic blocker
            that is not closed.
        _CycleError: If the open phases form a dependency cycle.
    """
    if isinstance(source, sqlite3.Connection):
        return _build_epic_work_plan_from_issues(db.list_issues(source), epic_id)

    from sase.core.bead_read_facade import resolve_id

    epic_id = resolve_id(source, epic_id)
    binding = require_rust_binding("bead_build_epic_work_plan")
    try:
        payload: dict[str, Any] = binding(str(source), epic_id)
    except ValueError as exc:
        _raise_epic_plan_error(exc)
    return _plan_from_payload(payload)


def build_epic_work_plan_from_beads_dir(
    beads_dir: str | Path,
    epic_id: str,
) -> EpicWorkPlan:
    """Compute an epic work plan directly from a bead store through Rust."""
    return _build_epic_work_plan(beads_dir, epic_id)


def _build_epic_work_plan_from_issues(
    issues: list[Issue],
    epic_id: str,
) -> EpicWorkPlan:
    binding = require_rust_binding("bead_build_epic_work_plan_from_issues")
    try:
        payload: dict[str, Any] = binding(
            [_issue_to_wire_dict(issue) for issue in issues],
            epic_id,
        )
    except ValueError as exc:
        _raise_epic_plan_error(exc)
    return _plan_from_payload(payload)


def _plan_from_payload(payload: dict[str, Any]) -> EpicWorkPlan:
    epic_id = str(payload["epic_id"])
    raw_waves = [list(wave) for wave in payload["waves"]]
    agent_names = {
        str(assignment["agent_name"]): _epic_clan_agent_name(
            epic_id,
            str(assignment["agent_name"]),
        )
        for wave in raw_waves
        for assignment in wave
    }

    def _membership_name(value: object) -> str:
        raw_name = str(value)
        return agent_names.get(raw_name, _epic_clan_agent_name(epic_id, raw_name))

    return EpicWorkPlan(
        epic_id=epic_id,
        launch_tag_id=str(payload.get("launch_tag_id", epic_id)),
        total_phase_count=int(
            payload.get(
                "total_phase_count",
                sum(len(wave) for wave in payload["waves"]),
            )
        ),
        waves=tuple(
            tuple(
                _PhaseAssignment(
                    bead_id=str(assignment["bead_id"]),
                    agent_name=_membership_name(assignment["agent_name"]),
                    waits_on=tuple(
                        _membership_name(v) for v in assignment.get("waits_on", [])
                    ),
                    blocker_bead_ids=tuple(
                        str(v) for v in assignment["blocker_bead_ids"]
                    ),
                    wave=int(assignment["wave"]),
                    model=str(assignment.get("model", "")),
                    size=(
                        PhaseSize(str(assignment["size"]))
                        if assignment.get("size")
                        else None
                    ),
                )
                for assignment in wave
            )
            for wave in raw_waves
        ),
        phase_bead_ids=tuple(str(v) for v in payload["phase_bead_ids"]),
        land_agent_name=_epic_clan_agent_name(
            epic_id,
            str(payload["land_agent_name"]),
        ),
        land_waits_on=tuple(
            _membership_name(v) for v in payload.get("land_waits_on", [])
        ),
        land_model=str(payload.get("land_model", "")),
    )


def _epic_clan_agent_name(epic_id: str, agent_name: str) -> str:
    prefix = f"{epic_id}."
    return agent_name if agent_name.startswith(prefix) else f"{prefix}{agent_name}"


def _issue_to_wire_dict(issue: Issue) -> dict[str, object]:
    return {
        "id": issue.id,
        "title": issue.title,
        "status": issue.status.value,
        "issue_type": issue.issue_type.value,
        "tier": issue.tier.value if issue.tier else None,
        "parent_id": issue.parent_id,
        "owner": issue.owner,
        "assignee": issue.assignee,
        "created_at": issue.created_at,
        "created_by": issue.created_by,
        "updated_at": issue.updated_at,
        "closed_at": issue.closed_at,
        "close_reason": issue.close_reason,
        "resolution": issue.resolution.value if issue.resolution else None,
        "description": issue.description,
        "notes": issue.notes_text,
        "design": issue.design,
        "model": issue.model,
        "size": issue.size.value if issue.size else None,
        "is_ready_to_work": issue.is_ready_to_work,
        "changespec_name": issue.changespec_name,
        "changespec_bug_id": issue.changespec_bug_id,
        "dependencies": [_dependency_to_wire_dict(dep) for dep in issue.dependencies],
        "plus_one_evidence": [
            {
                "timestamp": evidence.timestamp,
                "reporter": evidence.reporter,
                "note": evidence.note,
                "refs": evidence.refs,
            }
            for evidence in issue.plus_one_evidence
        ],
        "close_history": close_history_to_dicts(issue.close_history),
    }


def _dependency_to_wire_dict(dep: Dependency) -> dict[str, str]:
    return {
        "issue_id": dep.issue_id,
        "depends_on_id": dep.depends_on_id,
        "created_at": dep.created_at,
        "created_by": dep.created_by,
    }


def _raise_epic_plan_error(exc: ValueError) -> None:
    kind, message = _split_rust_error(str(exc))
    if kind == "cycle":
        raise _CycleError(message) from exc
    if kind == "cross_epic_blocker":
        raise _CrossEpicBlockerError(message) from exc
    raise EpicPlanError(message) from exc


def _split_rust_error(text: str) -> tuple[str, str]:
    if ": " not in text:
        return "validation", text
    kind, message = text.split(": ", 1)
    return kind, message


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
        f"#{vcs_context.vcs_workflow}:{vcs_context.project_name}",
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
        if plan.land_waits_on:
            land_lines.append(f"%w:{','.join(plan.land_waits_on)}")
        land_lines.extend(f"%w(bead={bead_id})" for bead_id in plan.phase_bead_ids)
        if not plan.land_waits_on:
            land_lines.extend(_extra_wait_lines(extra_waits))
        land_lines.append(f"#{land_epic_xprompt.name}:{plan.epic_id}")
        segments.append("\n".join(land_lines))

    return "\n---\n".join(segments)


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


def epic_work_segment_env(
    plan: EpicWorkPlan,
    *,
    plan_ref: str,
    plan_snapshot: str | None = None,
    launch_names: frozenset[str] | None = None,
) -> tuple[dict[str, str], ...]:
    """Return role metadata for each epic-work launch segment.

    ``SASE_BEAD_ID`` remains the commit-attribution value for the child. The
    narrowly scoped epic fields are consumed while the child's
    ``agent_meta.json`` marker is written, giving ACE a plan/role association
    without overloading ``SASE_PLAN`` or consulting bead storage.
    """
    envs: list[dict[str, str]] = []
    for wave in plan.waves:
        for assignment in wave:
            if launch_names is not None and assignment.agent_name not in launch_names:
                continue
            env = _bead_env(
                assignment.bead_id,
                epic_id=plan.epic_id,
                plan_ref=plan_ref,
                plan_snapshot=plan_snapshot,
                phase_bead_id=assignment.bead_id,
            )
            if not envs:
                env[SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV] = EPIC_CLAN_SUMMARY_SCRIPT
            envs.append(env)
    if launch_names is None or plan.land_agent_name in launch_names:
        env = _bead_env(
            plan.epic_id,
            epic_id=plan.epic_id,
            plan_ref=plan_ref,
            plan_snapshot=plan_snapshot,
        )
        if not envs:
            env[SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV] = EPIC_CLAN_SUMMARY_SCRIPT
        envs.append(env)
    return tuple(envs)


def task_work_segment_env(bead_id: str) -> tuple[dict[str, str], ...]:
    """Return the single launch environment for a task-bead worker."""
    return (
        {
            SASE_BEAD_ID_ENV: bead_id,
            INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
        },
    )


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


def _bead_env(
    bead_id: str,
    *,
    epic_id: str,
    plan_ref: str,
    plan_snapshot: str | None = None,
    phase_bead_id: str | None = None,
) -> dict[str, str]:
    env = {
        SASE_BEAD_ID_ENV: bead_id,
        SASE_EPIC_BEAD_ID_ENV: epic_id,
        SASE_EPIC_CLAN_TRIBE_ENV: EPIC_CLAN_TRIBE,
        INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
    }
    if plan_ref:
        env[SASE_EPIC_PLAN_REF_ENV] = plan_ref
    if plan_snapshot:
        env[SASE_EPIC_PLAN_SNAPSHOT_ENV] = plan_snapshot
    if phase_bead_id:
        env[SASE_PHASE_BEAD_ID_ENV] = phase_bead_id
    return env


def _segment_prefix(
    ctx: VCSLaunchContext | None,
    is_first_phase: bool,
) -> list[str]:
    if ctx is None:
        return []

    if isinstance(ctx, PatchLaunchContext):
        ref = ctx.project_name if is_first_phase else ctx.changespec_name
    else:
        ref = ctx.project_name
    line = f"#{ctx.vcs_workflow}:{ref}"
    if is_first_phase and isinstance(ctx, PatchLaunchContext):
        line = f"{line} {_pr_reference(ctx)}"
    return [line]


def _pr_reference(ctx: PatchLaunchContext) -> str:
    if ctx.bug_id:
        return f"#pr(name={ctx.changespec_name}, bug_id={ctx.bug_id})"
    return f"#pr:{ctx.changespec_name}"
