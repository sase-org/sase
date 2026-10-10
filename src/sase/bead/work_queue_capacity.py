"""Per-segment ``--capacity`` resolution for epic ``sase bead work``.

``sase bead work --capacity N`` stamps a ``%queue(capacity=...)`` budget into
every phase and land segment. A macro that authors a queue weight greater
than ``N`` is raised to ``ceil(weight)``, so a uniform ``N=1`` stays
satisfiable for the default-weight builtin lander.

This module probes only the queue-relevant macro text (never ``%id``,
``%clan``, ``%w``, ``%model``, or VCS prefixes), then translates ``N`` into a
per-agent budget: ``max(N, ceil(authored_weight))``. A colliding
macro-authored ``capacity`` is a pre-flight error so the runner never sees it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple

from sase.bead.work import EpicWorkPlan, phase_requires_plan
from sase.macro._exceptions import MacroError
from sase.macro.directives import extract_prompt_directives
from sase.macro.processor import (
    LAUNCH_DEFERRED_MACRO_NAMES,
    process_macro_references,
)
from sase.macro.queue_directive import format_queue_directive
from sase.macro.workflow_models import Workflow

if TYPE_CHECKING:
    from sase.macro._directive_types import PromptDirectives
    from sase.macro.models import Macro

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
        macro_name: str,
    ) -> None:
        super().__init__(message)
        self.agent_name = agent_name
        self.macro_name = macro_name


@dataclass(frozen=True)
class _AuthoredQueueFields:
    weight: float
    capacity: int | None


def _queue_probe_text(
    *,
    macro_name: str,
    macro_arg: str,
    capacity: int | None = None,
    include_plan: bool = False,
) -> str:
    """Return the queue-relevant probe for one epic segment."""
    lines: list[str] = []
    if capacity is not None:
        formatted = format_queue_directive(capacity=capacity)
        if formatted:
            lines.append(formatted)
    lines.append(f"#{macro_name}:{macro_arg}")
    if include_plan:
        lines.append("#plan")
    return "\n".join(lines)


def _probe_segment_queue_fields(
    probe_text: str,
    *,
    extra_macros: Mapping[str, Macro] | None = None,
    cache: dict[str, PromptDirectives] | None = None,
) -> PromptDirectives:
    """Expand *probe_text* and extract its queue directives.

    Results are cached by the exact probe input so a many-phase epic expands
    each distinct macro shape once rather than once per phase.
    """
    if cache is not None and probe_text in cache:
        return cache[probe_text]
    extras = dict(extra_macros) if extra_macros is not None else None
    expanded = process_macro_references(
        probe_text,
        extra_macros=extras,
        defer_macro_names=LAUNCH_DEFERRED_MACRO_NAMES,
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
    work_phase_macro: Workflow,
    land_epic_macro: Workflow,
    capacity: int | None,
    *,
    extra_macros: Mapping[str, Macro] | None = None,
) -> _EpicQueueCapacityResolution:
    """Probe each segment and return per-agent effective capacities.

    When *capacity* is ``None`` this returns an empty mapping and does not
    expand macros. Remaining queue conflicts raise
    :class:`EpicQueueCapacityConflictError` naming the agent and macro.
    """
    if capacity is None:
        return _EpicQueueCapacityResolution(
            segment_capacity=MappingProxyType({}),
            raised=(),
        )

    probe_cache: dict[str, PromptDirectives] = {}
    authored_by_shape: dict[tuple[str, bool], _AuthoredQueueFields] = {}
    composed_ok: set[tuple[str, bool, int]] = set()
    mapping: dict[str, int] = {}
    raised: list[_RaisedQueueCapacity] = []

    for agent_name, macro_name, refs in _segment_specs(
        plan, work_phase_macro, land_epic_macro
    ):
        include_plan = "#plan" in refs
        shape = (macro_name, include_plan)
        authored = authored_by_shape.get(shape)
        if authored is None:
            authored = _authored_fields(
                "\n".join(refs),
                agent_name=agent_name,
                macro_name=macro_name,
                extra_macros=extra_macros,
                cache=probe_cache,
            )
            authored_by_shape[shape] = authored
        if authored.capacity is not None:
            raise EpicQueueCapacityConflictError(
                f"{agent_name} ({macro_name}) authors "
                f"%queue(capacity={authored.capacity}) which conflicts "
                f"with --capacity {capacity}",
                agent_name=agent_name,
                macro_name=macro_name,
            )
        effective = max(capacity, math.ceil(authored.weight))
        composed_key = (macro_name, include_plan, effective)
        if composed_key not in composed_ok:
            composed = _queue_probe_text(
                macro_name=macro_name,
                macro_arg=_macro_arg(refs[0]),
                capacity=effective,
                include_plan=include_plan,
            )
            _probe_named(
                composed,
                agent_name=agent_name,
                macro_name=macro_name,
                extra_macros=extra_macros,
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
    work_phase_macro: Workflow,
    land_epic_macro: Workflow,
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    specs: list[tuple[str, str, tuple[str, ...]]] = []
    for wave in plan.waves:
        for assignment in wave:
            refs = [f"#{work_phase_macro.name}:{assignment.bead_id}"]
            if phase_requires_plan(assignment.size):
                refs.append("#plan")
            specs.append((assignment.agent_name, work_phase_macro.name, tuple(refs)))
    specs.append(
        (
            plan.land_agent_name,
            land_epic_macro.name,
            (f"#{land_epic_macro.name}:{plan.epic_id}",),
        )
    )
    return tuple(specs)


def _authored_fields(
    probe_text: str,
    *,
    agent_name: str,
    macro_name: str,
    extra_macros: Mapping[str, Macro] | None,
    cache: dict[str, PromptDirectives],
) -> _AuthoredQueueFields:
    directives = _probe_named(
        probe_text,
        agent_name=agent_name,
        macro_name=macro_name,
        extra_macros=extra_macros,
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
    macro_name: str,
    extra_macros: Mapping[str, Macro] | None,
    cache: dict[str, PromptDirectives],
) -> PromptDirectives:
    try:
        return _probe_segment_queue_fields(
            probe_text,
            extra_macros=extra_macros,
            cache=cache,
        )
    except MacroError as exc:
        raise EpicQueueCapacityConflictError(
            f"{agent_name} ({macro_name}): {exc}",
            agent_name=agent_name,
            macro_name=macro_name,
        ) from exc


def _macro_arg(ref_line: str) -> str:
    _name, separator, argument = ref_line.partition(":")
    if separator:
        return argument
    return ""


def _format_weight(weight: float) -> str:
    if weight == int(weight):
        return f"{weight:.1f}"
    return f"{weight:g}"
