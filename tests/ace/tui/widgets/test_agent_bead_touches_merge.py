"""Canonical-id, merge, and own-bead tests for agent bead touches.

Split from ``test_agent_bead_touches``; shared builders live in
``_agent_bead_touches_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from sase.ace.tui._bead_touches_merge import (
    BeadTouchEntry,
    _canonical_bead_id,
    merge_bead_touch_entries,
    own_bead_ids_for_agent,
)
from sase.core.bead_touch_index_facade import BeadNotePreview, BeadTouchClose
from tests.ace.tui.widgets._agent_bead_touches_helpers import (
    make_bead_read,
    make_bead_touch,
    make_bead_touch_display,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent

__all__ = [
    "test_canonical_bead_id_stays_exact_after_prefix",
    "test_canonical_bead_id_strips_prefix_and_whitespace",
    "test_merge_carries_creation_reason_from_creator_row_only",
    "test_merge_carries_newest_read_reason_first",
    "test_merge_counts_repeated_reads_and_read_only_beads",
    "test_merge_deduplicates_a_repeated_note_preview_id",
    "test_merge_empty_inputs_returns_empty",
    "test_merge_entry_type_defaults",
    "test_merge_folds_bead_read_into_touch_row",
    "test_merge_ignores_non_bead_refs",
    "test_merge_keeps_shared_agent_session_label",
    "test_merge_leaves_assigned_only_row_without_creation_reason",
    "test_merge_marks_own_beads_including_untouched",
    "test_merge_never_infers_creation_from_assignment",
    "test_merge_own_ids_match_after_canonicalization",
    "test_merge_prefers_standing_close_then_newest",
    "test_merge_ranks_newest_touch_first_with_id_tiebreak",
    "test_merge_selects_newest_note_across_session_members_with_its_role",
    "test_merge_single_touch_carries_verbs_title_and_timestamps",
    "test_merge_sums_verbs_across_agent_session_producers",
    "test_merge_skips_touches_without_a_bead_id",
    "test_merge_takes_first_available_title",
    "test_merge_titles_assigned_only_row_from_resolved_summaries",
    "test_own_bead_ids_collects_phase_epic_and_derived",
    "test_own_bead_ids_dedupes_and_skips_blanks",
    "test_own_bead_ids_derives_from_bead_work_name",
    "test_own_bead_ids_empty_for_ordinary_agent",
]


def test_canonical_bead_id_strips_prefix_and_whitespace() -> None:
    assert _canonical_bead_id("bead:sase-14j.4") == "sase-14j.4"
    assert _canonical_bead_id("  bead:sase-14j.4  ") == "sase-14j.4"
    assert _canonical_bead_id("sase-14j.4") == "sase-14j.4"
    assert _canonical_bead_id("bead:") == ""
    assert _canonical_bead_id("") == ""
    assert _canonical_bead_id(None) == ""


def test_canonical_bead_id_stays_exact_after_prefix() -> None:
    # No case folding and no suffix matching: dotted names must not merge.
    assert _canonical_bead_id("bead:SASE-14J.4") == "SASE-14J.4"
    assert _canonical_bead_id("plan:202608/design.md") == "plan:202608/design.md"


def test_merge_empty_inputs_returns_empty() -> None:
    assert merge_bead_touch_entries((), (), ()) == ()


def test_merge_single_touch_carries_verbs_title_and_timestamps() -> None:
    touch = make_bead_touch(
        "alpha",
        "sase-14j.4",
        verbs={"created": 1, "noted": 2},
        title="Resolve touches",
        first_at="2026-09-20T14:00:00Z",
        last_at="2026-09-20T16:41:02Z",
    )
    (entry,) = merge_bead_touch_entries((make_bead_touch_display(touch),), (), ())
    assert entry.bead_id == "sase-14j.4"
    assert entry.title == "Resolve touches"
    assert entry.verbs == {"created": 1, "noted": 2}
    assert entry.first_at == "2026-09-20T14:00:00Z"
    assert entry.last_at == "2026-09-20T16:41:02Z"
    assert entry.own is False
    assert entry.agent_label is None
    assert entry.creation_reason == ""


def test_merge_carries_creation_reason_from_creator_row_only() -> None:
    creator = make_bead_touch(
        "alpha",
        "sase-14j.4",
        verbs={"created": 1},
        title="Fix retry race",
        last_at="2026-09-20T16:41:02Z",
        creation_reason="A second agent reproduced dropped retries",
    )
    noter = make_bead_touch(
        "beta",
        "sase-14j.4",
        verbs={"noted": 1},
        last_at="2026-09-20T16:42:02Z",
    )
    (entry,) = merge_bead_touch_entries(
        (make_bead_touch_display(creator), make_bead_touch_display(noter, "coder")),
        (),
        (),
    )
    assert entry.creation_reason == "A second agent reproduced dropped retries"
    assert entry.creation_reason_truncated is False


def test_merge_leaves_assigned_only_row_without_creation_reason() -> None:
    (entry,) = merge_bead_touch_entries((), (), ("sase-14j.4",))
    assert entry.own is True
    assert entry.verbs == {}
    assert entry.creation_reason == ""


def test_merge_titles_assigned_only_row_from_resolved_summaries() -> None:
    (entry,) = merge_bead_touch_entries(
        (), (), ("sase-14j.4",), {"sase-14j.4": "File the retry race"}
    )
    assert entry.own is True
    assert entry.title == "File the retry race"
    assert entry.creation_reason == ""


def test_merge_never_infers_creation_from_assignment() -> None:
    touch = make_bead_touch(
        "alpha",
        "sase-14j.4",
        verbs={"noted": 1},
        title="File the retry race",
        last_at="2026-09-20T16:41:02Z",
    )
    (entry,) = merge_bead_touch_entries(
        (make_bead_touch_display(touch),),
        (),
        ("sase-14j.4",),
        {"sase-14j.4": "Resolved summary title"},
    )
    assert entry.own is True
    assert entry.title == "File the retry race"
    assert entry.creation_reason == ""


def test_merge_selects_newest_note_across_session_members_with_its_role() -> None:
    first = BeadNotePreview(
        id="sase-14j.4:1",
        author="alpha",
        timestamp="2026-09-20T16:00:00Z",
        text="planner note",
    )
    newest = BeadNotePreview(
        id="sase-14j.4:2",
        author="beta",
        timestamp="2026-09-20T16:01:00Z",
        text="coder note",
    )
    (entry,) = merge_bead_touch_entries(
        (
            make_bead_touch_display(
                make_bead_touch(
                    "alpha",
                    "sase-14j.4",
                    current_note_count=1,
                    note_preview=first,
                ),
                "plan",
            ),
            make_bead_touch_display(
                make_bead_touch(
                    "beta",
                    "sase-14j.4",
                    current_note_count=1,
                    note_preview=newest,
                ),
                "coder",
            ),
        ),
        (),
    )

    assert entry.current_note_count == 2
    assert entry.note_preview == newest
    assert entry.note_agent_label == "coder"
    assert entry.agent_label is None


def test_merge_deduplicates_a_repeated_note_preview_id() -> None:
    preview = BeadNotePreview(
        id="sase-14j.4:1",
        author="alpha",
        timestamp="2026-09-20T16:00:00Z",
        text="one note",
    )
    (entry,) = merge_bead_touch_entries(
        (
            make_bead_touch_display(
                make_bead_touch(
                    "alpha",
                    "sase-14j.4",
                    current_note_count=1,
                    note_preview=preview,
                )
            ),
            make_bead_touch_display(
                make_bead_touch(
                    "alpha",
                    "sase-14j.4",
                    current_note_count=1,
                    note_preview=preview,
                )
            ),
        ),
        (),
    )

    assert entry.current_note_count == 1
    assert entry.note_preview == preview


def test_merge_ranks_newest_touch_first_with_id_tiebreak() -> None:
    older = make_bead_touch("a", "sase-9b", last_at="2026-09-20T15:00:00Z")
    newer = make_bead_touch("a", "sase-9a", last_at="2026-09-20T16:00:00Z")
    tied_b = make_bead_touch("a", "sase-9c", last_at="2026-09-20T16:00:00Z")
    tied_a = make_bead_touch("a", "sase-9b2", last_at="2026-09-20T16:00:00Z")
    entries = merge_bead_touch_entries(
        (
            make_bead_touch_display(older),
            make_bead_touch_display(newer),
            make_bead_touch_display(tied_b),
            make_bead_touch_display(tied_a),
        ),
        (),
        (),
    )
    assert [entry.bead_id for entry in entries] == [
        "sase-9a",
        "sase-9b2",
        "sase-9c",
        "sase-9b",
    ]


def test_merge_folds_bead_read_into_touch_row() -> None:
    touch = make_bead_touch(
        "alpha",
        "sase-14j.4",
        verbs={"noted": 2},
        title="Resolve touches",
        first_at="2026-09-20T14:00:00Z",
        last_at="2026-09-20T15:00:00Z",
    )
    read = make_bead_read("bead:sase-14j.4", "2026-09-20T16:00:00Z", read_id="r1")
    (entry,) = merge_bead_touch_entries((make_bead_touch_display(touch),), (read,), ())
    assert entry.verbs == {"noted": 2, "read": 1}
    assert entry.last_at == "2026-09-20T16:00:00Z"
    assert entry.first_at == "2026-09-20T14:00:00Z"
    assert entry.title == "Resolve touches"


def test_merge_counts_repeated_reads_and_read_only_beads() -> None:
    reads = (
        make_bead_read("bead:sase-14j.4", "2026-09-20T16:00:00Z", read_id="r1"),
        make_bead_read("bead:sase-14j.4", "2026-09-20T16:05:00Z", read_id="r2"),
    )
    (entry,) = merge_bead_touch_entries((), reads, ())
    assert entry.bead_id == "sase-14j.4"
    assert entry.verbs == {"read": 2}
    assert entry.first_at == "2026-09-20T16:00:00Z"
    assert entry.last_at == "2026-09-20T16:05:00Z"


def test_merge_carries_newest_read_reason_first() -> None:
    reads = (
        make_bead_read(
            "bead:sase-14j.4",
            "2026-09-20T16:00:00Z",
            read_id="r1",
            reason="  older reason  ",
        ),
        make_bead_read(
            "bead:sase-14j.4",
            "2026-09-20T16:05:00Z",
            read_id="r2",
            reason="newer reason",
        ),
        make_bead_read(
            "bead:sase-14j.4",
            "2026-09-20T16:06:00Z",
            read_id="r3",
            reason="newer reason",
        ),
        make_bead_read(
            "bead:sase-14j.4",
            "",
            read_id="r4",
            reason="   ",
        ),
    )
    (entry,) = merge_bead_touch_entries((), reads, ())
    assert entry.read_reasons == ("newer reason", "older reason")


def test_merge_ignores_non_bead_refs() -> None:
    reads = (
        make_bead_read("plan:202608/design.md", "2026-09-20T16:00:00Z", read_id="r1"),
        make_bead_read("memory:tui_perf.md", "2026-09-20T16:01:00Z", read_id="r2"),
        make_bead_read("bead:", "2026-09-20T16:02:00Z", read_id="r3"),
    )
    assert merge_bead_touch_entries((), reads, ()) == ()


def test_merge_marks_own_beads_including_untouched() -> None:
    touch = make_bead_touch(
        "alpha",
        "sase-14j.4",
        verbs={"closed": 1},
        last_at="2026-09-20T16:00:00Z",
    )
    entries = merge_bead_touch_entries(
        (make_bead_touch_display(touch),), (), ("sase-14j", "sase-14j.4")
    )
    by_id = {entry.bead_id: entry for entry in entries}
    assert by_id["sase-14j.4"].own is True
    assert by_id["sase-14j.4"].verbs == {"closed": 1}
    untouched = by_id["sase-14j"]
    assert untouched.own is True
    assert untouched.verbs == {}
    assert untouched.last_at == ""
    # Timestamp-less own-only beads sort after every touched bead.
    assert entries[-1].bead_id == "sase-14j"


def test_merge_own_ids_match_after_canonicalization() -> None:
    entries = merge_bead_touch_entries((), (), ("  sase-14j.4  ",))
    assert len(entries) == 1
    assert entries[0].own is True


def test_merge_skips_touches_without_a_bead_id() -> None:
    touch = make_bead_touch("alpha", "   ", verbs={"noted": 1})
    assert merge_bead_touch_entries((make_bead_touch_display(touch),), (), ()) == ()


def test_merge_takes_first_available_title() -> None:
    first = make_bead_touch("a", "sase-1", title="")
    second = make_bead_touch("b", "sase-1", title="Kept title")
    (entry,) = merge_bead_touch_entries(
        (make_bead_touch_display(first), make_bead_touch_display(second)), (), ()
    )
    assert entry.title == "Kept title"


def test_merge_sums_verbs_across_agent_session_producers() -> None:
    first = make_bead_touch("a", "sase-1", verbs={"noted": 1})
    second = make_bead_touch("b", "sase-1", verbs={"noted": 2, "closed": 1})
    (entry,) = merge_bead_touch_entries(
        (
            make_bead_touch_display(first, "plan"),
            make_bead_touch_display(second, "coder"),
        ),
        (),
        (),
    )
    assert entry.verbs == {"noted": 3, "closed": 1}
    assert entry.agent_label is None


def test_merge_keeps_shared_agent_session_label() -> None:
    touch = make_bead_touch("a", "sase-1", verbs={"noted": 1})
    read = make_bead_read(
        "bead:sase-1", "2026-09-20T16:00:00Z", read_id="r1", label="plan"
    )
    (entry,) = merge_bead_touch_entries(
        (make_bead_touch_display(touch, "plan"),), (read,), ()
    )
    assert entry.agent_label == "plan"


def test_merge_entry_type_defaults() -> None:
    entry = BeadTouchEntry(bead_id="sase-1")
    assert entry.title == ""
    assert entry.verbs == {}
    assert entry.own is False
    assert entry.agent_label is None
    assert entry.agent_close is None


def test_merge_prefers_standing_close_then_newest() -> None:
    older_standing = BeadTouchClose(
        closed_at="2026-09-20T15:00:00Z",
        resolution="done",
        standing=True,
    )
    newer_undone = BeadTouchClose(
        closed_at="2026-09-20T16:00:00Z",
        resolution="done",
        standing=False,
    )
    (standing_entry,) = merge_bead_touch_entries(
        (
            make_bead_touch_display(make_bead_touch("a", "sase-1", close=newer_undone)),
            make_bead_touch_display(
                make_bead_touch("b", "sase-1", close=older_standing)
            ),
        ),
        (),
        (),
    )
    assert standing_entry.agent_close == older_standing

    older = BeadTouchClose(closed_at="2026-09-20T15:00:00Z", standing=False)
    newer = BeadTouchClose(
        closed_at="2026-09-20T16:00:00Z",
        resolution="canceled",
        reason="duplicate",
        standing=False,
    )
    (newest_entry,) = merge_bead_touch_entries(
        (
            make_bead_touch_display(make_bead_touch("a", "sase-1", close=older)),
            make_bead_touch_display(make_bead_touch("b", "sase-1", close=newer)),
        ),
        (),
        (),
    )
    assert newest_entry.agent_close == newer


def test_own_bead_ids_collects_phase_epic_and_derived() -> None:
    agent = make_agent(
        agent_name="worker",
        phase_bead_id="sase-14j.4",
        epic_bead_id="sase-14j",
    )
    assert own_bead_ids_for_agent(agent) == ("sase-14j.4", "sase-14j")


def test_own_bead_ids_dedupes_and_skips_blanks() -> None:
    agent = make_agent(
        agent_name="worker",
        phase_bead_id="sase-14j.4",
        epic_bead_id="sase-14j.4",
    )
    assert own_bead_ids_for_agent(agent) == ("sase-14j.4",)


def test_own_bead_ids_derives_from_bead_work_name() -> None:
    agent = make_agent(agent_name="sase-14j.4")
    assert own_bead_ids_for_agent(agent) == ("sase-14j.4",)


def test_own_bead_ids_empty_for_ordinary_agent() -> None:
    assert own_bead_ids_for_agent(make_agent(agent_name="worker")) == ()
