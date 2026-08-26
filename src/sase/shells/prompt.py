"""Prompt-routing helpers for family shell follow-ups."""

from __future__ import annotations

from sase.llm_provider.config import format_model_directive_value


def shell_routing_prefix(
    fork_target: str | None,
    model: str | None,
    reasoning_effort: str | None,
    next_model: str | None = None,
) -> str:
    """Render live xprompt routing directives for a follow-up prompt."""
    lines: list[str] = []
    if fork_target:
        lines.append(f"#fork:{fork_target}")
    selected = next_model.strip() if isinstance(next_model, str) else ""
    if selected:
        lines.append(f"%model:{format_model_directive_value(selected)}")
    else:
        if model:
            lines.append(f"%model:{model}")
        if reasoning_effort:
            lines.append(f"%effort:{reasoning_effort}")
    return "".join(f"{line}\n" for line in lines)


__all__ = ["shell_routing_prefix"]
