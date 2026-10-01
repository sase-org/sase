"""Text rendering goldens for memory history (colour off)."""

from __future__ import annotations

from rich.console import Console

from sase.memory.history import render_text


def _console() -> Console:
    return Console(record=True, width=100, force_terminal=False)


def _version(
    ordinal: int,
    class_name: str,
    commit: str,
    committer_time: int,
    **extra: object,
) -> dict[str, object]:
    version: dict[str, object] = {
        "ordinal": ordinal,
        "commit": commit,
        "committer_time": committer_time,
        "author_time": committer_time,
        "path": "sase/memory/tui.md",
        "class": class_name,
        "hidden_by_default": class_name in ("moved", "reflow", "whitespace"),
        "summary": {
            "section_paths": ["Default Keymap Config"],
            "words_added": 31,
            "words_removed": 4,
            "frontmatter_phrase": None,
            "volume": 35,
        },
        "provenance": {
            "agent": "athena.sase-1bc.12",
            "bead": "sase-1bc.12",
            "subject": "feat(tui): something",
        },
    }
    version.update(extra)
    return version


def test_timeline_header_rows_and_hidden_summary() -> None:
    console = _console()
    timeline = {
        "subject_id": "note:project:sase/tui",
        "path": "sase/memory/tui.md",
        "state": "Tracked",
        "versions": [
            _version(9, "authored", "a" * 40, 1790486400),
            _version(8, "promoted", "b" * 40, 1790054400),
            _version(7, "moved", "c" * 40, 1789000000),
        ],
    }

    render_text.render_timeline(
        console,
        timeline,
        "tui",
        "project:sase",
        now_epoch=1790700000,
        include_hidden=False,
    )

    text = console.export_text()
    assert "tui · note · project sase" in text
    assert "3 versions (1 hidden)" in text
    assert "v9" in text and "v8" in text
    assert "v7" not in text
    assert "+31w -4w" in text
    assert "sase-1bc.12" in text
    assert "1 hidden (↦ 1 move) · -a to show" in text


def test_timeline_shows_hidden_with_all() -> None:
    console = _console()
    timeline = {
        "subject_id": "note:project:sase/tui",
        "path": "sase/memory/tui.md",
        "state": "Tracked",
        "versions": [_version(7, "moved", "c" * 40, 1789000000)],
    }

    render_text.render_timeline(
        console,
        timeline,
        "tui",
        "project:sase",
        now_epoch=1790700000,
        include_hidden=True,
    )

    assert "v7" in console.export_text()


def test_version_renders_header_and_body() -> None:
    console = _console()
    response = {
        "subject_id": "note:project:sase/tui",
        "version": _version(8, "promoted", "b" * 40, 1790054400),
        "body": "# Tui\n\nBody here.\n",
        "body_missing": False,
    }

    render_text.render_version(
        console, response, "tui", "project:sase", now_epoch=1790700000
    )

    text = console.export_text()
    assert "tui · v8 ·" in text
    assert "Body here." in text


def test_diff_uses_piped_word_form_when_plain() -> None:
    console = _console()
    compare = {
        "base": {"ordinal": 7},
        "target": {"ordinal": 8},
        "comparison": {
            "frontmatter": {"entries": [], "type_change": None},
            "word_ops": [
                {
                    "target_line": 1,
                    "ops": [
                        {"kind": "equal", "text": "agents ", "start": 0, "end": 7},
                        {"kind": "delete", "text": "shells", "start": 7, "end": 7},
                        {"kind": "insert", "text": "processes", "start": 7, "end": 16},
                    ],
                }
            ],
            "hunks": [
                {
                    "target_start": 1,
                    "target_end": 2,
                    "base_start": 1,
                    "base_end": 2,
                    "section_path": ["PNG Snapshot Tests"],
                }
            ],
            "removal_anchors": [],
            "stats": {"words_added": 1, "words_removed": 1},
            "unified_diff": "",
        },
    }

    render_text.render_diff(
        console, compare, plain=True, target_body="agents processes"
    )

    text = console.export_text()
    assert "agents [-shells-]{+processes+}" in text
    assert "§ PNG Snapshot Tests" in text


def test_diff_falls_back_to_unified_without_word_ops() -> None:
    console = _console()
    compare = {
        "base": {"ordinal": 1},
        "target": {"ordinal": 2},
        "comparison": {
            "frontmatter": {"entries": [], "type_change": None},
            "word_ops": [],
            "hunks": [],
            "removal_anchors": [],
            "stats": {},
            "unified_diff": "@@ -1 +1 @@\n-old\n+new\n",
        },
    }

    render_text.render_diff(console, compare, plain=True)

    assert "-old" in console.export_text()


def test_feed_groups_days_and_folds_consequences() -> None:
    console = _console()
    feed = {
        "changesets": [
            {
                "scope_key": "project:sase",
                "commit": "d" * 40,
                "committer_time": 1790486400,
                "provenance": {
                    "subject": "feat(tabs): something",
                    "bead": "sase-1bu.7",
                    "agent": "athena.sase-1bu.7",
                },
                "boilerplate": False,
                "regen_only": False,
                "authored": [
                    {
                        "subject_id": "note:project:sase/glossary/artifact",
                        "ordinal": 3,
                        "class": "authored",
                        "summary": {
                            "section_paths": ["Definition"],
                            "words_added": 20,
                            "words_removed": 3,
                        },
                        "path": "sase/memory/glossary/artifact.md",
                    }
                ],
                "consequences": [
                    {
                        "subject_id": "instructions:project:sase/.",
                        "ordinal": 12,
                        "class": "rendered",
                        "summary": {},
                        "path": "AGENTS.md",
                    }
                ],
            }
        ],
        "hidden_changeset_count": 5,
    }

    render_text.render_feed(console, feed, "project:sase", now_epoch=1790700000)

    text = console.export_text()
    assert "Memory changes · project:sase" in text
    assert "feat(tabs): something" in text
    assert "glossary/artifact" in text
    assert "⟳" in text and "AGENTS.md" in text
    assert "5 regenerated-only changesets hidden" in text
