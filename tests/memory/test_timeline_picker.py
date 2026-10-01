"""Unit tests for the timeline picker rows (memory side)."""

from __future__ import annotations

import time

from sase.memory.history.timeline_picker import (
    _normalize_picker_compare,
    build_picker_rows,
    filter_picker_rows,
    hidden_picker_rows,
    hidden_summary_text,
    picker_footer_preview,
    picker_header_text,
    picker_pill_text,
    visible_picker_rows,
)

_NOW = 1790700000


def _timeline() -> dict[str, object]:
    return {
        "versions": [
            {
                "ordinal": 0,
                "class": "uncommitted",
                "commit": "",
                "committer_time": 0,
                "path": "sase/memory/gotchas.md",
                "summary": {},
                "provenance": {},
            },
            {
                "ordinal": 0,
                "class": "staged",
                "commit": "",
                "committer_time": 0,
                "path": "sase/memory/gotchas.md",
                "summary": {},
                "provenance": {},
            },
            {
                "ordinal": 9,
                "class": "authored",
                "commit": "a" * 40,
                "committer_time": 1790486400,
                "path": "sase/memory/gotchas.md",
                "summary": {
                    "section_paths": ["Default Keymap Config"],
                    "words_added": 31,
                    "words_removed": 4,
                },
                "provenance": {
                    "agent": "athena.sase-1bc.12",
                    "bead": "sase-1bc.12",
                    "subject": "feat(tui): keymaps",
                },
            },
            {
                "ordinal": 8,
                "class": "promoted",
                "commit": "b" * 40,
                "committer_time": 1790054400,
                "path": "sase/memory/gotchas.md",
                "summary": {
                    "section_paths": [],
                    "words_added": 0,
                    "words_removed": 0,
                    "frontmatter_phrase": "promoted reference → core",
                },
                "provenance": {
                    "agent": "athena.sase-1au.5",
                    "bead": "sase-1au.5",
                    "subject": "feat(memory): promote",
                },
            },
            {
                "ordinal": 7,
                "class": "moved",
                "commit": "c" * 40,
                "committer_time": 1789000000,
                "path": "memory/gotchas.md",
                "summary": {},
                "provenance": {},
            },
            {
                "ordinal": 6,
                "class": "reflow",
                "commit": "d" * 40,
                "committer_time": 1788900000,
                "path": "memory/gotchas.md",
                "summary": {},
                "provenance": {},
            },
            {
                "ordinal": 1,
                "class": "created",
                "commit": "e" * 40,
                "committer_time": 1788000000,
                "path": "memory/gotchas.md",
                "summary": {"section_paths": [], "created_words": 412},
                "provenance": {},
            },
        ]
    }


def test_build_rows_covers_worktree_staged_and_hidden() -> None:
    rows = build_picker_rows(_timeline(), now_epoch=_NOW)

    assert [row["label"] for row in rows] == [
        "now",
        "stg",
        "v9",
        "v8",
        "v7",
        "v6",
        "v1",
    ]
    assert rows[0]["glyph"] == "◌"
    assert "worktree" in rows[0]["display"]
    assert "not durable until committed" in rows[0]["display"]
    assert "staged" in rows[1]["display"]
    assert "§ Default Keymap Config" in rows[2]["display"]
    assert "+31w" in rows[2]["display"] and "-4w" in rows[2]["display"]
    assert "sase-1bc.12" in rows[2]["display"]
    assert rows[2]["hidden"] is False
    assert rows[4]["hidden"] is True
    assert rows[5]["hidden"] is True
    assert rows[6]["hidden"] is False


def test_visible_rows_hide_moves_and_reflows_until_dot() -> None:
    rows = build_picker_rows(_timeline(), now_epoch=_NOW)

    listed = visible_picker_rows(rows, show_hidden=False)
    assert [row["label"] for row in listed] == ["now", "stg", "v9", "v8", "v1"]

    shown = visible_picker_rows(rows, show_hidden=True)
    assert len(shown) == len(rows)


def test_hidden_summary_breaks_down_moves_and_reflows() -> None:
    rows = build_picker_rows(_timeline(), now_epoch=_NOW)
    hidden = hidden_picker_rows(rows)

    assert hidden_summary_text(hidden) == "·· 2 hidden (↦ 1 move, ≈ 1 reflow) · . show"
    assert hidden_summary_text(()) == ""


