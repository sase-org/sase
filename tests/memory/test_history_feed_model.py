"""Tests for the pure changes-feed view-model (phase `changes-lens`).

Covers the ``feed_model`` shared by the pager feed document and the
Memory pane Changes lens: day grouping, regen-only folding,
provenance items, word deltas, home tags, filtering, windowing,
dedupe, and parity with the document builder it was extracted from.
"""

from __future__ import annotations

import datetime
from typing import Any

from sase.memory.history import feed_model
from sase.memory.history.feed_document import build_feed_document

_DAY_ONE = 1790486400
_DAY_TWO = 1790400000


def _authored(
    subject_id: str = "note:project:sase/glossary/artifact",
    ordinal: int = 3,
    class_name: str = "authored",
    path: str = "sase/memory/glossary/artifact.md",
) -> dict[str, Any]:
    return {
        "subject_id": subject_id,
        "ordinal": ordinal,
        "class": class_name,
        "summary": {
            "section_paths": ["Definition"],
            "words_added": 20,
            "words_removed": 3,
        },
        "path": path,
        "commit": "d" * 40,
    }


def _changeset(
    commit: str = "d" * 40,
    committer_time: int = _DAY_ONE,
    subject: str = "feat(tabs): something",
    scope_key: str = "project:sase",
    bead: str = "sase-1bu.7",
    agent: str = "athena.sase-1bu.7",
    authored: list[dict[str, Any]] | None = None,
    consequences: list[dict[str, Any]] | None = None,
    regen_only: bool = False,
) -> dict[str, Any]:
    return {
        "scope_key": scope_key,
        "commit": commit,
        "committer_time": committer_time,
        "provenance": {"subject": subject, "bead": bead, "agent": agent},
        "regen_only": regen_only,
        "authored": authored if authored is not None else [_authored()],
        "consequences": consequences
        if consequences is not None
        else [
            {
                "subject_id": "instructions:project:sase/.",
                "ordinal": 12,
                "class": "rendered",
                "summary": {},
                "path": "AGENTS.md",
            }
        ],
    }


def _feed() -> dict[str, Any]:
    return {
        "changesets": [
            _changeset(),
            _changeset(
                commit="e" * 40,
                committer_time=_DAY_ONE + 600,
                subject="feat(home): tweak",
                scope_key="home",
                bead="",
                agent="",
                authored=[],
                consequences=[],
            ),
            _changeset(
                commit="f" * 40,
                committer_time=_DAY_TWO,
                subject="chore: regen",
                bead="",
                agent="",
                authored=[],
                consequences=[],
                regen_only=True,
            ),
        ],
    }


def test_day_helpers_match_document_forms() -> None:
    assert feed_model.day_key(_DAY_ONE) == datetime.datetime.fromtimestamp(
        _DAY_ONE
    ).strftime("%Y-%m-%d")
    assert feed_model.day_header(_DAY_ONE) == datetime.datetime.fromtimestamp(
        _DAY_ONE
    ).strftime("%a %b %d")
    assert feed_model.format_clock(_DAY_ONE) == datetime.datetime.fromtimestamp(
        _DAY_ONE
    ).strftime("%H:%M")
    assert feed_model.day_key(0) == "undated"
    assert feed_model.day_header(0) == "undated"
    assert feed_model.format_clock(0) == "--:--"


def test_words_suffix_skips_created() -> None:
    assert feed_model.words_suffix(
        {"words_added": 5, "words_removed": 2}, "authored"
    ) == ("+5w -2w")
    assert feed_model.words_suffix({"words_added": 200, "words_removed": 0}, "x") == (
        "+200w"
    )
    assert (
        feed_model.words_suffix({"words_added": 31, "words_removed": 4}, "created")
        == ""
    )


def test_entry_selector_prefers_path() -> None:
    assert feed_model.entry_selector({"path": "a/b.md", "subject_id": "x"}) == "a/b.md"
    assert feed_model.entry_selector({"subject_id": "web:g"}) == "web:g"
    assert feed_model.entry_selector({}) == ""


def test_entry_revision_prefers_ordinal() -> None:
    assert feed_model.entry_revision({"ordinal": 3, "commit": "abc"}, "zzz") == "v3"
    assert feed_model.entry_revision({"ordinal": 0, "commit": "abc"}, "zzz") == "abc"
    assert feed_model.entry_revision({"ordinal": 0}, "zzz") == "zzz"
    assert feed_model.entry_revision({"ordinal": 0}, None) == "now"


