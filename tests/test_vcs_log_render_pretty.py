"""Tests for the pretty and timeline VCS log renderers."""

from __future__ import annotations

import io
from datetime import datetime

import pytest

import sase.vcs_log._render_console as console_mod
from sase.core.vcs_log_facade import _MergeSummary
from sase.vcs_log._style import make_console
from sase.vcs_log.models import CommitFilters, LogRepo, RepoRemoteState, VcsLogResult
from sase.vcs_log.render import build_timeline_commit

from ._vcs_log_render_helpers import (
    _entry,
    _patch_clock,
    _render,
    _result,
    _styles_covering,
    _tagged_result,
)


def test_pretty_day_groups_labels_and_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 8, 15, 0)
    local = {
        300: datetime(2026, 7, 8, 14, 22),  # Today
        200: datetime(2026, 7, 8, 13, 5),  # Today
        100: datetime(2026, 7, 7, 18, 40),  # Yesterday
    }
    _patch_clock(monkeypatch, local_now=lambda: now, to_local=lambda ts: local[ts])

    text = _render(_result(), "pretty")

    # Day headers appear once each, Today before Yesterday.
    assert "── Today " in text
    assert "── Yesterday " in text
    assert text.index("── Today ") < text.index("── Yesterday ")
    # Legend lists both repos with counts.
    assert "sase (2)" in text
    assert "↑1 ↓0" in text
    assert "sase-core (1)" in text
    assert "↑0 ↓1" in text
    assert "↑ unpushed" in text
    assert "↓ GitHub-only" in text
    assert "vs origin/main · fetched" in text
    # Rows carry short SHA, repo label, subject, author, and time.
    assert "a1b2c3d" in text
    assert "14:22" in text
    assert "feat(core): parser" in text
    assert "· amy" in text
    # Ordering: newest commit before the yesterday commit.
    assert text.index("fix(sdd): link store") < text.index("docs: notes")
    # Warnings surfaced in a trailing block.
    assert "⚠ sase-telegram: no such checkout" in text


def test_pretty_merge_free_output_keeps_existing_spacing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 8, 15, 0)
    local = {
        300: datetime(2026, 7, 8, 14, 22),
        200: datetime(2026, 7, 8, 13, 5),
        100: datetime(2026, 7, 7, 18, 40),
    }
    _patch_clock(monkeypatch, local_now=lambda: now, to_local=lambda ts: local[ts])

    text = _render(_result(), "pretty")

    assert "◆ merge" not in text
    assert "a1b2c3d  sase       fix(sdd): link store" in text
    assert "9f8e7d6  sase-core  feat(core): parser" in text


def test_pretty_reverse_uses_ascending_day_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 8, 15, 0)
    local = {
        300: datetime(2026, 7, 8, 14, 22),
        200: datetime(2026, 7, 8, 13, 5),
        100: datetime(2026, 7, 7, 18, 40),
    }
    _patch_clock(monkeypatch, local_now=lambda: now, to_local=lambda ts: local[ts])

    text = _render(_result(), "pretty", reverse=True)

    assert text.index("── Yesterday ") < text.index("── Today ")
    assert text.index("docs: notes") < text.index("feat(core): parser")
    assert text.index("feat(core): parser") < text.index("fix(sdd): link store")


def test_pretty_tags_suffix_before_author(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 8, 15, 0)
    local = {
        300: datetime(2026, 7, 8, 14, 22),
        200: datetime(2026, 7, 8, 13, 5),
    }
    _patch_clock(monkeypatch, local_now=lambda: now, to_local=lambda ts: local[ts])

    text = _render(_tagged_result(), "pretty")

    assert "tagged subject  · ◆ sdd · plan sdd/foo.md  · bryan" in text
    assert "plain subject  · bryan" in text


def test_pretty_marks_merges_and_condenses_pull_request_headline(
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
                body="Add the feature title here\n\nmore body",
                parent_ids=("parent0000", "parent1111"),
            ),
            _entry("sase", "plain000", 200, "ordinary subject"),
        ),
        warnings=(),
    )
    monkeypatch.setattr(
        console_mod,
        "merge_summary",
        lambda _subject, _body: _MergeSummary(
            kind="pull_request",
            reference="123",
            source="org/feature",
            target=None,
            headline="Add the feature title here",
        ),
    )
    _patch_clock(
        monkeypatch,
        local_now=lambda: datetime(2026, 7, 8, 15, 0),
        to_local=lambda ts: datetime(2026, 7, 8, 14, 22 if ts == 300 else 13, 5),
    )

    text = _render(result, "pretty")

    assert "◆ merge" in text
    assert "merge00  sase  ◆ #123  Add the feature title here" in text
    assert "plain00  sase    ordinary subject" in text
    assert "Merge pull request #123 from org/feature" not in text


