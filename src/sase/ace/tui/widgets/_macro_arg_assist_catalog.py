"""Catalog projection helpers for macro argument assist."""

from __future__ import annotations

from sase.macro.catalog import build_structured_macros_catalog
from sase.macro.models import Macro
from sase.macro.reference_display import (
    workflow_kind_value,
    workflow_reference_insertion,
    workflow_reference_prefix,
)
from sase.macro.workflow_models import Workflow

from ._macro_arg_assist_inputs import input_hint_from_input_arg
from ._macro_arg_assist_models import MacroAssistEntry, MacroInputHint


def build_macro_assist_entries(
    project: str | None = None,
) -> list[MacroAssistEntry]:
    """Build immutable TUI assist entries from the structured macro catalog."""
    # The TUI is a local display; the string-default redaction exists only
    # for the mobile wire.
    projection = build_structured_macros_catalog(
        project=project, include_string_defaults=True
    )
    return [
        MacroAssistEntry(
            name=entry.name,
            description=entry.description,
            insertion=entry.insertion,
            reference_prefix=entry.reference_prefix,
            kind=entry.kind,
            input_signature=entry.input_signature,
            inputs=tuple(
                MacroInputHint(
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
            skill_name=entry.skill_name,
            memory_type=entry.memory_type,
        )
        for entry in projection.entries
    ]


def macro_assist_entry_from_workflow(
    name: str,
    workflow: Workflow,
) -> MacroAssistEntry:
    """Build a TUI assist entry from a selected workflow-like macro."""
    inputs: list[MacroInputHint] = []
    for inp in workflow.inputs:
        hint = input_hint_from_input_arg(inp, len(inputs))
        if hint is not None:
            inputs.append(hint)

    return MacroAssistEntry(
        name=name,
        description=workflow.description,
        insertion=workflow_reference_insertion(name, workflow),
        reference_prefix=workflow_reference_prefix(workflow),
        kind=workflow_kind_value(workflow),
        input_signature=None,
        inputs=tuple(inputs),
        content_preview=(
            workflow.get_prompt_part_content() if workflow.is_simple_macro() else None
        ),
        memory_type=workflow.memory_type,
    )


def macro_assist_entry_from_local_macro(
    name: str,
    macro: Macro,
) -> MacroAssistEntry:
    """Build a TUI assist entry from a prompt-frontmatter local macro.

    Mirrors :func:`macro_assist_entry_from_workflow` (it routes through the
    same workflow projection) so a ``#_helper`` declared in the Frontmatter
    Panel's ``macros:`` field completes, soft-completes, and shows argument
    hints in every prompt pane exactly like a global macro.
    """
    from sase.macro.models import macro_to_workflow

    return macro_assist_entry_from_workflow(name, macro_to_workflow(macro))


def merge_local_macro_entries(
    base: list[MacroAssistEntry],
    local: list[MacroAssistEntry],
) -> list[MacroAssistEntry]:
    """Merge live local macro *local* entries over the *base* catalog.

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
    "build_macro_assist_entries",
    "merge_local_macro_entries",
    "macro_assist_entry_from_local_macro",
    "macro_assist_entry_from_workflow",
]
