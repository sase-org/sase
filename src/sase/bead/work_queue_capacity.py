"""Per-segment ``--capacity`` resolution for epic ``sase bead work``.

``sase bead work --capacity N`` stamps a ``%queue(capacity=...)`` budget into
every phase and land segment. An xprompt that authors a queue weight greater
than ``N`` is raised to ``ceil(weight)`` once ``queue_capacity_budget`` is on,
so a uniform ``N=1`` stays satisfiable for the default-weight builtin lander.

This module probes only the queue-relevant xprompt text (never ``%id``,
``%clan``, ``%w``, ``%model``, or VCS prefixes), then translates ``N`` into a
per-agent budget: ``max(N, ceil(authored_weight))`` with the flag on, and
plain ``N`` with the flag off. A colliding xprompt-authored ``capacity`` is a
pre-flight error so the runner never sees it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple

from sase.bead.work import EpicWorkPlan, phase_requires_plan
from sase.feature_flags.registry import FeatureFlag
from sase.feature_flags.snapshot import current_flags
from sase.xprompt._exceptions import XPromptError
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.processor import (
    LAUNCH_DEFERRED_XPROMPT_NAMES,
    process_xprompt_references,
)
from sase.xprompt.queue_directive import format_queue_directive
from sase.xprompt.workflow_models import Workflow

if TYPE_CHECKING:
    from sase.xprompt._directive_types import PromptDirectives
    from sase.xprompt.models import XPrompt

_DEFAULT_QUEUE_WEIGHT = 1.0


class _RaisedQueueCapacity(NamedTuple):
    """One segment whose rendered budget is higher than the requested ``N``."""

    agent_name: str
    requested: int
    effective: int
    weight: float


@dataclass(frozen=True)
class _EpicQueueCapacityResolution:
    """Per-agent effective capacities for one epic launch.

    ``segment_capacity`` is empty when ``capacity`` was omitted, so default
    launches skip rendering ``%queue`` and pay no expansion cost.
    """

    segment_capacity: Mapping[str, int]
    raised: tuple[_RaisedQueueCapacity, ...]


class EpicQueueCapacityConflictError(ValueError):
    """Composed queue fields for one epic segment cannot be admitted."""

    def __init__(
        self,
        message: str,
        *,
        agent_name: str,
        xprompt_name: str,
    ) -> None:
        super().__init__(message)
        self.agent_name = agent_name
        self.xprompt_name = xprompt_name


@dataclass(frozen=True)
class _AuthoredQueueFields:
    weight: float
    capacity: int | None


def _queue_probe_text(
    *,
    xprompt_name: str,
    xprompt_arg: str,
    capacity: int | None = None,
    include_plan: bool = False,
) -> str:
    """Return the queue-relevant probe for one epic segment."""
    lines: list[str] = []
    if capacity is not None:
        formatted = format_queue_directive(capacity=capacity)
        if formatted:
            lines.append(formatted)
    lines.append(f"#{xprompt_name}:{xprompt_arg}")
    if include_plan:
        lines.append("#plan")
    return "\n".join(lines)


def _probe_segment_queue_fields(
    probe_text: str,
    *,
    extra_xprompts: Mapping[str, XPrompt] | None = None,
    cache: dict[str, PromptDirectives] | None = None,
) -> PromptDirectives:
    """Expand *probe_text* and extract its queue directives.

    Results are cached by the exact probe input so a many-phase epic expands
    each distinct xprompt shape once rather than once per phase.
    """
    if cache is not None and probe_text in cache:
        return cache[probe_text]
    extras = dict(extra_xprompts) if extra_xprompts is not None else None
    expanded = process_xprompt_references(
        probe_text,
        extra_xprompts=extras,
        defer_xprompt_names=LAUNCH_DEFERRED_XPROMPT_NAMES,
        raise_on_error=True,
    )
    _cleaned, directives = extract_prompt_directives(expanded)
    if cache is not None:
        cache[probe_text] = directives
    return directives


def format_raised_capacity_line(entry: _RaisedQueueCapacity) -> str:
    """Render one work-plan summary line for a raised segment budget."""
    return (
        f"  Capacity: requested {entry.requested} · {entry.agent_name} "
        f"raised to {entry.effective} (queue weight {_format_weight(entry.weight)})"
    )


def resolve_epic_queue_capacities(
    plan: EpicWorkPlan,
    work_phase_xprompt: Workflow,
    land_epic_xprompt: Workflow,
    capacity: int | None,
    *,
    extra_xprompts: Mapping[str, XPrompt] | None = None,
) -> _EpicQueueCapacityResolution:
    """Probe each segment and return per-agent effective capacities.

    When *capacity* is ``None`` this returns an empty mapping and does not
    expand xprompts. Remaining queue conflicts raise
    :class:`EpicQueueCapacityConflictError` naming the agent and xprompt.
    """
    if capacity is None:
        return _EpicQueueCapacityResolution(
            segment_capacity=MappingProxyType({}),
            raised=(),
        )

    budget_enabled = current_flags().enabled(FeatureFlag.queue_capacity_budget)
    probe_cache: dict[str, PromptDirectives] = {}
    authored_by_shape: dict[tuple[str, bool], _AuthoredQueueFields] = {}
    composed_ok: set[tuple[str, bool, int]] = set()
    mapping: dict[str, int] = {}
    raised: list[_RaisedQueueCapacity] = []

    for agent_name, xprompt_name, refs in _segment_specs(
        plan, work_phase_xprompt, land_epic_xprompt
    ):
        include_plan = "#plan" in refs
        shape = (xprompt_name, include_plan)
        authored = authored_by_shape.get(shape)
        if authored is None:
            authored = _authored_fields(
                "\n".join(refs),
                agent_name=agent_name,
                xprompt_name=xprompt_name,
                extra_xprompts=extra_xprompts,
                cache=probe_cache,
            )
            authored_by_shape[shape] = authored
        if authored.capacity is not None:
            raise EpicQueueCapacityConflictError(
                f"{agent_name} ({xprompt_name}) authors "
                f"%queue(capacity={authored.capacity}) which conflicts "
                f"with --capacity {capacity}",
                agent_name=agent_name,
                xprompt_name=xprompt_name,
            )
        if budget_enabled:
            effective = max(capacity, math.ceil(authored.weight))
        else:
            effective = capacity
        composed_key = (xprompt_name, include_plan, effective)
        if composed_key not in composed_ok:
            composed = _queue_probe_text(
                xprompt_name=xprompt_name,
                xprompt_arg=_xprompt_arg(refs[0]),
                capacity=effective,
                include_plan=include_plan,
            )
            _probe_named(
                composed,
                agent_name=agent_name,
                xprompt_name=xprompt_name,
                extra_xprompts=extra_xprompts,
                cache=probe_cache,
            )
            composed_ok.add(composed_key)
        mapping[agent_name] = effective
        if effective > capacity:
            raised.append(
                _RaisedQueueCapacity(agent_name, capacity, effective, authored.weight)
            )

    return _EpicQueueCapacityResolution(
        segment_capacity=MappingProxyType(mapping),
        raised=tuple(raised),
    )


def _segment_specs(
    plan: EpicWorkPlan,
    work_phase_xprompt: Workflow,
    land_epic_xprompt: Workflow,
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    specs: list[tuple[str, str, tuple[str, ...]]] = []
    for wave in plan.waves:
        for assignment in wave:
            refs = [f"#{work_phase_xprompt.name}:{assignment.bead_id}"]
            if phase_requires_plan(assignment.size):
                refs.append("#plan")
            specs.append((assignment.agent_name, work_phase_xprompt.name, tuple(refs)))
    specs.append(
        (
            plan.land_agent_name,
            land_epic_xprompt.name,
            (f"#{land_epic_xprompt.name}:{plan.epic_id}",),
        )
    )
    return tuple(specs)


def _authored_fields(
    probe_text: str,
    *,
    agent_name: str,
    xprompt_name: str,
    extra_xprompts: Mapping[str, XPrompt] | None,
    cache: dict[str, PromptDirectives],
) -> _AuthoredQueueFields:
    directives = _probe_named(
        probe_text,
        agent_name=agent_name,
        xprompt_name=xprompt_name,
        extra_xprompts=extra_xprompts,
        cache=cache,
    )
    weight = (
        directives.queue_weight
        if directives.queue_weight is not None
        else _DEFAULT_QUEUE_WEIGHT
    )
    return _AuthoredQueueFields(weight=weight, capacity=directives.wait_runners)


def _probe_named(
    probe_text: str,
    *,
    agent_name: str,
    xprompt_name: str,
    extra_xprompts: Mapping[str, XPrompt] | None,
    cache: dict[str, PromptDirectives],
) -> PromptDirectives:
    try:
        return _probe_segment_queue_fields(
            probe_text,
            extra_xprompts=extra_xprompts,
            cache=cache,
        )
    except XPromptError as exc:
        raise EpicQueueCapacityConflictError(
            f"{agent_name} ({xprompt_name}): {exc}",
            agent_name=agent_name,
            xprompt_name=xprompt_name,
        ) from exc


def _xprompt_arg(ref_line: str) -> str:
    _name, separator, argument = ref_line.partition(":")
    if separator:
        return argument
    return ""


def _format_weight(weight: float) -> str:
    if weight == int(weight):
        return f"{weight:.1f}"
    return f"{weight:g}"