def test_pretty_keeps_raw_merge_subject_when_summary_is_not_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = VcsLogResult(
        repos=(LogRepo("sase", "/p/sase", "primary"),),
        commits=(
            _entry(
                "sase",
                "merge000",
                300,
                "Merge something custom",
                parent_ids=("parent0000", "parent1111"),
            ),
        ),
        warnings=(),
    )
    monkeypatch.setattr(console_mod, "merge_summary", lambda _subject, _body: None)
    _patch_clock(
        monkeypatch,
        local_now=lambda: datetime(2026, 7, 8, 15, 0),
        to_local=lambda ts: datetime(2026, 7, 8, 14, 22),
    )

    text = _render(result, "pretty")

    assert "merge00  sase  ◆ Merge something custom" in text


def test_pretty_keeps_raw_pull_request_subject_without_headline(
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
                parent_ids=("parent0000", "parent1111"),
            ),
        ),
        warnings=(),
    )
    monkeypatch.setattr(
        console_mod,
        "merge_summary",
        lambda _subject, _body: _MergeSummary(
            kind="pull_request",
            reference="123",
            source="org/feature",
            target=None,
            headline=None,
        ),
    )
    _patch_clock(
        monkeypatch,
        local_now=lambda: datetime(2026, 7, 8, 15, 0),
        to_local=lambda ts: datetime(2026, 7, 8, 14, 22),
    )

    text = _render(result, "pretty")

    assert "merge00  sase  ◆ Merge pull request #123 from org/feature" in text


def test_pretty_tag_spans_use_semantic_chip_colors() -> None:
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

    line = console_mod.commit_line(
        entry,
        {"sase": "#87D7FF"},
        repo_width=len("sase"),
        sha_width=7,
        dt_local=datetime(2026, 7, 8, 14, 22),
        show_tags=True,
    )

    assert "◆ sdd · @worker-1 · plan sdd/plans/foo.md · #412" in line.plain
    assert _styles_covering(line, "◆") == ["#87D7FF"]
    assert _styles_covering(line, "@") == ["#FFD700"]
    assert _styles_covering(line, "worker-1") == ["#FFD700"]
    assert _styles_covering(line, "foo.md") == ["#5FAFFF"]
    assert _styles_covering(line, "#") == ["#FF8787"]
    assert _styles_covering(line, "412") == ["#FF8787"]


def test_pretty_merge_marker_spans_use_merge_accent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _entry(
        "sase",
        "merge000",
        300,
        "Merge something custom",
        parent_ids=("parent0000", "parent1111"),
    )
    monkeypatch.setattr(console_mod, "merge_summary", lambda _subject, _body: None)

    line = console_mod.commit_line(
        entry,
        {"sase": "#87D7FF"},
        repo_width=len("sase"),
        sha_width=7,
        dt_local=datetime(2026, 7, 8, 14, 22),
        show_tags=False,
        merge_column=True,
    )

    assert "◆ Merge something custom" in line.plain
    assert _styles_covering(line, "◆") == ["#D787FF"]


def test_compact_timeline_row_is_one_line_and_ellipsizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _entry(
        "sase-platform-repository",
        "a1b2c3d4",
        300,
        "feat: keep this deliberately long timeline subject on one physical row",
        author="A deliberately long commit author name",
        body="body\n\nSASE_AGENT=worker-1\nSASE_BUG=412",
        presence="local_only",
    )
    result = VcsLogResult(
        repos=(LogRepo(entry.repo, "/p/sase", "primary"),),
        commits=(entry,),
        warnings=(),
    )
    _patch_clock(monkeypatch, to_local=lambda _ts: datetime(2026, 7, 8, 14, 22))

    row = build_timeline_commit(
        entry,
        result,
        show_tags=False,
        show_author=False,
    )

    assert "↑" in row.plain
    assert "14:22" in row.plain
    assert "a1b2c3d" in row.plain
    assert entry.repo in row.plain
    assert entry.commit.subject in row.plain
    assert "worker-1" not in row.plain
    assert "#412" not in row.plain
    assert entry.commit.author_name not in row.plain
    assert "\n" not in row.plain
    assert row.no_wrap is True
    assert row.overflow == "ellipsis"

    out = io.StringIO()
    console = make_console("never", file=out, width=36)
    console.print(row, no_wrap=row.no_wrap, overflow=row.overflow)
    rendered_lines = out.getvalue().splitlines()
    assert len(rendered_lines) == 1
    assert rendered_lines[0].endswith("…")


