"""Tests for the shared ⚐ stranded-work presentation vocabulary."""

from __future__ import annotations

from sase.bead.stranded_presentation import (
    STRANDED_BREADCRUMB_STYLE,
    STRANDED_GLYPH,
    STRANDED_LEAF_STYLE,
    STRANDED_WORD,
    blocked_sentence,
    stranded_age_label,
    stranded_cause_sentence,
)
from sase.core.stranded_work_facade import StrandedWorkVerdict


def _verdict(**kwargs: object) -> StrandedWorkVerdict:
    values = {
        "bead_id": "sase-1.2",
        "kind": "phase",
        "state": "stranded",
        **kwargs,
    }
    return StrandedWorkVerdict(**values)  # type: ignore[arg-type]


def test_glyph_and_word_and_styles() -> None:
    assert STRANDED_GLYPH == "⚐"
    assert STRANDED_WORD == "STRANDED"
    assert STRANDED_LEAF_STYLE == "bold #FFAF00"
    assert STRANDED_BREADCRUMB_STYLE == "#AF8700"


def test_cause_sentences_cover_each_reason() -> None:
    expected = {
        "failed": "latest turn failed; nothing resumes it",
        "stopped": "latest turn was stopped; nothing resumes it",
        "lost": "latest turn is gone; nothing resumes it",
        "child_landed": "child epic landed; the phase is still open",
        "close_failed": "ended with bead_action close; the bead is still open",
        "kept": "ended with bead_action keep; nothing resumes it",
        "unclosed": "ended without closing the bead; nothing resumes it",
    }
    for reason, sentence in expected.items():
        assert stranded_cause_sentence(_verdict(reason=reason)) == sentence


def test_followup_failed_names_the_member() -> None:
    sentence = stranded_cause_sentence(
        _verdict(reason="followup_failed", last_turn="sase-1.2--mon")
    )
    assert sentence == "sase-1.2--mon follow-up failed; nothing resumes it"
    fallback = stranded_cause_sentence(
        _verdict(reason="followup_failed", session="sase-1.2")
    )
    assert fallback == "sase-1.2 follow-up failed; nothing resumes it"


def test_age_label_uses_hours_until_a_day_then_days() -> None:
    now = 1_000_000.0
    assert stranded_age_label(now - 23 * 3600, now) == "23h"
    assert stranded_age_label(now - 31 * 3600, now) == "1d"
    assert stranded_age_label(now - 2 * 86400, now) == "2d"
    assert stranded_age_label(None, now) == ""


def test_blocked_sentence_names_the_leaf_and_extra_count() -> None:
    one = _verdict(blocked_by=("sase-1.2",))
    assert blocked_sentence(one) == "blocked by stranded sase-1.2"
    two = _verdict(blocked_by=("sase-1.2", "sase-1.3"))
    assert blocked_sentence(two) == "blocked by stranded sase-1.2 (+1 more)"
    assert blocked_sentence(_verdict()) == ""
