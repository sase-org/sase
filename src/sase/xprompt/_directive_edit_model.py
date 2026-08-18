"""Model-directive edits for relaunch and CLI restart."""

from __future__ import annotations

from ._directive_edit_core import format_directive_arg, set_prompt_directive


def set_prompt_model(prompt: str, model: str) -> str:
    """Return *prompt* with ``%model`` set to *model*.

    *model* is the same ``[provider/]model[@effort]`` spelling ``%model:``
    accepts. A bare model (``opus``) replaces only ``{"m", "model"}`` and
    leaves a standalone ``%effort:`` / ``%e:`` in place. A combined value
    (``opus@high``) also removes ``{"e", "effort"}`` so the single
    ``%model:opus@high`` directive is the only source of truth.
    """
    from sase.xprompt.effort import split_model_effort

    _bare_model, effort = split_model_effort(model)
    if any(char.isspace() or char in ",()=" for char in model):
        replacement = f"%model({format_directive_arg(model)})"
    else:
        replacement = f"%model:{model}"
    updated = set_prompt_directive(prompt, {"m", "model"}, replacement)
    if effort is None:
        return updated
    return set_prompt_directive(updated, {"e", "effort"}, None)
