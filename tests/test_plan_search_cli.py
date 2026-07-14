"""CLI coverage for ``sase plan search`` (Phase 4 slice).

Covers flag parsing (including repeatable accumulation), parse-time and
handler-time rejection of invalid limit/date args (exit 2), dispatch routing,
the JSON envelope shape, and the no-match success path. The JSON tests drive
the real Rust-backed facade over a temp repo ``sdd/`` tree plus a temp local
archive, exercising the slice end-to-end.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from sase.main import plan_command_handler
from sase.main.parser import create_parser
from sase.main.plan_search_handler import handle_plan_search_command


def _write_plan(
    path: Path,
    *,
    title: str,
    status: str,
    create_time: str,
    body: str,
    tier: str = "tale",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntier: {tier}\ncreate_time: {create_time}\nstatus: {status}\n---\n# {title}\n\n{body}\n"
    )


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a temp repo ``sdd/`` tree + local archive and point the CLI at it.

    The handler resolves the repo root from the current working directory and
    the local archive from ``SASE_HOME``; chdir + ``SASE_HOME`` wire both to the
    temp corpus without threading overrides through the CLI surface.
    """
    repo = tmp_path / "repo"
    sase_home = tmp_path / ".sase"
    repo.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-q"],
        cwd=repo,
        check=True,
    )
    bare = tmp_path / "repo.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=repo,
        check=True,
    )

    _write_plan(
        repo / "sdd" / "plans" / "202606" / "auth_token_refresh.md",
        title="Refresh auth tokens on 401",
        status="wip",
        create_time="2026-06-18 21:29:20",
        body="Retry the request once after refreshing the auth token.",
    )
    _write_plan(
        repo / "sdd" / "plans" / "202605" / "unified_auth.md",
        title="Unified auth across providers",
        status="done",
        create_time="2026-05-10 09:00:00",
        body="Consolidate the providers behind one interface.",
        tier="epic",
    )
    _write_plan(
        sase_home / "plans" / "202604" / "auth_login_fix.md",
        title="Fix login auth race",
        status="done",
        create_time="2026-04-02 08:30:00",
        body="Guard the session write behind a lock.",
    )

    monkeypatch.chdir(repo)
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    return repo


def _run(argv: list[str]) -> argparse.Namespace:
    return create_parser().parse_args(argv)


# --- flag parsing --------------------------------------------------------


def test_search_parser_sets_query_filters_and_output_options() -> None:
    args = _run(
        [
            "plan",
            "search",
            "Needle",
            "--color",
            "never",
            "--format",
            "json",
            "--kind",
            "epic",
            "--kind",
            "tale",
            "--limit",
            "5",
            "--since",
            "2026-01-01",
            "--source",
            "repo",
            "--sort",
            "recent",
            "--status",
            "wip",
            "--status",
            "done",
            "--until",
            "14d",
        ]
    )

    assert args.command == "plan"
    assert args.plan_subcommand == "search"
    assert args.query == "Needle"
    assert args.color == "never"
    assert args.format == "json"
    assert args.kind == ["epic", "tale"]
    assert args.limit == 5
    assert args.since == "2026-01-01"
    assert args.source == "repo"
    assert args.sort == "recent"
    assert args.status == ["wip", "done"]
    assert args.until == "14d"


def test_search_parser_defaults() -> None:
    args = _run(["plan", "search"])

    assert args.plan_subcommand == "search"
    assert args.query is None
    assert args.color == "auto"
    assert args.format == "compact"
    assert args.kind is None
    assert args.limit == 20
    assert args.since is None
    assert args.source == "all"
    assert args.sort is None
    assert args.status is None
    assert args.until is None


def test_search_parser_accepts_prompt_kind() -> None:
    args = _run(["plan", "search", "--kind", "prompt"])

    assert args.kind == ["prompt"]


def test_search_parser_rejects_negative_limit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        _run(["plan", "search", "needle", "--limit", "-1"])

    assert excinfo.value.code == 2
    assert "must be a non-negative integer" in capsys.readouterr().err


