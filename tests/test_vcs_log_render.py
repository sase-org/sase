"""Golden rendering tests for ``sase vcs log`` (color forced off)."""

from __future__ import annotations

import io
import json
from datetime import datetime

import pytest
from rich.text import Text

import sase.vcs_log.render as render_mod
from sase.core.vcs_log_wire import (
    AggregatedCommitWire,
    CommitPresence,
    VcsCommitWire,
)
from sase.vcs_log.models import CommitFilters, LogRepo, RepoRemoteState, VcsLogResult
from sase.vcs_log.render import build_timeline_commit, render


def _entry(
    repo: str,
    full: str,
    ts: int,
    subject: str,
    author: str = "bryan",
    body: str = "",
    presence: CommitPresence = "synced",
) -> AggregatedCommitWire:
    return AggregatedCommitWire(
        repo=repo,
        commit=VcsCommitWire(
            full_id=full,
            short_id=full[:7],
            author_name=author,
            author_email="b@x",
            timestamp=ts,
            subject=subject,
            body=body,
            presence=presence,
        ),
    )


def _result() -> VcsLogResult:
    return VcsLogResult(
        repos=(
            LogRepo("sase", "/p/sase", "primary"),
            LogRepo("sase-core", "/p/core", "linked"),
        ),
        commits=(
            _entry(
                "sase",
                "a1b2c3d4",
                300,
                "fix(sdd): link store",
                presence="local_only",
            ),
            _entry(
                "sase-core",
                "9f8e7d6c",
                200,
                "feat(core): parser",
                "amy",
                presence="remote_only",
            ),
            _entry("sase", "4c5d6e7f", 100, "docs: notes", presence="synced"),
        ),
        warnings=("sase-telegram: no such checkout",),
        remote_states=(
            RepoRemoteState("sase", "origin/main", 1, 0, True),
            RepoRemoteState("sase-core", "origin/main", 0, 1, True),
        ),
    )


def _tagged_result() -> VcsLogResult:
    return VcsLogResult(
        repos=(LogRepo("sase", "/p/sase", "primary"),),
        commits=(
            _entry(
                "sase",
                "a1b2c3d4",
                300,
                "tagged subject",
                body="body text\n\nSASE_TYPE=sdd\nSASE_PLAN=sdd/foo.md",
            ),
            _entry("sase", "b2c3d4e5", 200, "plain subject"),
        ),
        warnings=(),
    )


def _linked_tagged_result() -> VcsLogResult:
    return VcsLogResult(
        repos=(LogRepo("sase", "/p/sase", "primary"),),
        commits=(
            _entry(
                "sase",
                "a1b2c3d4",
                300,
                "linked plan",
                body=(
                    "body text\n\nSASE_PLAN=[202607/foo.md][1]\n\n"
                    "[1]: https://github.com/acme/plans/blob/main/202607/foo.md"
                ),
            ),
        ),
        warnings=(),
    )


def _render(
    result: VcsLogResult,
    fmt: str,
    color: str = "never",
    *,
    limit: int = 40,
    filters: CommitFilters | None = None,
    reverse: bool = False,
    show_tags: bool = True,
    all_projects: bool = False,
) -> str:
    out = io.StringIO()
    render(
        result,
        fmt=fmt,
        color=color,
        out=out,
        limit=limit,
        filters=filters,
        reverse=reverse,
        show_tags=show_tags,
        all_projects=all_projects,
    )
    return out.getvalue()


def test_oneline_golden() -> None:
    assert _render(_result(), "oneline") == (
        "↑ a1b2c3d sase      fix(sdd): link store\n"
        "↓ 9f8e7d6 sase-core feat(core): parser\n"
        "● 4c5d6e7 sase      docs: notes\n"
    )


def test_oneline_empty_is_blank() -> None:
    empty = VcsLogResult(repos=(), commits=(), warnings=())
    assert _render(empty, "oneline") == ""


def test_oneline_tags_suffix() -> None:
    assert _render(_tagged_result(), "oneline") == (
        "● a1b2c3d sase tagged subject [TYPE=sdd PLAN=sdd/foo.md]\n"
        "● b2c3d4e sase plain subject\n"
    )


def test_oneline_no_tags_suppresses_suffix() -> None:
    assert _render(_tagged_result(), "oneline", show_tags=False) == (
        "● a1b2c3d sase tagged subject\n● b2c3d4e sase plain subject\n"
    )


