"""Fail-closed launch guard for hard-disabled LLM providers.

A launch that can only run on a hard-disabled provider is refused before any
workspace is claimed or any agent is spawned. Soft disables never refuse. The
fast path is a lock-free peek: when no hard disable is active, nothing is
planned. Unexpected errors are the caller's job to fail open — this module
raises only :class:`DisabledProviderLaunchError` for a confirmed block.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sase.llm_provider.provider_disable import TemporaryProviderDisable
from sase.llm_provider.provider_disable_peek import peek_active_provider_disables

_LAUNCH_UNIT_KEYS = frozenset({"prompt", "template_group", "swarm_xprompts"})
_REMEDY = "Enable it in ACE Launch Control (,m → p) or choose another model."

ProviderDisableSnapshot = Mapping[str, TemporaryProviderDisable]


@dataclass(frozen=True, slots=True)
class LaunchUnitCandidate:
    """One fan-out slot of a unit and the provider/model it would use."""

    slot_index: int
    prompt: str
    provider: str | None
    model: str | None
    blocked_by: TemporaryProviderDisable | None
    unavailable: bool


@dataclass(frozen=True, slots=True)
class LaunchUnit:
    """One expanded prompt segment: what the panel calls "this agent"."""

    index: int
    total: int
    prompt: str
    template_group: str | None
    swarm_xprompts: tuple[str, ...]
    candidates: tuple[LaunchUnitCandidate, ...]
    _blocking_disables: tuple[TemporaryProviderDisable, ...] = ()

    @property
    def blocked(self) -> bool:
        """Return whether every candidate is blocked or unavailable, with a block."""
        if not self.candidates:
            return False
        if not any(candidate.blocked_by is not None for candidate in self.candidates):
            return False
        return all(
            candidate.blocked_by is not None or candidate.unavailable
            for candidate in self.candidates
        )

    @property
    def blocking_providers(self) -> tuple[str, ...]:
        """Distinct hard-disabled providers that leave this unit with no option."""
        if self._blocking_disables:
            return tuple(
                dict.fromkeys(disable.provider for disable in self._blocking_disables)
            )
        return tuple(
            dict.fromkeys(
                candidate.blocked_by.provider
                for candidate in self.candidates
                if candidate.blocked_by is not None
            )
        )

    @property
    def single_model(self) -> str | None:
        """Return ``provider/model`` when every candidate agrees; else ``None``."""
        labels: list[str] = []
        for candidate in self.candidates:
            if not candidate.provider or not candidate.model:
                return None
            labels.append(f"{candidate.provider}/{candidate.model}")
        if not labels:
            return None
        first = labels[0]
        return first if all(label == first for label in labels) else None


@dataclass(frozen=True, slots=True)
class LaunchUnitInput:
    """One ACE-resolved expanded unit in a ``sase run`` request payload."""

    prompt: str
    template_group: str | None = None
    swarm_xprompts: tuple[str, ...] = ()


class DisabledProviderLaunchError(RuntimeError):
    """Raised before any spawn when a unit needs a hard-disabled provider."""

    def __init__(self, unit: LaunchUnit, message: str) -> None:
        self.unit = unit
        super().__init__(message)

    @classmethod
    def from_unit(cls, unit: LaunchUnit) -> DisabledProviderLaunchError:
        """Build the actionable refusal for *unit*."""
        return cls(unit, _format_block_message(unit))


class LaunchUnitsPayloadError(ValueError):
    """Raised when a ``launch_units`` request payload is malformed."""


def parse_launch_units_payload(value: object) -> tuple[LaunchUnitInput, ...]:
    """Validate a ``launch_units`` request list into typed unit inputs.

    Each entry must be an object with exactly the keys ``prompt``,
    ``template_group``, and ``swarm_xprompts``. Prompts must be non-empty.
    """
    if not isinstance(value, list):
        raise LaunchUnitsPayloadError("launch_units must be a list")
    units: list[LaunchUnitInput] = []
    for index, item in enumerate(value):
        units.append(_parse_launch_unit_entry(index, item))
    return tuple(units)


def plan_launch_units(prompt: str) -> tuple[LaunchUnit, ...]:
    """Enumerate the launch units one prompt will spawn.

    Mirrors :func:`sase.agent.launch_request_planning.build_preview_plan`'s
    read-only expansion, then resolves every fan-out slot of each expanded
    segment so a model-bearing ``%alt`` / ``%repeat`` cannot hide a blocked
    branch. Never consumes a load-balanced pool cursor.
    """
    return _plan_launch_units(prompt, peek_active_provider_disables())


def blocked_launch_units(
    prompt: str,
    *,
    units: Sequence[LaunchUnitInput] | None = None,
) -> tuple[LaunchUnit, ...]:
    """Return the units that can only run on a hard-disabled provider.

    When no hard disable is active this returns ``()`` without planning.
    """
    snapshot = peek_active_provider_disables()
    if not _snapshot_has_hard_disable(snapshot):
        return ()
    planned = (
        _plan_launch_units_from_inputs(units, snapshot)
        if units is not None
        else _plan_launch_units(prompt, snapshot)
    )
    return tuple(unit for unit in planned if unit.blocked)


def guard_launch_units(
    prompt: str,
    *,
    units: Sequence[LaunchUnitInput] | None = None,
) -> None:
    """Refuse *prompt* when a unit needs a hard-disabled provider.

    Raises :class:`DisabledProviderLaunchError` for the first blocked unit.
    Any other exception propagates so the caller can fail open.
    """
    blocked = blocked_launch_units(prompt, units=units)
    if not blocked:
        return
    raise DisabledProviderLaunchError.from_unit(blocked[0])


def _snapshot_has_hard_disable(snapshot: ProviderDisableSnapshot) -> bool:
    return any(record.is_hard for record in snapshot.values())


def _parse_launch_unit_entry(index: int, item: object) -> LaunchUnitInput:
    if not isinstance(item, dict):
        raise LaunchUnitsPayloadError(f"launch_units[{index}] must be an object")
    if set(item) != _LAUNCH_UNIT_KEYS:
        raise LaunchUnitsPayloadError(
            f"launch_units[{index}] must have exactly keys prompt, "
            "template_group, swarm_xprompts"
        )
    prompt = item["prompt"]
    if not isinstance(prompt, str) or not prompt.strip():
        raise LaunchUnitsPayloadError(
            f"launch_units[{index}].prompt must be a non-empty string"
        )
    template_group = item["template_group"]
    if template_group is not None and not isinstance(template_group, str):
        raise LaunchUnitsPayloadError(
            f"launch_units[{index}].template_group must be a string or null"
        )
    swarm = item["swarm_xprompts"]
    if not isinstance(swarm, list) or not all(isinstance(name, str) for name in swarm):
        raise LaunchUnitsPayloadError(
            f"launch_units[{index}].swarm_xprompts must be a list of strings"
        )
    return LaunchUnitInput(
        prompt=prompt,
        template_group=template_group,
        swarm_xprompts=tuple(swarm),
    )


def _plan_launch_units(
    prompt: str,
    snapshot: ProviderDisableSnapshot,
) -> tuple[LaunchUnit, ...]:
    from sase.agent.multi_prompt import parse_multi_prompt
    from sase.agent.xprompt_swarm import expand_xprompt_swarms_with_metadata
    from sase.project_aliases import canonicalize_project_aliases_in_prompt

    submitted = canonicalize_project_aliases_in_prompt(prompt)
    multi = parse_multi_prompt(submitted)
    expanded_records = expand_xprompt_swarms_with_metadata(
        multi.segments, multi.local_xprompts
    )
    inputs = [
        LaunchUnitInput(
            prompt=record.prompt,
            template_group=record.template_group,
            swarm_xprompts=tuple(record.swarm_xprompts),
        )
        for record in expanded_records
    ]
    return _plan_launch_units_from_inputs(inputs, snapshot)


def _plan_launch_units_from_inputs(
    units: Sequence[LaunchUnitInput],
    snapshot: ProviderDisableSnapshot,
) -> tuple[LaunchUnit, ...]:
    from sase.xprompt._parsing import (
        normalize_default_vcs_workflow,
        normalize_default_vcs_workflow_segment,
    )

    total = len(units)
    planned: list[LaunchUnit] = []
    for index, unit in enumerate(units, start=1):
        segment = (
            normalize_default_vcs_workflow_segment(unit.prompt)
            if total > 1
            else normalize_default_vcs_workflow(unit.prompt)
        )
        planned.append(
            _unit_from_segment(
                index=index,
                total=total,
                segment=segment,
                template_group=unit.template_group,
                swarm_xprompts=tuple(unit.swarm_xprompts),
                snapshot=snapshot,
            )
        )
    return tuple(planned)


def _unit_from_segment(
    *,
    index: int,
    total: int,
    segment: str,
    template_group: str | None,
    swarm_xprompts: tuple[str, ...],
    snapshot: ProviderDisableSnapshot,
) -> LaunchUnit:
    resolved: list[tuple[LaunchUnitCandidate, tuple[str, ...]]] = [
        _resolve_candidate(slot_index, slot.prompt, snapshot)
        for slot_index, slot in enumerate(_fanout_slots_for_segment(segment))
    ]
    candidates = tuple(item[0] for item in resolved)
    return LaunchUnit(
        index=index,
        total=total,
        prompt=segment,
        template_group=template_group,
        swarm_xprompts=swarm_xprompts,
        candidates=candidates,
        _blocking_disables=_collect_blocking_disables(resolved, snapshot),
    )


def _fanout_slots_for_segment(segment: str) -> list[Any]:
    from sase.core.agent_launch_facade import plan_agent_launch_fanout, plan_fake_fanout
    from sase.xprompt.directives import plan_prompt_fanout_variants

    repeat_plan = plan_agent_launch_fanout(segment, launch_kind="repeat")
    if repeat_plan.slots:
        return list(repeat_plan.slots)

    fanout_plan = plan_prompt_fanout_variants(segment)
    if fanout_plan is None and "#" in segment:
        from sase.xprompt.processor import (
            LAUNCH_DEFERRED_XPROMPT_NAMES,
            process_xprompt_references,
            prompt_may_reference_xprompt,
        )

        if prompt_may_reference_xprompt(segment):
            expanded = process_xprompt_references(
                segment,
                defer_xprompt_names=LAUNCH_DEFERRED_XPROMPT_NAMES,
            )
            fanout_plan = plan_prompt_fanout_variants(expanded)
    if fanout_plan is not None:
        return list(fanout_plan.slots)
    return list(plan_fake_fanout("single", [segment]).slots)


def _resolve_candidate(
    slot_index: int,
    prompt: str,
    snapshot: ProviderDisableSnapshot,
) -> tuple[LaunchUnitCandidate, tuple[str, ...]]:
    from sase.llm_provider.launch_selection import resolve_launch_selection
    from sase.llm_provider.registry import provider_routing_available
    from sase.xprompt.directives import extract_prompt_directives

    _cleaned, directives = extract_prompt_directives(prompt)
    selection = resolve_launch_selection(
        directives,
        consume=False,
        provider_disables=snapshot,
    )
    provider = selection.provider if selection is not None else None
    model = selection.model if selection is not None else None
    disable = snapshot.get(provider) if provider else None
    blocked_by = disable if disable is not None and disable.is_hard else None
    unavailable = not provider_routing_available(provider, {})
    candidate = LaunchUnitCandidate(
        slot_index=slot_index,
        prompt=prompt,
        provider=provider,
        model=model,
        blocked_by=blocked_by,
        unavailable=unavailable,
    )
    alias_names: list[str] = []
    if directives.model_alias:
        alias_names.append(directives.model_alias)
    if selection is not None:
        for name in selection.alias_trail:
            if name not in alias_names:
                alias_names.append(name)
    return candidate, tuple(alias_names)


def _collect_blocking_disables(
    resolved: Sequence[tuple[LaunchUnitCandidate, tuple[str, ...]]],
    snapshot: ProviderDisableSnapshot,
) -> tuple[TemporaryProviderDisable, ...]:
    found: dict[str, TemporaryProviderDisable] = {}
    for candidate, alias_names in resolved:
        if candidate.blocked_by is not None:
            found.setdefault(candidate.blocked_by.provider, candidate.blocked_by)
        if candidate.blocked_by is None and not candidate.unavailable:
            continue
        for provider, disable in _exhausted_alias_disables(
            alias_names, snapshot
        ).items():
            found.setdefault(provider, disable)
    return tuple(found.values())


def _exhausted_alias_disables(
    alias_names: Sequence[str],
    snapshot: ProviderDisableSnapshot,
) -> dict[str, TemporaryProviderDisable]:
    from sase.llm_provider.model_alias_resolution import model_alias_selector_details

    found: dict[str, TemporaryProviderDisable] = {}
    for alias in alias_names:
        details = model_alias_selector_details(alias, provider_disables=snapshot)
        if details is None:
            continue
        if any(member.available for member in details.members):
            continue
        for member in details.members:
            if not member.provider:
                continue
            disable = snapshot.get(member.provider)
            if disable is not None and disable.is_hard:
                found.setdefault(member.provider, disable)
    return found


def _format_block_message(unit: LaunchUnit) -> str:
    from sase.ace.tui.provider_disable_display import provider_disable_provenance_label
    from sase.llm_provider.registry import format_provider_disable_expiry

    snapshot = peek_active_provider_disables()
    disables = tuple(
        snapshot[name] for name in unit.blocking_providers if name in snapshot
    )
    if not disables:
        disables = tuple(
            candidate.blocked_by
            for candidate in unit.candidates
            if candidate.blocked_by is not None
        )
    provider_clause = _format_provider_clause(
        disables,
        expiry=format_provider_disable_expiry,
        provenance=provider_disable_provenance_label,
    )
    prefix = (
        f"Cannot launch agent {unit.index} of {unit.total}: "
        if unit.total > 1
        else "Cannot launch: "
    )
    return f"{prefix}{provider_clause} {launch_unit_block_reason(unit)} {_REMEDY}"


def _format_provider_clause(
    disables: Sequence[TemporaryProviderDisable],
    *,
    expiry: Any,
    provenance: Any,
) -> str:
    if not disables:
        return "a hard-disabled provider is required."
    parts = [
        (
            f"{disable.provider.upper()} is disabled {expiry(disable)} "
            f"({provenance(disable)})"
        )
        for disable in disables
    ]
    if len(parts) == 1:
        clause = parts[0]
    elif len(parts) == 2:
        clause = f"{parts[0]} and {parts[1]}"
    else:
        clause = ", ".join(parts[:-1]) + f", and {parts[-1]}"
    return f"{clause}."


def launch_unit_block_reason(unit: LaunchUnit) -> str:
    from sase.llm_provider.model_alias_resolution import model_alias_selector_details
    from sase.xprompt.directives import extract_prompt_directives

    candidate = next(
        (item for item in unit.candidates if item.blocked_by is not None),
        unit.candidates[0] if unit.candidates else None,
    )
    prompt = candidate.prompt if candidate is not None else unit.prompt
    _cleaned, directives = extract_prompt_directives(prompt)
    alias = directives.model_alias
    if alias:
        details = model_alias_selector_details(
            alias, provider_disables=peek_active_provider_disables()
        )
        if details is not None and details.mode == "round_robin":
            return (
                f"Every member of @{alias} is disabled, so there is no "
                "fallback to route to."
            )
        if details is not None and details.mode == "fallback":
            return (
                f"The @{alias} fallback has no available candidate, so there is "
                "no fallback to route to."
            )
        return (
            f"This prompt asks for @{alias} with %model, so there is no "
            "fallback to route to."
        )
    if directives.model:
        return (
            f"This prompt asks for {directives.model} with %model, so there is "
            "no fallback to route to."
        )
    provider = candidate.provider if candidate is not None else None
    if provider:
        return f"The launch default resolves to {provider.upper()}."
    return "The launch default has no available candidate."


__all__ = [
    "DisabledProviderLaunchError",
    "LaunchUnit",
    "LaunchUnitCandidate",
    "LaunchUnitInput",
    "LaunchUnitsPayloadError",
    "blocked_launch_units",
    "guard_launch_units",
    "launch_unit_block_reason",
    "parse_launch_units_payload",
    "plan_launch_units",
]
