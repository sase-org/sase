"""Process-wide shared state for the plan approval modal.

The modal shell (:mod:`~sase.ace.tui.modals.plan_approval_modal`) and its
behavior mixins each need the Esc-draft store and the frozen-decisions message,
so they live here under public names. Keeping them in one private module means
no split module has to import a ``_``-prefixed name from another.
"""

from __future__ import annotations

from typing import Any

__all__ = ["DECISIONS_FROZEN_MESSAGE", "esc_drafts"]

DECISIONS_FROZEN_MESSAGE = (
    "Decisions are fixed for this review. Change answers in the Decisions panel, "
    "or send feedback to change the questions."
)

# Esc draft store: request id -> draft values, for the life of the process.
esc_drafts: dict[str, dict[str, Any]] = {}
