"""Unit tests for the timeline picker rows (memory side)."""

from __future__ import annotations

import time

from sase.memory.history.timeline_picker import (
    build_picker_rows,
    filter_picker_rows,
    hidden_picker_rows,
    hidden_summary_text,
    picker_header_text,
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

    assert len(rows) == 500
    assert [row["label"] for row in matches] == ["v499"]
    assert elapsed < 2.0
