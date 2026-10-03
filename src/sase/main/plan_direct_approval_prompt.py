"""Coder prompt composition for gateless ``sase plan approve`` runs."""

from __future__ import annotations

from sase.main.plan_direct_approval_types import CoderPlacement


def compose_coder_prompt(
    *,
    project_tag: str,
    model_directive: str,
    plan_argument: str,
    extra_prompt: str | None,
    wait: object,
    bead: str | None,
    placement: CoderPlacement,
) -> str:
    """Compose the ``#coder`` prompt used for previews and recovery hints."""
    from sase.macro._parsing_args import escape_for_xprompt

    argument = plan_argument.strip()
    if _needs_quoting(argument):
        argument = f'"{escape_for_xprompt(argument)}"'
    if placement.mode == "session" and placement.parent:
        id_part = f"%id({placement.suffix}, session={placement.parent})"
    elif bead:
        id_part = f"%id(bead={bead})"
    else:
        id_part = ""
    model_part = f"%model:{model_directive}" if model_directive else ""
    head = " ".join(part for part in (project_tag.strip(), model_part, id_part) if part)
    lines = [f"{head} #coder({argument})" if head else f"#coder({argument})"]
    if extra_prompt and extra_prompt.strip():
        lines += ["", "Additional instructions:", extra_prompt.strip()]
    prompt = "\n".join(lines)
    if wait is not None:
        try:
            from sase.macro.directive_edit import set_prompt_wait

            prompt = set_prompt_wait(prompt, wait)  # type: ignore[arg-type]
        except Exception:
            pass
    return prompt


def _needs_quoting(argument: str) -> bool:
    import re

    return re.search(r"[^A-Za-z0-9_/:.+-]", argument) is not None


__all__ = ["compose_coder_prompt"]