def test_filter_matches_section_agent_bead_and_words() -> None:
    rows = build_picker_rows(_timeline(), now_epoch=_NOW)
    listed = visible_picker_rows(rows, show_hidden=True)

    assert [row["label"] for row in filter_picker_rows(listed, "keymap")] == ["v9"]
    assert [row["label"] for row in filter_picker_rows(listed, "sase-1au.5")] == ["v8"]
    assert [row["label"] for row in filter_picker_rows(listed, "promote core")] == [
        "v8"
    ]
    assert [row["label"] for row in filter_picker_rows(listed, "+31w")] == ["v9"]
    assert [row["label"] for row in filter_picker_rows(listed, "worktree")] == ["now"]
    assert filter_picker_rows(listed, "no-such-token") == ()


def test_header_names_subject_counts_and_filter() -> None:
    header = picker_header_text(
        subject_display="gotchas.md",
        total_committed=9,
        hidden_count=2,
        show_hidden=False,
        query="",
    )

    assert header == "gotchas.md · 9 versions · 2 hidden — / filter"

    filtered = picker_header_text(
        subject_display="gotchas.md",
        total_committed=9,
        hidden_count=2,
        show_hidden=False,
        query="keymap",
    )
    assert filtered.endswith("— / keymap")


def _clean_timeline() -> dict[str, object]:
    versions: list[dict[str, object]] = []
    for ordinal, committer in ((25, 1790486400), (24, 1790054400), (1, 1788000000)):
        versions.append(
            {
                "ordinal": ordinal,
                "class": "authored",
                "commit": f"{ordinal:040d}",
                "committer_time": committer,
                "path": "sase/memory/gotchas.md",
                "summary": {
                    "section_paths": ["Default Keymap Config"],
                    "words_added": 31,
                    "words_removed": 4,
                },
                "provenance": {
                    "agent": "athena.sase-1bc.12",
                    "bead": "sase-1bc.12",
                    "subject": "feat(tui): keymaps",
                },
            }
        )
    return {"versions": versions}


def test_rows_carry_structured_column_cells() -> None:
    rows = build_picker_rows(_timeline(), now_epoch=_NOW)

    committed = rows[2]
    assert committed["date"] != ""
    assert committed["age"] != ""
    assert committed["change"] == "§ Default Keymap Config"
    assert committed["words"] == "+31w -4w"
    assert committed["by"] == "sase-1bc.12"
    assert committed["sha"] == "a" * 7
    assert committed["detail"] == ""
    assert committed["is_now_alias"] is False

    pseudo = rows[0]
    assert pseudo["date"] == ""
    assert pseudo["detail"] == "uncommitted · not durable until committed"


def test_clean_now_row_is_synthesized_first_with_alias_tag() -> None:
    rows = build_picker_rows(
        _clean_timeline(), now_epoch=_NOW, now_matches_newest=True, newest=25
    )

    assert [row["label"] for row in rows] == ["now", "v25", "v24", "v1"]
    now_row = rows[0]
    assert now_row["pseudo"] is True
    assert now_row["detail"] == "≡ v25 · the live file"
    assert filter_picker_rows(rows, "live file")[0]["label"] == "now"
    newest_row = rows[1]
    assert newest_row["is_now_alias"] is True
    assert rows[2]["is_now_alias"] is False


def test_clean_now_row_without_d3_has_no_alias() -> None:
    rows = build_picker_rows(
        _clean_timeline(), now_epoch=_NOW, now_matches_newest=False, newest=25
    )

    assert rows[0]["label"] == "now"
    assert rows[0]["detail"] == "the live file"
    assert all(row["is_now_alias"] is False for row in rows)


def test_dirty_now_row_keeps_uncommitted_detail() -> None:
    rows = build_picker_rows(_timeline(), now_epoch=_NOW)

    assert rows[0]["label"] == "now"
    assert rows[0]["class"] == "uncommitted"
    assert rows[0]["detail"] == "uncommitted · not durable until committed"


def test_dates_gain_a_year_outside_the_current_year() -> None:
    old = dict(_clean_timeline()["versions"][0])  # type: ignore[index]
    old["committer_time"] = 1670000000  # Dec 2022
    rows = build_picker_rows({"versions": [old]}, now_epoch=_NOW)

    assert rows[1]["date"].endswith("2022")
    assert rows[1]["date"].startswith("Dec")
    assert rows[0]["label"] == "now"