def test_json_shape_and_ordering() -> None:
    payload = json.loads(_render(_result(), "json"))
    assert list(payload.keys()) == ["commits", "query", "repos", "warnings"]
    assert [c["short_id"] for c in payload["commits"]] == [
        "a1b2c3d",
        "9f8e7d6",
        "4c5d6e7",
    ]
    # Each commit carries repo label + ids + author + email + timestamp + subject.
    first = payload["commits"][0]
    assert first == {
        "author_email": "b@x",
        "author_name": "bryan",
        "full_id": "a1b2c3d4",
        "presence": "local_only",
        "repo": "sase",
        "sase_tags": {},
        "short_id": "a1b2c3d",
        "subject": "fix(sdd): link store",
        "timestamp": 300,
    }
    assert payload["query"] == {
        "all": False,
        "authors": [],
        "limit": 40,
        "reverse": False,
        "since": None,
        "until": None,
    }
    assert payload["repos"][0] == {
        "kind": "primary",
        "name": "sase",
        "path": "/p/sase",
        "remote_ref": "origin/main",
        "ahead": 1,
        "behind": 0,
        "fetched": True,
        "fetched_at": None,
    }
    assert payload["warnings"] == ["sase-telegram: no such checkout"]


def test_json_tags_shape() -> None:
    payload = json.loads(_render(_tagged_result(), "json"))

    assert payload["commits"][0]["sase_tags"] == {
        "PLAN": "sdd/foo.md",
        "TYPE": "sdd",
    }
    assert payload["commits"][1]["sase_tags"] == {}


def test_linked_tag_rendering_uses_label_and_omits_reference_definition() -> None:
    oneline = _render(_linked_tagged_result(), "oneline")
    payload = json.loads(_render(_linked_tagged_result(), "json"))
    full = _render(_linked_tagged_result(), "full")

    assert "PLAN=202607/foo.md" in oneline
    assert payload["commits"][0]["sase_tags"] == {"PLAN": "202607/foo.md"}
    assert "plan  202607/foo.md" in full
    assert "[1]: https://github.com" not in full


def test_json_no_tags_omits_sase_tags() -> None:
    payload = json.loads(_render(_tagged_result(), "json", show_tags=False))

    assert "sase_tags" not in payload["commits"][0]
    assert "sase_tags" not in payload["commits"][1]


def test_json_empty_result() -> None:
    empty = VcsLogResult(repos=(), commits=(), warnings=())
    payload = json.loads(_render(empty, "json"))
    assert payload == {
        "commits": [],
        "query": {
            "all": False,
            "authors": [],
            "limit": 40,
            "reverse": False,
            "since": None,
            "until": None,
        },
        "repos": [],
        "warnings": [],
    }


def test_json_reverse_and_query_filters() -> None:
    payload = json.loads(
        _render(
            _result(),
            "json",
            limit=0,
            filters=CommitFilters(since=100, until=300, authors=("bryan",)),
            reverse=True,
        )
    )

    assert [c["short_id"] for c in payload["commits"]] == [
        "4c5d6e7",
        "9f8e7d6",
        "a1b2c3d",
    ]
    assert payload["query"] == {
        "all": False,
        "authors": ["bryan"],
        "limit": 0,
        "reverse": True,
        "since": 100,
        "until": 300,
    }


@pytest.mark.parametrize("fmt", ["pretty", "full", "oneline", "json"])
def test_all_formats_trim_author_time_before_filling_final_limit(fmt: str) -> None:
    result = VcsLogResult(
        repos=(LogRepo("sase", "/p/sase", "primary"),),
        commits=(
            _entry("sase", "margin400", 400, "upper margin"),
            _entry("sase", "bound300", 300, "upper inclusive"),
            _entry("sase", "inside25", 250, "inside window"),
            _entry("sase", "bound200", 200, "lower inclusive"),
            _entry("sase", "outside1", 100, "below window"),
        ),
        warnings=(),
    )

    text = _render(
        result,
        fmt,
        limit=2,
        filters=CommitFilters(since=200, until=300),
    )

    assert "upper inclusive" in text
    assert "inside window" in text
    assert "upper margin" not in text
    assert "lower inclusive" not in text
    assert "below window" not in text


def test_json_exact_author_time_bounds_are_inclusive() -> None:
    result = VcsLogResult(
        repos=(LogRepo("sase", "/p/sase", "primary"),),
        commits=(
            _entry("sase", "above301", 301, "above"),
            _entry("sase", "upper300", 300, "upper"),
            _entry("sase", "lower200", 200, "lower"),
            _entry("sase", "below199", 199, "below"),
        ),
        warnings=(),
        resolved_filters=CommitFilters(since=200, until=300),
    )

    payload = json.loads(_render(result, "json", limit=0))

    assert [commit["subject"] for commit in payload["commits"]] == [
        "upper",
        "lower",
    ]
    assert payload["query"]["since"] == 200
    assert payload["query"]["until"] == 300


def test_json_marks_all_project_scope_with_unique_local_only_labels() -> None:
    result = VcsLogResult(
        repos=(
            LogRepo("alpha/shared", "/p/alpha-shared", "linked"),
            LogRepo("beta/shared", "/p/beta-shared", "linked"),
        ),
        commits=(
            _entry(
                "alpha/shared",
                "abc12345",
                200,
                "local provider commit",
                presence="unknown",
            ),
        ),
        warnings=(),
        remote_states=(
            RepoRemoteState("alpha/shared", None, 0, 0, False),
            RepoRemoteState("beta/shared", None, 0, 0, False),
        ),
    )

    payload = json.loads(_render(result, "json", all_projects=True))

    assert payload["query"]["all"] is True
    assert [repo["name"] for repo in payload["repos"]] == [
        "alpha/shared",
        "beta/shared",
    ]
    assert payload["commits"][0]["presence"] == "unknown"


