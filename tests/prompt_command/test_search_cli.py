"""End-to-end CLI coverage for ``sase prompt search`` (compact renderer)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.prompt.cli_search import handle_prompt_search

from ._helpers import _entry, _prompt_id, _seed


def _ns(query: str, **overrides: object) -> argparse.Namespace:
    """Build a search Namespace with the parser defaults, overridable per test."""
    base: dict[str, object] = {
        "query": query,
        "after": None,
        "before": None,
        "color": "never",
        "format": "compact",
        "limit": 20,
        "source": "all",
        "tag": None,
        "cancelled": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _write_sdd(base: Path, month: str, name: str, content: str) -> None:
    path = base / "sdd" / "prompts" / month / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run the search handler from an isolated repo root (for SDD discovery)."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["", "   "])
def test_empty_query_is_usage_error(
    query: str,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        handle_prompt_search(_ns(query))
    assert exc.value.code == 2
    assert "cannot be empty" in capsys.readouterr().err


def test_unparseable_date_is_usage_error(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        handle_prompt_search(_ns("auth", after="not-a-date"))
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "not-a-date" in err


def test_no_match_is_not_an_error(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("totally unrelated prompt", "260603_000000"))
    handle_prompt_search(_ns("zzzznotpresent"))
    out = capsys.readouterr().out
    assert 'No prompts match "zzzznotpresent".' in out


# ---------------------------------------------------------------------------
# Compact rendering — both sources, grouping, footer
# ---------------------------------------------------------------------------


def test_compact_groups_both_sources_with_footer(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_sdd(repo, "202604", "auth_snapshot", "Rotate auth tokens nightly.\n")
    _seed(_entry("retry the auth flow on failure", "260601_000000"))

    handle_prompt_search(_ns("auth"))

    out = capsys.readouterr().out
    # SDD group renders before the local group.
    assert "── SDD prompts (1) ──" in out
    assert "── Local history (1) ──" in out
    assert out.index("SDD prompts") < out.index("Local history")
    # The locator, snapshot path, and a body snippet all appear.
    assert "auth_snapshot" in out
    assert "sdd/prompts/202604/auth_snapshot.md" in out
    assert "Rotate auth tokens nightly." in out
    # Footer reports per-source totals.
    assert "2 matches (1 SDD · 1 local)" in out


def test_compact_singular_match_footer(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("deploy the auth service", "260601_000000"))
    handle_prompt_search(_ns("deploy", source="local"))
    out = capsys.readouterr().out
    assert "1 match (0 SDD · 1 local)" in out


def test_local_status_badges(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("auth launched prompt", "260601_000000"),
        _entry("auth cancelled prompt", "260602_000000", cancelled=True),
    )
    handle_prompt_search(_ns("auth", source="local"))
    out = capsys.readouterr().out
    assert "launched" in out
    assert "cancelled" in out


# ---------------------------------------------------------------------------
# "Why matched" — non-body fields name themselves
# ---------------------------------------------------------------------------


def test_plan_only_match_shows_why(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_sdd(
        repo,
        "202604",
        "snapshot",
        "---\nplan: sdd/plans/202604/rotate_tokens.md\n---\nDo the work.\n",
    )
    # 'rotate_tokens' appears only in the plan link, not the body/title/path.
    handle_prompt_search(_ns("rotate_tokens", source="sdd"))
    out = capsys.readouterr().out
    assert 'plan: "' in out
    assert "rotate_tokens" in out


def test_tag_only_match_shows_why(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_sdd(
        repo,
        "202604",
        "snapshot",
        "---\nprompt_tags: [security]\n---\nDo the work.\n",
    )
    handle_prompt_search(_ns("security", source="sdd"))
    out = capsys.readouterr().out
    assert 'tag: "security"' in out


# ---------------------------------------------------------------------------
# Color resolution
# ---------------------------------------------------------------------------


def test_color_never_emits_no_ansi(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("auth token rotation", "260601_000000"))
    handle_prompt_search(_ns("auth", source="local", color="never"))
    out = capsys.readouterr().out
    assert "\x1b[" not in out


def test_color_always_highlights_match(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("auth token rotation", "260601_000000"))
    handle_prompt_search(_ns("auth", source="local", color="always"))
    out = capsys.readouterr().out
    assert "\x1b[" in out  # ANSI is present
    # The matched term is wrapped in the bold-yellow highlight style.
    assert "33m" in out  # yellow foreground


# ---------------------------------------------------------------------------
# Filters end-to-end: source, date, tag, cancelled, limit
# ---------------------------------------------------------------------------


def test_source_filter_scopes_results(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_sdd(repo, "202604", "auth_snapshot", "auth in the snapshot\n")
    _seed(_entry("auth in local history", "260601_000000"))

    handle_prompt_search(_ns("auth", source="sdd"))
    out = capsys.readouterr().out
    assert "auth_snapshot" in out
    assert "Local history" not in out

    handle_prompt_search(_ns("auth", source="local"))
    out = capsys.readouterr().out
    assert "SDD prompts" not in out
    assert "Local history (1)" in out


def test_sdd_source_finds_local_sase_sdd_snapshot(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A project-local ``.sase/sdd/prompts`` snapshot must be visible to an
    # ``--source sdd`` search run from the project root.
    local_path = repo / ".sase" / "sdd" / "prompts" / "202605" / "local_snapshot.md"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text("Rotate auth tokens locally.\n", encoding="utf-8")

    handle_prompt_search(_ns("auth", source="sdd"))

    out = capsys.readouterr().out
    assert "local_snapshot" in out
    assert ".sase/sdd/prompts/202605/local_snapshot.md" in out
    assert "1 match (1 SDD · 0 local)" in out


def test_after_date_filter(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("auth old prompt", "260101_000000"),
        _entry("auth new prompt", "260601_000000"),
    )
    handle_prompt_search(_ns("auth", source="local", after="2026-03-01"))
    out = capsys.readouterr().out
    assert "1 match (0 SDD · 1 local)" in out
    assert _prompt_id("auth new prompt") in out
    assert _prompt_id("auth old prompt") not in out


def test_tag_filter(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_sdd(
        repo, "202604", "reviewed", "---\nprompt_tags: [review]\n---\nauth work\n"
    )
    _write_sdd(repo, "202604", "plain", "auth work without tags\n")
    handle_prompt_search(_ns("auth", source="sdd", tag=["review"]))
    out = capsys.readouterr().out
    assert "reviewed" in out
    assert "plain" not in out
    assert "1 match (1 SDD · 0 local)" in out


def test_cancelled_filter_restricts_local(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("auth launched", "260601_000000"),
        _entry("auth abandoned", "260602_000000", cancelled=True),
    )
    handle_prompt_search(_ns("auth", source="local", cancelled=True))
    out = capsys.readouterr().out
    assert _prompt_id("auth abandoned") in out
    assert _prompt_id("auth launched") not in out


def test_limit_truncates_and_reports(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("auth one", "260601_000000"),
        _entry("auth two", "260602_000000"),
        _entry("auth three", "260603_000000"),
    )
    handle_prompt_search(_ns("auth", source="local", limit=2))
    out = capsys.readouterr().out
    # Footer reports the full total but flags how many are shown.
    assert "3 matches (0 SDD · 3 local)" in out
    assert "showing 2" in out


def test_limit_zero_is_unlimited(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("auth one", "260601_000000"),
        _entry("auth two", "260602_000000"),
    )
    handle_prompt_search(_ns("auth", source="local", limit=0))
    out = capsys.readouterr().out
    assert "2 matches (0 SDD · 2 local)" in out
    assert "showing" not in out  # not truncated
