"""Resolve the bead-automation xprompts by their semantic tags.

The ``sase bead work`` machinery binds three roles — *create the epic*,
*work a phase bead*, *land the epic* — to xprompts via
:class:`sase.xprompt.tags.XPromptTag`. Built-in xprompts ship with these
tags pre-applied; users may override any of them by tagging an xprompt
of their own with the same tag (the loader's precedence chain handles
which one wins, and :func:`get_by_tag_strict` rejects ambiguous setups).
"""

from __future__ import annotations

from sase.xprompt.tags import XPromptTag, get_by_tag_strict
from sase.xprompt.workflow_models import Workflow


class BeadXPromptNotFoundError(LookupError):
    """Raised when no xprompt is tagged with a required bead-automation tag."""


def _resolve_bead_xprompt(tag: XPromptTag, project: str | None = None) -> Workflow:
    """Return the xprompt tagged with *tag*.

    Raises:
        BeadXPromptNotFoundError: if no xprompt has the tag.
        ValueError: if multiple xprompts have the tag (propagated from
            :func:`get_by_tag_strict`).
    """
    wf = get_by_tag_strict(tag, project=project)
    if wf is None:
        raise BeadXPromptNotFoundError(
            f"No xprompt is tagged with {tag.value!r}. Tag a built-in or "
            f"custom xprompt with `tags: {tag.value}` to enable this role."
        )
    return wf


def resolve_work_phase_xprompt(project: str | None = None) -> Workflow:
    """Resolve the xprompt tagged ``work_phase_bead``."""
    return _resolve_bead_xprompt(XPromptTag.work_phase_bead, project=project)


def resolve_land_epic_xprompt(project: str | None = None) -> Workflow:
    """Resolve the xprompt tagged ``land_epic``."""
    return _resolve_bead_xprompt(XPromptTag.land_epic, project=project)
