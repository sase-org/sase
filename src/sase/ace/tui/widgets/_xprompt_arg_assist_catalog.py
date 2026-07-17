"""Catalog projection helpers for xprompt argument assist."""

from __future__ import annotations

from sase.xprompt.catalog import build_structured_xprompts_catalog
from sase.xprompt.models import XPrompt
from sase.xprompt.reference_display import (
    workflow_kind_value,
    workflow_reference_insertion,
    workflow_reference_prefix,
)
from sase.xprompt.workflow_models import Workflow

from ._xprompt_arg_assist_inputs import input_hint_from_input_arg
from ._xprompt_arg_assist_models import XPromptAssistEntry, XPromptInputHint


def build_xprompt_assist_entries(
    project: str | None = None,
) -> list[XPromptAssistEntry]:
    """Build immutable TUI assist entries from the structured xprompt catalog."""
    projection = build_structured_xprompts_catalog(project=project)
    return [
        XPromptAssistEntry(
            name=entry.name,
            description=entry.description,
            insertion=entry.insertion,
            reference_prefix=entry.reference_prefix,
            kind=entry.kind,
            input_signature=entry.input_signature,
            inputs=tuple(
                XPromptInputHint(
                    name=inp.name,
                    type=inp.type,
                    required=inp.required,
                    default_display=inp.default_display,
                    position=inp.position,
                    repeatable=inp.repeatable,
                    description=inp.description,
                )
                for inp in entry.inputs
            ),
            content_preview=entry.content_preview,
            is_skill=entry.is_skill,
        )
        for entry in projection.entries
    ]


def xprompt_assist_entry_from_workflow(
    name: str,
    workflow: Workflow,
) -> XPromptAssistEntry:
    """Build a TUI assist entry from a selected workflow-like xprompt."""
    inputs: list[XPromptInputHint] = []
    for inp in workflow.inputs:
        hint = input_hint_from_input_arg(inp, len(inputs))
        if hint is not None:
            inputs.append(hint)

    return XPromptAssistEntry(
        name=name,
        description=workflow.description,
        insertion=workflow_reference_insertion(name, workflow),
        reference_prefix=workflow_reference_prefix(workflow),
        kind=workflow_kind_value(workflow),
        input_signature=None,
        inputs=tuple(inputs),
        content_preview=(
            workflow.get_prompt_part_content() if workflow.is_simple_xprompt() else None
        ),
    )


def xprompt_assist_entry_from_local_xprompt(
    name: str,
    xprompt: XPrompt,
) -> XPromptAssistEntry:
    """Build a TUI assist entry from a prompt-frontmatter local xprompt.

    Mirrors :func:`xprompt_assist_entry_from_workflow` (it routes through the
    same workflow projection) so a ``#_helper`` declared in the Frontmatter
    Panel's ``xprompts:`` field completes, soft-completes, and shows argument
    hints in every prompt pane exactly like a global xprompt.
    """
    from sase.xprompt.models import xprompt_to_workflow

    return xprompt_assist_entry_from_workflow(name, xprompt_to_workflow(xprompt))


def merge_local_xprompt_entries(
    base: list[XPromptAssistEntry],
    local: list[XPromptAssistEntry],
) -> list[XPromptAssistEntry]:
    """Merge live local xprompt *local* entries over the *base* catalog.

    Local entries are **additive**: every local helper is appended, and on a
    name collision the live local definition wins (the panel keeps frontmatter
    live, so a freshly edited helper takes precedence over a stale global of the
    same name). Local entries are placed last so by-name resolvers -- which keep
    the last entry for a name -- select them. ``_``-prefixed local names rarely
    collide with global names, so in practice the merge is purely additive.
    """
    if not local:
        return base
    overridden = {entry.name for entry in local}
    return [entry for entry in base if entry.name not in overridden] + list(local)


__all__ = [
    "build_xprompt_assist_entries",
    "merge_local_xprompt_entries",
    "xprompt_assist_entry_from_local_xprompt",
    "xprompt_assist_entry_from_workflow",
]