def test_search_parser_rejects_invalid_date(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        _run(["plan", "search", "needle", "--since", "yesterday"])

    assert excinfo.value.code == 2
    assert "invalid date" in capsys.readouterr().err


@pytest.mark.parametrize("date", ["2026-06-18", "2026-06", "202606", "14d", "2w", "3m"])
def test_search_parser_accepts_date_forms(date: str) -> None:
    args = _run(["plan", "search", "needle", "--since", date])
    assert args.since == date


# --- handler-level validation -------------------------------------------


def _search_namespace(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "query": None,
        "color": "auto",
        "format": "json",
        "kind": None,
        "limit": 20,
        "since": None,
        "source": "all",
        "sort": None,
        "status": None,
        "until": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_handler_rejects_negative_limit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_plan_search_command(_search_namespace(limit=-3))

    assert excinfo.value.code == 2
    assert "must be a non-negative integer" in capsys.readouterr().err


def test_handler_rejects_invalid_date(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_plan_search_command(_search_namespace(until="someday"))

    assert excinfo.value.code == 2
    assert "--until" in capsys.readouterr().err


def test_handler_compact_renders_grouped_listing(
    corpus: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handle_plan_search_command(
        _run(["plan", "search", "auth", "--format", "compact", "--color", "never"])
    )

    out = capsys.readouterr().out
    assert "REPO" in out and "LOCAL" in out
    # REPO section is surfaced above LOCAL.
    assert out.index("REPO") < out.index("LOCAL")
    assert "auth_token_refresh" in out
    assert "3 plans · 2 repo · 1 local · sorted by relevance" in out


def test_handler_markdown_renders_grouped_tables(
    corpus: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handle_plan_search_command(_run(["plan", "search", "auth", "--format", "markdown"]))

    out = capsys.readouterr().out
    assert out.startswith("# Plan Search Results")
    assert "**Query:** `auth`" in out
    assert "## REPO — sdd/" in out
    assert "## LOCAL — ~/.sase/plans/" in out
    assert "| Status | Kind | Plan | Title | Created |" in out


def test_handler_full_renders_panels(
    corpus: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handle_plan_search_command(
        _run(["plan", "search", "auth", "--format", "full", "--color", "never"])
    )

    out = capsys.readouterr().out
    # One bordered panel per match, with the title and metadata table.
    assert "Refresh auth tokens on 401" in out
    assert "Matched" in out
    assert "╭" in out and "╰" in out


def test_handler_browse_compact_sorts_by_recency(
    corpus: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handle_plan_search_command(
        _run(["plan", "search", "--format", "compact", "--color", "never"])
    )

    out = capsys.readouterr().out
    assert "sorted by recent" in out


# --- dispatch routing ----------------------------------------------------


def test_plan_command_dispatches_search() -> None:
    args = argparse.Namespace(plan_subcommand="search")

    with (
        patch.object(
            plan_command_handler,
            "handle_plan_search_command",
        ) as search_mock,
        pytest.raises(SystemExit) as excinfo,
    ):
        plan_command_handler.handle_plan_command(args)

    assert excinfo.value.code == 0
    search_mock.assert_called_once_with(args)


# --- end-to-end JSON rendering ------------------------------------------


def test_search_json_envelope_shape(
    corpus: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handle_plan_search_command(_run(["plan", "search", "auth", "--format", "json"]))

    payload = json.loads(capsys.readouterr().out)
    assert payload["query"] == "auth"
    assert payload["count"] == 3
    names = [result["plan"]["name"] for result in payload["results"]]
    # Repo plans outrank the matching local plan (repo boost).
    assert names == ["auth_token_refresh", "unified_auth", "auth_login_fix"]
    first = payload["results"][0]
    assert first["plan"]["source"] == "repo"
    assert first["plan"]["kind"] == "tale"
    assert first["matched_fields"] == ["title", "name", "path", "body"]
    assert isinstance(first["score"], float)


def test_search_json_browse_without_query(
    corpus: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handle_plan_search_command(_run(["plan", "search", "--format", "json"]))

    payload = json.loads(capsys.readouterr().out)
    assert payload["query"] == ""
    assert payload["count"] == 3
    # Browse mode sorts by recency and reports no matched fields.
    assert [result["plan"]["name"] for result in payload["results"]] == [
        "auth_token_refresh",
        "unified_auth",
        "auth_login_fix",
    ]
    assert all(result["matched_fields"] == [] for result in payload["results"])


def test_search_json_kind_filter(
    corpus: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handle_plan_search_command(
        _run(
            ["plan", "search", "--format", "json", "--source", "repo", "--kind", "epic"]
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert [result["plan"]["name"] for result in payload["results"]] == ["unified_auth"]


def test_search_json_prompt_kind(
    corpus: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompt = corpus / "sdd" / "plans" / "202606" / "prompts" / "auth_request.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text(
        "---\n"
        "create_time: 2026-06-19 10:00:00\n"
        "plan: plans/202606/auth_token_refresh.md\n"
        "---\n"
        "# Auth request\n\n"
        "Refresh authentication behavior.\n",
        encoding="utf-8",
    )

    handle_plan_search_command(
        _run(
            [
                "plan",
                "search",
                "--format",
                "json",
                "--source",
                "repo",
                "--kind",
                "prompt",
            ]
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert [result["plan"]["name"] for result in payload["results"]] == ["auth_request"]
    assert payload["results"][0]["plan"]["kind"] == "prompt"


def test_search_json_no_matches_is_success(
    corpus: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handle_plan_search_command(
        _run(["plan", "search", "nonexistent-needle", "--format", "json"])
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"query": "nonexistent-needle", "count": 0, "results": []}