def test_timeline_row_marks_merge_when_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _entry(
        "sase",
        "merge000",
        300,
        "Merge pull request #123 from org/feature",
        body="Add the feature title here",
        parent_ids=("parent0000", "parent1111"),
    )
    result = VcsLogResult(
        repos=(LogRepo("sase", "/p/sase", "primary"),),
        commits=(entry,),
        warnings=(),
    )
    monkeypatch.setattr(
        console_mod,
        "merge_summary",
        lambda _subject, _body: _MergeSummary(
            kind="pull_request",
            reference="123",
            source="org/feature",
            target=None,
            headline="Add the feature title here",
        ),
    )
    _patch_clock(monkeypatch, to_local=lambda _ts: datetime(2026, 7, 8, 14, 22))

    row = build_timeline_commit(entry, result, show_tags=False, show_author=False)

    assert "◆ #123  Add the feature title here" in row.plain
    assert row.no_wrap is True
    assert row.overflow == "ellipsis"


def test_pretty_filter_summary_and_empty_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = {
        100: datetime(2026, 7, 7, 0, 0),
        200: datetime(2026, 7, 8, 14, 30),
        300: datetime(2026, 7, 8, 15, 30),
    }
    _patch_clock(monkeypatch, to_local=lambda ts: local[ts])
    filters = CommitFilters(since=100, until=200, authors=("bryan",))

    text = _render(_result(), "pretty", filters=filters)
    assert "since 2026-07-07" in text
    assert "until 2026-07-08T14:30" in text
    assert "author bryan" in text

    empty = VcsLogResult(repos=(), commits=(), warnings=())
    text = _render(empty, "pretty", filters=filters)
    assert (
        "No commits found (since 2026-07-07, until 2026-07-08T14:30, author bryan)"
    ) in text


def test_pretty_empty_shows_no_commits() -> None:
    empty = VcsLogResult(repos=(), commits=(), warnings=())
    text = _render(empty, "pretty")
    assert "No commits found" in text


def test_pretty_filter_summary_mentions_non_default_merge_modes() -> None:
    text = _render(_result(), "pretty", filters=CommitFilters(merges="show"))
    assert "with merges" in text

    empty = VcsLogResult(repos=(), commits=(), warnings=())
    text = _render(empty, "pretty", filters=CommitFilters(merges="only"))
    assert "No merge commits found (merges only)" in text


def test_pretty_empty_still_shows_warnings() -> None:
    empty = VcsLogResult(repos=(), commits=(), warnings=("boom",))
    text = _render(empty, "pretty")
    assert "No commits found" in text
    assert "⚠ boom" in text


def test_pretty_cached_remote_summary_shows_fetch_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_clock(
        monkeypatch,
        local_now=lambda: datetime(2026, 7, 8, 15, 0),
        to_local=lambda ts: datetime(2026, 7, 8, 14, 22),
        now_epoch=lambda: 1030.0,
    )
    result = VcsLogResult(
        repos=(LogRepo("sase", "/p/sase", "primary"),),
        commits=(_entry("sase", "a1b2c3d4", 300, "cached"),),
        warnings=(),
        remote_states=(RepoRemoteState("sase", "origin/main", 0, 0, False, 1000.0),),
    )

    text = _render(result, "pretty")

    assert "vs origin/main · fetched 30s ago" in text


def test_pretty_mixed_fetched_and_cached_remote_summary_is_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_clock(
        monkeypatch,
        local_now=lambda: datetime(2026, 7, 8, 15, 0),
        to_local=lambda ts: datetime(2026, 7, 8, 14, 22),
    )
    result = VcsLogResult(
        repos=(
            LogRepo("sase", "/p/sase", "primary"),
            LogRepo("sase-core", "/p/core", "linked"),
        ),
        commits=(
            _entry("sase", "a1b2c3d4", 300, "fetched"),
            _entry("sase-core", "b2c3d4e5", 200, "cached"),
        ),
        warnings=(),
        remote_states=(
            RepoRemoteState("sase", "origin/main", 0, 0, True, 1030.0),
            RepoRemoteState("sase-core", "origin/main", 0, 0, False, 1000.0),
        ),
    )

    text = _render(result, "pretty")

    assert "vs origin/main · fresh" in text
