"""Resolve the bead-automation macros by their semantic tags.

The ``sase bead work`` machinery binds bead automation roles to macros via
:class:`sase.macro.tags.MacroTag`. Built-in macros ship with these
tags pre-applied; users may override any of them by tagging a macro
of their own with the same tag (the loader's precedence chain handles
which one wins, and :func:`get_by_tag_strict` rejects ambiguous setups).
"""

from __future__ import annotations

from sase.macro.tags import MacroTag, get_by_tag_strict
from sase.macro.workflow_models import Workflow


class BeadMacroNotFoundError(LookupError):
    """Raised when no macro is tagged with a required bead-automation tag."""


def _resolve_bead_macro(tag: MacroTag, project: str | None = None) -> Workflow:
    """Return the macro tagged with *tag*.

    Raises:
        BeadMacroNotFoundError: if no macro has the tag.
        ValueError: if multiple macros have the tag (propagated from
            :func:`get_by_tag_strict`).
    """
    wf = get_by_tag_strict(tag, project=project)
    if wf is None:
        raise BeadMacroNotFoundError(
            f"No macro is tagged with {tag.value!r}. Tag a built-in or "
            f"custom macro with `tags: {tag.value}` to enable this role."
        )
    return wf


def resolve_work_phase_macro(project: str | None = None) -> Workflow:
    """Resolve the macro tagged ``work_phase_bead``."""
    return _resolve_bead_macro(MacroTag.work_phase_bead, project=project)


def resolve_work_task_macro(project: str | None = None) -> Workflow:
    """Resolve the macro tagged ``work_task_bead``."""
    return _resolve_bead_macro(MacroTag.work_task_bead, project=project)


def resolve_land_epic_macro(project: str | None = None) -> Workflow:
    """Resolve the macro tagged ``land_epic``."""
    return _resolve_bead_macro(MacroTag.land_epic, project=project)