def test_pretty_day_groups_labels_and_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 8, 15, 0)
    local = {
        300: datetime(2026, 7, 8, 14, 22),  # Today
        200: datetime(2026, 7, 8, 13, 5),  # Today
        100: datetime(2026, 7, 7, 18, 40),  # Yesterday
    }
    monkeypatch.setattr(render_mod, "_local_now", lambda: now)
    monkeypatch.setattr(render_mod, "_to_local", lambda ts: local[ts])

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


def test_pretty_reverse_uses_ascending_day_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 8, 15, 0)
    local = {
        300: datetime(2026, 7, 8, 14, 22),
        200: datetime(2026, 7, 8, 13, 5),
        100: datetime(2026, 7, 7, 18, 40),
    }
    monkeypatch.setattr(render_mod, "_local_now", lambda: now)
    monkeypatch.setattr(render_mod, "_to_local", lambda ts: local[ts])

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
    monkeypatch.setattr(render_mod, "_local_now", lambda: now)
    monkeypatch.setattr(render_mod, "_to_local", lambda ts: local[ts])

    text = _render(_tagged_result(), "pretty")

    assert "tagged subject  · ◆ sdd · plan sdd/foo.md  · bryan" in text
    assert "plain subject  · bryan" in text


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

    line = render_mod._commit_line(
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
    monkeypatch.setattr(
        render_mod, "_to_local", lambda _ts: datetime(2026, 7, 8, 14, 22)
    )

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
    console = render_mod.make_console("never", file=out, width=36)
    console.print(row, no_wrap=row.no_wrap, overflow=row.overflow)
    rendered_lines = out.getvalue().splitlines()
    assert len(rendered_lines) == 1
    assert rendered_lines[0].endswith("…")


def test_pretty_filter_summary_and_empty_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = {
        100: datetime(2026, 7, 7, 0, 0),
        200: datetime(2026, 7, 8, 14, 30),
        300: datetime(2026, 7, 8, 15, 30),
    }
    monkeypatch.setattr(render_mod, "_to_local", lambda ts: local[ts])
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
    monkeypatch.setattr(render_mod, "_local_now", lambda: datetime(2026, 7, 8, 15, 0))
    monkeypatch.setattr(
        render_mod, "_to_local", lambda ts: datetime(2026, 7, 8, 14, 22)
    )
    monkeypatch.setattr(render_mod, "_relative_age", lambda dt: "38m ago")

    text = _render(result, "full")

    assert "▌ sase  feat: full message" in text
    assert "body one" in text
    assert "body two" in text
    assert "a1b2c3d · bryan <b@x> · 14:22 · 38m ago · synced" in text


def test_full_tags_line_and_footer_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(render_mod, "_local_now", lambda: datetime(2026, 7, 8, 15, 0))
    monkeypatch.setattr(
        render_mod, "_to_local", lambda ts: datetime(2026, 7, 8, 14, 22)
    )
    monkeypatch.setattr(render_mod, "_relative_age", lambda dt: "38m ago")

    text = _render(_tagged_result(), "full")

    assert "body text" in text
    assert "     ◆ type  sdd" in text
    assert "       plan  sdd/foo.md" in text
    assert "tags:" not in text
    assert "SASE_TYPE=sdd" not in text
    assert "SASE_PLAN=sdd/foo.md" not in text


def test_full_tag_spans_use_semantic_chip_colors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(render_mod, "_relative_age", lambda dt: "38m ago")
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

    lines = render_mod._full_commit_lines(
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


def test_pretty_empty_shows_no_commits() -> None:
    empty = VcsLogResult(repos=(), commits=(), warnings=())
    text = _render(empty, "pretty")
    assert "No commits found" in text


def test_pretty_empty_still_shows_warnings() -> None:
    empty = VcsLogResult(repos=(), commits=(), warnings=("boom",))
    text = _render(empty, "pretty")
    assert "No commits found" in text
    assert "⚠ boom" in text


def test_pretty_cached_remote_summary_shows_fetch_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(render_mod, "_local_now", lambda: datetime(2026, 7, 8, 15, 0))
    monkeypatch.setattr(
        render_mod, "_to_local", lambda ts: datetime(2026, 7, 8, 14, 22)
    )
    monkeypatch.setattr(render_mod, "_now_epoch", lambda: 1030.0)
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
    monkeypatch.setattr(render_mod, "_local_now", lambda: datetime(2026, 7, 8, 15, 0))
    monkeypatch.setattr(
        render_mod, "_to_local", lambda ts: datetime(2026, 7, 8, 14, 22)
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


def _styles_covering(text: Text, fragment: str) -> list[str]:
    start = text.plain.index(fragment)
    end = start + len(fragment)
    return [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= end
    ]