def test_header_carries_the_open_version_pill() -> None:
    header = picker_header_text(
        subject_display="gotchas.md",
        total_committed=25,
        hidden_count=4,
        show_hidden=False,
        query="",
        pill_text="⟲ PAST · v24",
    )

    assert header == "gotchas.md · 25 versions · 4 hidden · [⟲ PAST · v24] — / filter"


def test_pill_text_covers_every_kind() -> None:
    assert picker_pill_text("past", 24, 25) == "⟲ PAST · v24"
    assert picker_pill_text("now", 25, 25) == "● NOW · v25"
    assert picker_pill_text("now_dirty", 0, 25) == "◌ NOW"
    assert picker_pill_text("deleted", 12, 12) == "✖ DELETED"
    assert picker_pill_text("loading", 0, 0) == ""


def test_normalize_compare_always_reads_older_to_newer() -> None:
    assert _normalize_picker_compare(open_ordinal=24, cursor_ordinal=21) == (21, 24)
    assert _normalize_picker_compare(open_ordinal=21, cursor_ordinal=24) == (21, 24)
    assert _normalize_picker_compare(open_ordinal=0, cursor_ordinal=24) == (24, 0)
    assert _normalize_picker_compare(open_ordinal=24, cursor_ordinal=0) == (24, 0)
    assert _normalize_picker_compare(open_ordinal=24, cursor_ordinal=24) is None
    assert _normalize_picker_compare(open_ordinal=0, cursor_ordinal=0) is None


def test_footer_previews_open_and_compare_actions() -> None:
    open_row = {"ordinal": 24, "class": "authored", "label": "v24"}
    older_row = {"ordinal": 21, "class": "authored", "label": "v21"}
    now_row = {"ordinal": 0, "class": "", "label": "now"}

    assert (
        picker_footer_preview(open_row, open_ordinal=24, open_class="")
        == "● open v24 · . hidden · / filter · esc close"
    )
    assert (
        picker_footer_preview(older_row, open_ordinal=24, open_class="")
        == "⏎ open v21 · = compare v21 → v24 · . hidden · / filter · esc close"
    )
    assert (
        picker_footer_preview(
            {"ordinal": 25, "class": "authored", "label": "v25"},
            open_ordinal=24,
            open_class="",
        )
        == "⏎ open v25 · = compare v24 → v25 · . hidden · / filter · esc close"
    )
    assert (
        picker_footer_preview(now_row, open_ordinal=24, open_class="")
        == "⏎ open now · = compare v24 → now · . hidden · / filter · esc close"
    )
    assert (
        picker_footer_preview(now_row, open_ordinal=0, open_class="")
        == "● open now · . hidden · / filter · esc close"
    )
    assert picker_footer_preview(None, open_ordinal=24) == (
        "⏎ open · . hidden · / filter · esc close"
    )


def test_footer_sheds_hints_but_keeps_actions_when_narrow() -> None:
    row = {"ordinal": 129, "class": "authored", "label": "v129"}

    preview = picker_footer_preview(row, open_ordinal=130, open_class="", width=52)
    assert preview == "⏎ open v129 · = compare v129 → v130 · esc close"
    assert picker_footer_preview(
        row, open_ordinal=130, open_class="", width=0
    ).endswith("· . hidden · / filter · esc close")


def test_large_timelines_stay_fast() -> None:
    versions: list[dict[str, object]] = []
    for ordinal in range(1, 501):
        versions.append(
            {
                "ordinal": ordinal,
                "class": "authored",
                "commit": f"{ordinal:040d}",
                "committer_time": 1790486400,
                "path": "AGENTS.md",
                "summary": {
                    "section_paths": [f"Section {ordinal}"],
                    "words_added": ordinal,
                    "words_removed": 0,
                },
                "provenance": {"agent": f"athena.sase-1dr.{ordinal}"},
            }
        )
    timeline = {"versions": versions}

    from sase.pager.history.timeline import picker_window

    started = time.perf_counter()
    rows = build_picker_rows(timeline, now_epoch=_NOW)
    matches = filter_picker_rows(rows, "section 499")
    picker_window(len(rows), 250, 20)
    elapsed = time.perf_counter() - started

    assert len(rows) == 501
    assert rows[0]["label"] == "now"
    assert [row["label"] for row in matches] == ["v499"]
    assert elapsed < 2.0
