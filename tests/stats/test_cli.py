"""Handler tests for ``sase stats`` and ``sase stats project``."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.main.stats_handler import handle_stats_command
from sase.main.stats_handler_project import handle_stats_project
from sase.stats.project import (
    ProjectStatsUnavailableError,
    ProjectStatsUsageError,
)
from tests.main.parser_cli_helpers import parse_sase_args
from tests.stats._project_render_fixtures import one_project_view


def test_bare_stats_prints_group_help_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = parse_sase_args(["stats"])

    assert handle_stats_command(args) == 0
    out = capsys.readouterr().out
    assert "usage: sase stats" in out
    assert "project" in out
    assert "{project}" in out
    assert "overview" not in out
    assert "runner" not in out


def test_unknown_project_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sase.main.stats_handler_project.load_project_stats",
        lambda query: (_ for _ in ()).throw(
            ProjectStatsUsageError("Unknown project 'nope'; did you mean sase?")
        ),
    )

    assert (
        handle_stats_project(parse_sase_args(["stats", "project", "-p", "nope"])) == 2
    )
    assert "did you mean sase?" in capsys.readouterr().err


def test_ambiguous_project_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sase.main.stats_handler_project.load_project_stats",
        lambda query: (_ for _ in ()).throw(
            ProjectStatsUsageError("Ambiguous project 'x': alpha, beta")
        ),
    )

    assert handle_stats_project(parse_sase_args(["stats", "project", "-p", "x"])) == 2
    assert "Ambiguous project" in capsys.readouterr().err


def test_bad_range_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        handle_stats_project(parse_sase_args(["stats", "project", "-r", "nope"])) == 2
    )
    err = capsys.readouterr().err
    assert "Invalid statistics range" in err
    assert "Accepted:" in err


def test_json_plus_rich_format_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        handle_stats_project(parse_sase_args(["stats", "project", "-j", "-f", "rich"]))
        == 2
    )
    assert "cannot be combined with a non-JSON --format" in capsys.readouterr().err


def test_binding_missing_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sase.main.stats_handler_project.load_project_stats",
        lambda query: (_ for _ in ()).throw(
            ProjectStatsUnavailableError("project_stats_query binding is missing")
        ),
    )

    assert handle_stats_project(parse_sase_args(["stats", "project"])) == 1
    assert "binding is missing" in capsys.readouterr().err


def test_json_envelope_round_trip(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    view = one_project_view()
    monkeypatch.setattr(
        "sase.main.stats_handler_project.load_project_stats", lambda query: view
    )

    argv = ["stats", "project", "-p", "sase", "-j"]
    assert handle_stats_project(parse_sase_args(argv), argv=argv) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["schema"] == "sase.stats.project"
    assert envelope["data"] == view.data
    assert envelope["data"]["fingerprint"] == "golden"
    assert envelope["query"]["group_by"] == "model"


def test_cli_json_data_matches_projects_tui_worker_payload(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI envelope and TUI worker preserve the same shared wire payload."""
    from sase.stats.loader import load_statistics_view

    view = one_project_view()
    tui_calls: list[tuple[object, frozenset[str]]] = []

    def load_for_tui(query: object, *, facets: object) -> object:
        tui_calls.append((query, frozenset(facets)))  # type: ignore[arg-type]
        return view

    monkeypatch.setattr("sase.stats.loader.load_project_stats", load_for_tui)
    worker_result = load_statistics_view("projects", view.query.range, "sase")
    assert worker_result.project_stats is view
    assert tui_calls[0][1] == frozenset({"output", "runs"})

    monkeypatch.setattr(
        "sase.main.stats_handler_project.load_project_stats", lambda query: view
    )
    argv = ["stats", "project", "-p", "sase", "-j"]
    assert handle_stats_project(parse_sase_args(argv), argv=argv) == 0
    envelope = json.loads(capsys.readouterr().out)

    assert envelope["data"] == worker_result.project_stats.data


def test_json_and_explicit_json_format_agree(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    view = one_project_view()
    monkeypatch.setattr(
        "sase.main.stats_handler_project.load_project_stats", lambda query: view
    )

    handle_stats_project(parse_sase_args(["stats", "project", "-j"]))
    via_j = capsys.readouterr().out
    handle_stats_project(parse_sase_args(["stats", "project", "-f", "json"]))
    via_f = capsys.readouterr().out
    assert via_j == via_f


def test_cross_format_numbers_agree(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    view = one_project_view()
    monkeypatch.setattr(
        "sase.main.stats_handler_project.load_project_stats", lambda query: view
    )
    commits = view.data["projects"][0]["output"]["commits"]
    plans = view.data["projects"][0]["output"]["plans_committed"]
    runs = view.data["projects"][0]["runs"]["runs"]

    handle_stats_project(parse_sase_args(["stats", "project", "-j"]))
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["data"]["projects"][0]["output"]["commits"] == commits

    handle_stats_project(
        parse_sase_args(["stats", "project", "-f", "markdown"]),
        argv=["stats", "project", "-p", "sase"],
    )
    markdown = capsys.readouterr().out
    handle_stats_project(parse_sase_args(["stats", "project"]))
    rich = capsys.readouterr().out
    for value in (commits, plans, runs):
        token = f"{value:,}"
        assert token in markdown or str(value) in markdown
        assert token in rich or str(value) in rich


def _stub_fetch_request(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    monkeypatch.setattr(
        "sase.main.stats_handler_project.build_project_stats_request",
        lambda query, now_ts: SimpleNamespace(
            data={
                "projects": [
                    {
                        "key": "alpha",
                        "code_repos": [{"name": "alpha", "path": str(repo)}],
                    }
                ]
            }
        ),
    )


def test_fetch_failure_becomes_issue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "code"
    repo.mkdir()
    _stub_fetch_request(monkeypatch, repo)
    monkeypatch.setattr(
        "sase.main.stats_handler_project.load_project_stats",
        lambda query: one_project_view(),
    )

    def _fail(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        env = kwargs["env"]
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["GIT_OPTIONAL_LOCKS"] == "0"
        assert env["GIT_NO_LAZY_FETCH"] == "1"
        assert "GIT_DIR" not in env
        return subprocess.CompletedProcess(
            ["git", "fetch"], 1, stdout="", stderr="permission denied"
        )

    monkeypatch.setattr("sase.main.stats_handler_project.subprocess.run", _fail)

    assert (
        handle_stats_project(parse_sase_args(["stats", "project", "-F", "-p", "sase"]))
        == 0
    )
    rendered = capsys.readouterr().out
    assert "permission denied" in rendered
    assert "Fetch failed" in rendered


def test_fetch_success_adds_no_issue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "code"
    repo.mkdir()
    _stub_fetch_request(monkeypatch, repo)
    monkeypatch.setattr(
        "sase.main.stats_handler_project.load_project_stats",
        lambda query: one_project_view(),
    )
    monkeypatch.setattr(
        "sase.main.stats_handler_project.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["git", "fetch"], 0, stdout="", stderr=""
        ),
    )

    assert (
        handle_stats_project(parse_sase_args(["stats", "project", "-F", "-p", "sase"]))
        == 0
    )
    rendered = capsys.readouterr().out
    assert "Fetch failed" not in rendered
    assert "permission denied" not in rendered
