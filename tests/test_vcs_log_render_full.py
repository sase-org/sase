"""Tests for full-detail VCS log rendering."""

from __future__ import annotations

from datetime import datetime

import pytest

import sase.vcs_log._render_console as console_mod
from sase.vcs_log.models import LogRepo, VcsLogResult

from ._vcs_log_render_helpers import (
    _entry,
    _patch_clock,
    _render,
    _styles_covering,
    _tagged_result,
)


def test_full_format_shows_body_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = VcsLogResult(
        repos=(LogRepo("sase", "/p/sase", "primary"),),
        commits=(
            _entry(
                "sase",
                "a1b2c3d4",
                300,
                "feat: full message",
                body="body one\nbody two",
            ),
        ),
        warnings=(),
    )
    _patch_clock(
        monkeypatch,
        local_now=lambda: datetime(2026, 7, 8, 15, 0),
        to_local=lambda ts: datetime(2026, 7, 8, 14, 22),
        relative_age=lambda dt: "38m ago",
    )

    text = _render(result, "full")

    assert "▌ sase  feat: full message" in text
    assert "body one" in text
    assert "body two" in text
    assert "a1b2c3d · bryan <b@x> · 14:22 · 38m ago · synced" in text


def test_full_format_marks_merge_and_lists_all_parents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = VcsLogResult(
        repos=(LogRepo("sase", "/p/sase", "primary"),),
        commits=(
            _entry(
                "sase",
                "merge000",
                300,
                "Merge pull request #123 from org/feature",
                parent_ids=("parent0000", "parent1111", "parent2222"),
            ),
        ),
        warnings=(),
    )
    _patch_clock(
        monkeypatch,
        local_now=lambda: datetime(2026, 7, 8, 15, 0),
        to_local=lambda ts: datetime(2026, 7, 8, 14, 22),
        relative_age=lambda dt: "38m ago",
    )

    text = _render(result, "full")

    assert "◆ ✎ manual  ▌ sase  Merge pull request #123 from org/feature" in text
    assert "parents  parent0  parent1  parent2" in text


def test_full_tags_line_and_footer_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_clock(
        monkeypatch,
        local_now=lambda: datetime(2026, 7, 8, 15, 0),
        to_local=lambda ts: datetime(2026, 7, 8, 14, 22),
        relative_age=lambda dt: "38m ago",
    )

    text = _render(_tagged_result(), "full")

    assert "↻ auto  ▌ sase  tagged subject" in text
    assert "body text" in text
    assert "     ◆ type  sdd" in text
    assert "       plan  sdd/foo.md" in text
    assert "tags:" not in text
    assert "SASE_TYPE=sdd" not in text
    assert "SASE_PLAN=sdd/foo.md" not in text


def test_full_tag_spans_use_semantic_chip_colors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_clock(monkeypatch, relative_age=lambda dt: "38m ago")
    entry = _entry(
        "sase",
        "a1b2c3d4",
        300,
        "tagged subject",
        body=(
            "body text\n\n"
            "SASE_PLAN=sdd/plans/foo.md\n"
            "SASE_BUG=412\n"
            "SASE_AGENT=worker-1\n"
            "SASE_TYPE=sdd"
        ),
    )

    lines = console_mod._full_commit_lines(
        entry,
        {"sase": "#87D7FF"},
        datetime(2026, 7, 8, 14, 22),
        show_tags=True,
    )

    tag_lines = [
        line
        for line in lines
        if line.plain.startswith(("     ◆", "     @", "       plan", "     #"))
    ]
    assert [line.plain for line in tag_lines] == [
        "     ◆ type   sdd",
        "     @ agent  worker-1",
        "       plan   sdd/plans/foo.md",
        "     # bug    412",
    ]
    assert _styles_covering(tag_lines[0], "◆") == ["#87D7FF"]
    assert _styles_covering(tag_lines[0], "sdd") == ["#87D7FF"]
    assert _styles_covering(tag_lines[1], "@") == ["#FFD700"]
    assert _styles_covering(tag_lines[1], "worker-1") == ["#FFD700"]
    assert _styles_covering(tag_lines[2], "foo.md") == ["#5FAFFF"]
    assert _styles_covering(tag_lines[3], "#") == ["#FF8787"]
    assert _styles_covering(tag_lines[3], "412") == ["#FF8787"]
