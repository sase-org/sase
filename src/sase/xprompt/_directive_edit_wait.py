"""Wait and auto-mode prompt directive edits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ._directive_edit_core import format_directive_arg, set_prompt_directive

AutoMode = Literal["plan", "tale", "epic"]


@dataclass(frozen=True)
class PromptWaitDirective:
    """Canonical wait directive payload used by prompt rewrite callers."""

    agents: tuple[str, ...] = ()
    time_token: str | None = None
    runners: int | None = None
    beads: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(
            self.agents or self.time_token or self.runners is not None or self.beads
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
    """Return *prompt* with a canonical ``%wait(...)`` directive or none."""
    replacement = _format_wait_directive(wait_spec) if wait_spec else None
    return set_prompt_directive(
        prompt,
        {"wait"},
        replacement,
        remove_deprecated=True,
        remove_time_xprompts=True,
    )


def _format_wait_directive(wait_spec: PromptWaitDirective | None) -> str | None:
    if not wait_spec:
        return None
    parts = [format_directive_arg(agent) for agent in wait_spec.agents]
    if wait_spec.time_token:
        parts.append(f"time={wait_spec.time_token}")
    if wait_spec.runners is not None:
        parts.append(f"runners={wait_spec.runners}")
    directives = [f"%wait({', '.join(parts)})"] if parts else []
    directives.extend(
        f"%wait(bead={format_directive_arg(bead)})" for bead in wait_spec.beads
    )
    return "\n".join(directives)
