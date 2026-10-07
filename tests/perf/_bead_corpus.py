"""Deterministic synthetic bead corpus with realistic shape at any scale.

This module is the public facade for the bead-corpus helpers; the
implementation lives in :mod:`tests.perf._bead_corpus_common`,
:mod:`tests.perf._bead_corpus_events`, :mod:`tests.perf._bead_corpus_beads`,
and :mod:`tests.perf._bead_corpus_store`. It re-exports every public name
of the original module so existing imports keep working.
"""

from __future__ import annotations

from tests.perf._bead_corpus_common import mint_event_id
from tests.perf._bead_corpus_store import (
    BASE_PLANS,
    BASE_TASKS,
    CLOSED_PHASE_FRACTION,
    CLOSED_PLAN_FRACTION,
    CLOSED_TASK_FRACTION,
    LIVE_EPIC_COUNT,
    MAX_PHASES_PER_EPIC,
    MIN_PHASES_PER_EPIC,
    TIMELINE_DAYS,
    generate_corpus,
    summarize_corpus,
)

__all__ = [
    "BASE_PLANS",
    "BASE_TASKS",
    "CLOSED_PHASE_FRACTION",
    "CLOSED_PLAN_FRACTION",
    "CLOSED_TASK_FRACTION",
    "LIVE_EPIC_COUNT",
    "MAX_PHASES_PER_EPIC",
    "MIN_PHASES_PER_EPIC",
    "TIMELINE_DAYS",
    "generate_corpus",
    "mint_event_id",
    "summarize_corpus",
]
