"""Wait and auto-mode prompt directive edits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ._directive_edit_core import format_directive_arg, set_prompt_directive
from .queue_directive import format_queue_directive

AutoMode = Literal["plan", "tale", "epic"]


@dataclass(frozen=True)
class PromptWaitDirective:
    """Canonical wait directive payload used by prompt rewrite callers."""

    agents: tuple[str, ...] = ()
    time_token: str | None = None
    runners: int | None = None
    priority: int | None = None
    beads: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(
            self.agents
            or self.time_token
            or self.runners is not None
            or self.priority is not None
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
    queue_replacement = (
        format_queue_directive(
            runners=wait_spec.runners,
            priority=wait_spec.priority,
        )
        if wait_spec
        else None
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
    runners: int | None,
    priority: int | None,
) -> str:
    """Return *prompt* with only the runner-slot queue directive rewritten."""
    return set_prompt_directive(
        prompt,
        {"queue"},
        format_queue_directive(runners=runners, priority=priority),
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
