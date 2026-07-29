"""Focused tests for the shared structured chop-report renderer."""

from __future__ import annotations

from sase.axe.chop_report_render import TONE_STYLES, render_chop_report


def test_render_chop_report_covers_every_block_kind_and_literal_text() -> None:
    report = {
        "title": "CI [WATCH]",
        "blocks": [
            {"kind": "headline", "text": "[bold]literal[/bold]", "tone": "warn"},
            {"kind": "heading", "text": "REPOSITORIES"},
            {"kind": "text", "text": "One failure", "tone": "error"},
            {
                "kind": "kv",
                "items": [{"key": "mode", "value": "dry run", "tone": "muted"}],
            },
            {
                "kind": "rows",
                "columns": ["REPOSITORY", "STATE"],
                "rows": [
                    {
                        "cells": ["sase-org/sase", "red"],
                        "tone": "error",
                        "glyph": "▲",
                    }
                ],
            },
            {
                "kind": "bullets",
                "items": [{"text": "rerun CI", "tone": "info", "glyph": "▸"}],
            },
            {"kind": "gauge", "label": "green", "value": 4, "max": 5, "tone": "ok"},
            {"kind": "divider"},
        ],
    }

    plain = render_chop_report(report, width=80).plain

    for expected in (
        "CI [WATCH]",
        "[bold]literal[/bold]",
        "REPOSITORIES",
        "One failure",
        "mode dry run",
        "sase-org/sase",
        "▸ rerun CI",
        "green",
        "4/5",
        "████",
    ):
        assert expected in plain


def test_tone_palette_is_the_closed_axe_house_style() -> None:
    assert TONE_STYLES == {
        "neutral": "#D7AF87",
        "muted": "dim #A8A8A8",
        "info": "#87D7FF",
        "ok": "#5FD75F",
        "warn": "#FFAF5F",
        "error": "#FF5F5F",
        "accent": "bold #FFD700",
    }


def test_rows_right_align_numeric_columns_and_elide_cells() -> None:
    report = {
        "blocks": [
            {
                "kind": "rows",
                "columns": ["PATH", "COUNT"],
                "rows": [
                    {
                        "cells": [
                            "very/long/path/with/many/directories/to/the/report.json",
                            "2",
                        ],
                        "tone": "ok",
                    },
                    {"cells": ["short", "10"], "tone": "neutral"},
                ],
            }
        ]
    }

    lines = render_chop_report(report, width=60).plain.splitlines()

    assert "…/" in lines[1]
    assert lines[1].endswith(" 2")
    assert lines[2].endswith("10")


def test_narrow_rows_and_kv_stack_without_truncating_values() -> None:
    long_value = "a complete value that must remain visible"
    report = {
        "blocks": [
            {
                "kind": "rows",
                "columns": ["NAME", "DETAIL"],
                "rows": [{"cells": ["alpha", long_value], "tone": "info"}],
            },
            {
                "kind": "kv",
                "items": [
                    {"key": "first", "value": long_value},
                    {"key": "second", "value": "another complete value"},
                ],
            },
        ]
    }

    plain = render_chop_report(report, width=40).plain

    assert "\n    DETAIL: " in plain
    assert plain.count(long_value) == 2
    assert "\n  second another complete value" in plain


def test_unknown_kind_and_tone_are_skipped_without_raising() -> None:
    report = {
        "blocks": [
            {"kind": "future", "text": "hidden"},
            {"kind": "text", "text": "also hidden", "tone": "ultraviolet"},
            {"kind": "text", "text": "visible", "tone": "ok"},
        ]
    }

    plain = render_chop_report(report).plain

    assert "visible" in plain
    assert "hidden" not in plain