def test_provenance_items_follow_wire_order() -> None:
    items = feed_model.provenance_items(_changeset())
    assert [(item.visible, item.ref) for item in items] == [
        ("sase-1bu.7", "bead:sase-1bu.7"),
        ("athena.sase-1bu.7", "agent:athena.sase-1bu.7"),
        ("d" * 7, f"commit:{'d' * 40}"),
    ]
    assert feed_model.provenance_items({"provenance": {}}) == ()


def test_group_feed_splits_regen_and_preserves_order() -> None:
    days = feed_model.group_feed(_feed())
    assert [day.key for day in days] == [
        feed_model.day_key(_DAY_ONE),
        feed_model.day_key(_DAY_TWO),
    ]
    assert len(days[0].visible) == 2
    assert days[0].hidden == ()
    assert days[1].visible == ()
    assert len(days[1].hidden) == 1


def test_group_feed_survives_malformed_input() -> None:
    assert feed_model.group_feed({}) == ()
    assert feed_model.group_feed(None) == ()  # type: ignore[arg-type]


def test_first_subject_label_and_more_count() -> None:
    view = feed_model.changeset_view(
        _changeset(
            authored=[
                _authored("note:project:sase/a", path="a.md"),
                _authored("note:project:sase/b", path="b.md"),
            ]
        )
    )
    assert view.first_subject == "a"
    assert view.extra_subjects == 1
    assert view.word_delta == "+40w -6w"


def test_changeset_word_delta_sums_authored() -> None:
    assert feed_model.changeset_word_delta(_changeset()) == "+20w -3w"


def test_home_tag_only_for_home_scope() -> None:
    assert feed_model.changeset_view(_changeset(scope_key="home")).home is True
    assert feed_model.changeset_view(_changeset()).home is False


def test_filter_matches_subject_bead_agent_and_commit() -> None:
    views = tuple(feed_model.changeset_view(item) for item in _feed()["changesets"])
    assert len(feed_model.filter_changesets(views, "glossary")) == 1
    assert len(feed_model.filter_changesets(views, "sase-1bu.7")) == 1
    assert len(feed_model.filter_changesets(views, "athena")) == 1
    assert len(feed_model.filter_changesets(views, "d" * 8)) == 1
    assert feed_model.filter_changesets(views, "no-such-thing") == ()
    assert feed_model.filter_changesets(views, "") == views


def test_window_bounds_newest_and_counts_older() -> None:
    views = tuple(
        feed_model.changeset_view(
            _changeset(commit=f"{index:040d}", committer_time=_DAY_ONE + index)
        )
        for index in range(250)
    )
    shown, older = feed_model.window_changesets(views, 100)
    assert len(shown) == 100
    assert older == 150
    assert shown[0].commit == f"{0:040d}"


def test_dedupe_keeps_first_row() -> None:
    first = feed_model.changeset_view(_changeset())
    dup = feed_model.changeset_view(_changeset(subject="other"))
    assert feed_model.dedupe_changesets((first, dup)) == (first,)


def test_row_text_carries_clock_subject_delta_and_home() -> None:
    home = feed_model.changeset_view(
        _changeset(scope_key="home", authored=[], consequences=[])
    )
    line = feed_model.changeset_row_text(home)
    assert "⌂" in line
    row = feed_model.changeset_row_text(feed_model.changeset_view(_changeset()))
    assert "+20w" in row and "artifact" in row


def test_regen_and_older_text() -> None:
    assert "1 regenerated-only changeset" in feed_model.regen_count_text(1)
    assert "3 regenerated-only changesets" in feed_model.regen_count_text(3)
    assert "389 older" in feed_model.older_window_text(389)


def test_document_parity_with_grouped_days() -> None:
    """The document builder and the model agree on days and regen folds."""
    feed = _feed()
    result = build_feed_document(feed, "project:sase + home")
    days = feed_model.group_feed(feed)
    assert len(result.document.sections) == len(days)
    titles = [section.title for section in result.document.sections]
    assert titles == [day.title for day in days]
    assert len(result.folds) == sum(1 for day in days if day.hidden)
