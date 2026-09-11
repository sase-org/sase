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

    def __bool__(self) -> bool:
        return bool(
            self.agents
            or self.time_token
            or self.capacity is not None
            or self.priority is not None
            or self.weight is not None
            or self.beads
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
        remove_time_xprompts=True,
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
    queue_replacement = format_queue_directive(
        capacity=wait_spec.capacity if wait_spec else None,
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
        remove_time_xprompts=True,
    )


def set_prompt_queue(
    prompt: str,
    *,
    capacity: int | None,
    priority: int | None,
    weight: float | None = None,
) -> str:
    """Return *prompt* with only the runner-slot queue directive rewritten."""
    resolved_weight = weight if weight is not None else _existing_queue_weight(prompt)
    return set_prompt_directive(
        prompt,
        {"queue"},
        format_queue_directive(
            capacity=capacity,
            priority=priority,
            weight=resolved_weight,
        ),
        remove_deprecated=False,
        remove_time_xprompts=False,
    )


def _format_wait_directive(
    wait_spec: PromptWaitDirective | None,
) -> str | None:
    if not wait_spec:
        return None
    parts = [format_directive_arg(agent) for agent in wait_spec.agents]
    if wait_spec.time_token:
        parts.append(f"time={wait_spec.time_token}")
    directives = [f"%wait({', '.join(parts)})"] if parts else []
    directives.extend(
        f"%wait(bead={format_directive_arg(bead)})" for bead in wait_spec.beads
    )
    return "\n".join(directives)


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
