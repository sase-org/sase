"""Wait and auto-mode prompt directive edits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ._directive_collect import collect_queue_directive_occurrences
from ._directive_edit_core import (
    format_directive_arg,
    protect_ignored_regions,
    set_prompt_directive,
)
from ._exceptions import DirectiveError
from .queue_directive import format_queue_directive

AutoMode = Literal["plan", "tale", "epic"]


@dataclass(frozen=True)
class PromptWaitDirective:
    """Canonical wait directive payload used by prompt rewrite callers."""

    agents: tuple[str, ...] = ()
    time_token: str | None = None
    capacity: int | None = None
    priority: int | None = None
    weight: float | None = None
    beads: tuple[str, ...] = ()
    hoods: tuple[str, ...] = ()
    capacity_multiplier: float | None = None
    epic_follow_agents: tuple[str, ...] | None = None

    def __bool__(self) -> bool:
        return bool(
            self.agents
            or self.time_token
            or self.capacity is not None
            or self.capacity_multiplier is not None
            or self.priority is not None
            or self.weight is not None
            or self.beads
            or self.hoods
            or self.epic_follow_agents
        )


def set_prompt_auto_mode(prompt: str, mode: AutoMode | None) -> str:
    """Return *prompt* with the requested canonical ``%auto`` directive."""
    replacement = None
    if mode == "plan":
        replacement = "%auto"
    elif mode is not None:
        replacement = f"%auto:{mode}"
    return set_prompt_directive(prompt, {"auto"}, replacement)


def set_prompt_wait(
    prompt: str,
    wait_spec: PromptWaitDirective | None,
) -> str:
    """Return *prompt* with dependency/time ``%wait`` rewritten."""
    replacement = _format_wait_directive(wait_spec) if wait_spec else None
    return set_prompt_directive(
        prompt,
        {"wait"},
        replacement,
        remove_deprecated=True,
        remove_time_macros=True,
    )


def set_prompt_wait_and_queue(
    prompt: str,
    wait_spec: PromptWaitDirective | None,
) -> str:
    """Return *prompt* with wait and runner-slot queue directives rewritten."""
    wait_replacement = _format_wait_directive(wait_spec) if wait_spec else None
    weight = (
        wait_spec.weight
        if wait_spec is not None and wait_spec.weight is not None
        else _existing_queue_weight(prompt)
    )
    if wait_spec is None:
        capacity: int | None = None
        capacity_multiplier: float | None = None
    elif wait_spec.capacity is not None or wait_spec.capacity_multiplier is not None:
        capacity = wait_spec.capacity
        capacity_multiplier = wait_spec.capacity_multiplier
    else:
        capacity, capacity_multiplier = _existing_queue_capacity(prompt)
    queue_replacement = format_queue_directive(
        capacity=capacity,
        capacity_multiplier=capacity_multiplier,
        priority=wait_spec.priority if wait_spec else None,
        weight=weight,
    )
    replacement = (
        "\n".join(part for part in (wait_replacement, queue_replacement) if part)
        or None
    )
    return set_prompt_directive(
        prompt,
        {"wait", "queue"},
        replacement,
        remove_deprecated=True,
        remove_time_macros=True,
    )


def set_prompt_queue(
    prompt: str,
    *,
    capacity: int | None,
    priority: int | None,
    weight: float | None = None,
    capacity_multiplier: float | None = None,
) -> str:
    """Return *prompt* with only the runner-slot queue directive rewritten."""
    resolved_weight = weight if weight is not None else _existing_queue_weight(prompt)
    resolved_capacity = capacity
    resolved_multiplier = capacity_multiplier
    if resolved_capacity is None and resolved_multiplier is None:
        resolved_capacity, resolved_multiplier = _existing_queue_capacity(prompt)
    return set_prompt_directive(
        prompt,
        {"queue"},
        format_queue_directive(
            capacity=resolved_capacity,
            capacity_multiplier=resolved_multiplier,
            priority=priority,
            weight=resolved_weight,
        ),
        remove_deprecated=False,
        remove_time_macros=False,
    )


def _format_wait_directive(
    wait_spec: PromptWaitDirective | None,
) -> str | None:
    if not wait_spec:
        return None
    from ._directive_types import WAIT_FOR_EPIC_DEFAULT

    follow = set(wait_spec.epic_follow_agents or ())
    if wait_spec.epic_follow_agents is None:
        main_agents = list(wait_spec.agents)
        follow_agents: list[str] = []
    elif WAIT_FOR_EPIC_DEFAULT:
        main_agents = [a for a in wait_spec.agents if a not in follow]
        follow_agents = [a for a in wait_spec.agents if a in follow]
    else:
        main_agents = [a for a in wait_spec.agents if a not in follow]
        follow_agents = [a for a in wait_spec.agents if a in follow]
    parts = [format_directive_arg(agent) for agent in main_agents]
    if wait_spec.time_token:
        parts.append(f"time={wait_spec.time_token}")
    directives = [f"%wait({', '.join(parts)})"] if parts else []
    if follow_agents:
        value = "true" if not WAIT_FOR_EPIC_DEFAULT else "true"
        if WAIT_FOR_EPIC_DEFAULT:
            # When the default flips, the positive list stays in the main
            # occurrence and explicit-false agents split out instead; until
            # then the positive list always renders with for_epic=true.
            pass
        follow_parts = [format_directive_arg(agent) for agent in follow_agents]
        follow_parts.append(f"for_epic={value}")
        directives.append(f"%wait({', '.join(follow_parts)})")
    directives.extend(
        f"%wait(bead={format_directive_arg(bead)})" for bead in wait_spec.beads
    )
    directives.extend(
        f"%wait(hood={format_directive_arg(hood)})" for hood in wait_spec.hoods
    )
    return "\n".join(directives) if directives else None


def _existing_queue_capacity(prompt: str) -> tuple[int | None, float | None]:
    """Return the authored integer/multiplier capacity already in *prompt*."""
    protected, _restore = protect_ignored_regions(prompt)
    occurrences = collect_queue_directive_occurrences(protected)
    if not occurrences:
        return None, None

    from .queue_directive import collect_queue_fields

    payload = collect_queue_fields(occurrences)
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        return None, None
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return None, None
    raw_capacity = fields.get(
        "capacity",
        fields.get("queue_capacity", fields.get("runners")),
    )
    capacity = int(raw_capacity) if raw_capacity is not None else None
    raw_multiplier = fields.get("queue_capacity_multiplier")
    multiplier = float(raw_multiplier) if raw_multiplier is not None else None
    if capacity is not None and multiplier is not None:
        return capacity, None
    return capacity, multiplier


def _existing_queue_weight(prompt: str) -> float | None:
    protected, _restore = protect_ignored_regions(prompt)
    occurrences = collect_queue_directive_occurrences(protected)
    if not occurrences:
        return None

    from .queue_directive import collect_queue_fields

    payload = collect_queue_fields(occurrences)
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            message = str(first.get("message") or "Invalid %queue directive.")
        else:
            message = "Invalid %queue directive."
        raise DirectiveError(message)
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return None
    value = fields.get("weight")
    return float(value) if value is not None else None
