"""Unit tests for ``tools/last_workflow_set_status`` (Phase 1 surface).

The script has no ``.py`` suffix, so the test module loads it through
``importlib.machinery.SourceFileLoader`` and exposes it as a fixture.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "tools" / "last_workflow_set_status"


def _load_script() -> types.ModuleType:
    """Load the suffix-less tool script as a module."""
    loader = importlib.machinery.SourceFileLoader(
        "last_workflow_set_status", str(SCRIPT_PATH)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> types.ModuleType:
    return _load_script()


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------


def test_parse_args_defaults(script: types.ModuleType) -> None:
    config = script.parse_args([])
    assert config.repo is None
    assert config.branch is None
    assert config.limit == script.DEFAULT_LIMIT
    assert config.tail == script.DEFAULT_TAIL
    assert config.events == script.DEFAULT_EVENTS
    assert config.require == ()
    assert config.json_output is False


def test_parse_args_overrides(script: types.ModuleType) -> None:
    config = script.parse_args(
        [
            "--repo",
            "sase-org/sase",
            "--branch",
            "master",
            "--limit",
            "100",
            "--tail",
            "10",
            "--event",
            "push",
            "--event",
            "merge_group",
            "--require",
            "CI, Deploy Docs ,",
            "--json",
        ]
    )
    assert config.repo == "sase-org/sase"
    assert config.branch == "master"
    assert config.limit == 100
    assert config.tail == 10
    assert config.events == ("push", "merge_group")
    assert config.require == ("CI", "Deploy Docs")
    assert config.json_output is True


@pytest.mark.parametrize(
    "argv",
    [
        ["--limit", "0"],
        ["--limit", "-3"],
        ["--tail", "0"],
        ["--repo", "not-a-slash-form"],
    ],
)
def test_parse_args_rejects_bad_values(
    script: types.ModuleType, argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as info:
        script.parse_args(argv)
    assert info.value.code == 2


# ---------------------------------------------------------------------------
# GhClient
# ---------------------------------------------------------------------------


def _fake_runner(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
    capture: list[list[str]] | None = None,
):
    def _run(argv):
        if capture is not None:
            capture.append(list(argv))
        return subprocess.CompletedProcess(
            args=list(argv),
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return _run


def test_gh_client_default_branch(script: types.ModuleType) -> None:
    capture: list[list[str]] = []
    client = script.GhClient(
        repo="sase-org/sase",
        executable=sys.executable,  # any existing executable resolves on PATH
        runner=_fake_runner(stdout='"master"\n', capture=capture),
    )
    assert client.default_branch() == "master"

    argv = capture[0]
    assert argv[0] == sys.executable
    assert argv[1:] == [
        "repo",
        "view",
        "--json",
        "defaultBranchRef",
        "--jq",
        ".defaultBranchRef.name",
        "--repo",
        "sase-org/sase",
    ]


def test_gh_client_propagates_repo(script: types.ModuleType) -> None:
    capture: list[list[str]] = []
    client = script.GhClient(
        repo="o/r",
        executable=sys.executable,
        runner=_fake_runner(stdout="[]", capture=capture),
    )
    client.run_json(["run", "list"])
    assert capture[0][-2:] == ["--repo", "o/r"]


def test_gh_client_omits_repo_when_unset(script: types.ModuleType) -> None:
    capture: list[list[str]] = []
    client = script.GhClient(
        repo=None,
        executable=sys.executable,
        runner=_fake_runner(stdout="[]", capture=capture),
    )
    client.run_json(["run", "list"])
    assert "--repo" not in capture[0]


def test_gh_client_missing_executable(script: types.ModuleType) -> None:
    client = script.GhClient(executable="definitely-not-on-path-xyz")
    with pytest.raises(script.GhMissingError) as info:
        client.run_text(["repo", "view"])
    assert info.value.exit_code == script.EXIT_CONFIG_ERROR


def test_gh_client_nonzero_exit(script: types.ModuleType) -> None:
    client = script.GhClient(
        executable=sys.executable,
        runner=_fake_runner(returncode=1, stderr="auth required"),
    )
    with pytest.raises(script.GhCommandError) as info:
        client.run_text(["repo", "view"])
    assert info.value.returncode == 1
    assert "auth required" in str(info.value)
    assert info.value.exit_code == script.EXIT_CONFIG_ERROR


def test_gh_client_invalid_json(script: types.ModuleType) -> None:
    client = script.GhClient(
        executable=sys.executable,
        runner=_fake_runner(stdout="not-json"),
    )
    with pytest.raises(script.GhJsonError) as info:
        client.run_json(["repo", "view"])
    assert info.value.exit_code == script.EXIT_CONFIG_ERROR


def test_gh_client_empty_default_branch_is_error(
    script: types.ModuleType,
) -> None:
    client = script.GhClient(
        executable=sys.executable,
        runner=_fake_runner(stdout='""'),
    )
    with pytest.raises(script.GhJsonError):
        client.default_branch()


# ---------------------------------------------------------------------------
# resolve_branch + main flow
# ---------------------------------------------------------------------------


def test_resolve_branch_prefers_explicit(script: types.ModuleType) -> None:
    config = script.parse_args(["--branch", "topic"])

    class _Boom:
        def default_branch(self) -> str:  # pragma: no cover - must not be called
            raise AssertionError("default_branch should not be queried")

    assert script.resolve_branch(config, _Boom()) == "topic"


def test_resolve_branch_falls_back_to_default(script: types.ModuleType) -> None:
    config = script.parse_args([])

    class _Stub:
        def default_branch(self) -> str:
            return "main"

    assert script.resolve_branch(config, _Stub()) == "main"


def _make_run(
    script: types.ModuleType,
    *,
    workflow: str,
    sha: str,
    status: str = "completed",
    conclusion: str = "success",
    attempt: int = 1,
    created_at: str = "2026-05-11T12:00:00Z",
    updated_at: str | None = None,
    workflow_id: int | None = None,
    database_id: int | None = None,
    title: str = "",
    url: str = "",
    branch: str = "master",
):
    return script.WorkflowRun(
        database_id=database_id
        if database_id is not None
        else hash((workflow, sha, attempt)) & 0xFFFFFFFF,
        workflow_name=workflow,
        workflow_database_id=workflow_id
        if workflow_id is not None
        else hash(workflow) & 0xFFFF,
        head_sha=sha,
        head_branch=branch,
        status=status,
        conclusion=conclusion,
        created_at=created_at,
        updated_at=updated_at if updated_at is not None else created_at,
        event="push",
        attempt=attempt,
        display_title=title,
        url=url,
    )


class _StubClient:
    """In-test replacement for ``GhClient`` that returns canned data."""

    def __init__(
        self,
        *,
        runs: list[Any] | None = None,
        default_branch_value: str = "master",
        raise_on_default_branch: Exception | None = None,
        raise_on_list_runs: Exception | None = None,
    ) -> None:
        self._runs = runs or []
        self._default_branch = default_branch_value
        self._raise_default = raise_on_default_branch
        self._raise_list = raise_on_list_runs
        self.list_runs_calls: list[dict[str, Any]] = []

    def default_branch(self) -> str:
        if self._raise_default is not None:
            raise self._raise_default
        return self._default_branch

    def list_runs(self, *, branch: str, events: Any, limit: int) -> list[Any]:
        if self._raise_list is not None:
            raise self._raise_list
        self.list_runs_calls.append(
            {"branch": branch, "events": tuple(events), "limit": limit}
        )
        return list(self._runs)


def _install_stub(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    stub: _StubClient,
) -> None:
    def _factory(*_args: Any, **_kwargs: Any) -> _StubClient:
        return stub

    monkeypatch.setattr(script, "GhClient", _factory)


def test_main_passing_set(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs = [
        _make_run(script, workflow="CI", sha="aaa", title="msg"),
        _make_run(script, workflow="Deploy Docs", sha="aaa", title="msg"),
    ]
    stub = _StubClient(runs=runs)
    _install_stub(script, monkeypatch, stub)

    code = script.main(["--repo", "sase-org/sase"])
    assert code == script.EXIT_PASS
    out = capsys.readouterr().out
    assert "All 2 workflow(s) passed" in out
    assert "CI" in out and "Deploy Docs" in out
    assert stub.list_runs_calls[0]["branch"] == "master"


def test_main_failing_set(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs = [
        _make_run(script, workflow="CI", sha="aaa", conclusion="failure"),
        _make_run(script, workflow="Deploy Docs", sha="aaa", conclusion="success"),
    ]
    _install_stub(script, monkeypatch, _StubClient(runs=runs))
    code = script.main([])
    assert code == script.EXIT_FAIL
    out = capsys.readouterr().out
    assert "FAIL: 1 of 2" in out


def test_main_no_complete_set(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs = [
        _make_run(
            script, workflow="CI", sha="aaa", status="in_progress", conclusion=""
        ),
    ]
    _install_stub(script, monkeypatch, _StubClient(runs=runs))
    code = script.main([])
    assert code == script.EXIT_NO_COMPLETE_SET
    out = capsys.readouterr().out
    assert "No fully-completed" in out


def test_main_json_output_passing(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs = [_make_run(script, workflow="CI", sha="zzz", branch="main")]
    _install_stub(
        script, monkeypatch, _StubClient(runs=runs, default_branch_value="main")
    )
    code = script.main(["--json"])
    assert code == script.EXIT_PASS
    payload = json.loads(capsys.readouterr().out)
    assert payload["branch"] == "main"
    assert payload["ok"] is True
    assert payload["run_set"]["head_sha"] == "zzz"
    assert len(payload["run_set"]["runs"]) == 1


def test_main_json_output_no_set(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_stub(script, monkeypatch, _StubClient(runs=[]))
    code = script.main(["--json"])
    assert code == script.EXIT_NO_COMPLETE_SET
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_set"] is None
    assert payload["ok"] is False


def test_main_surfaces_gh_errors(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stub = _StubClient(
        raise_on_default_branch=script.GhMissingError(
            "gh not installed", exit_code=script.EXIT_CONFIG_ERROR
        )
    )
    _install_stub(script, monkeypatch, stub)
    code = script.main([])
    assert code == script.EXIT_CONFIG_ERROR
    err = capsys.readouterr().err
    assert "gh not installed" in err


# ---------------------------------------------------------------------------
# Phase 2: parsing and selection
# ---------------------------------------------------------------------------


def test_parse_runs_skips_invalid_entries(script: types.ModuleType) -> None:
    payload = [
        # missing identifying fields
        {"workflowName": "CI"},
        # not a dict
        "junk",
        # valid
        {
            "databaseId": 1,
            "workflowName": "CI",
            "workflowDatabaseId": 100,
            "headSha": "abc",
            "headBranch": "master",
            "status": "completed",
            "conclusion": "success",
            "createdAt": "2026-05-11T10:00:00Z",
            "updatedAt": "2026-05-11T10:01:00Z",
            "event": "push",
            "attempt": 1,
            "displayTitle": "msg",
            "url": "https://example/runs/1",
        },
    ]
    runs = script.parse_runs(payload)
    assert len(runs) == 1
    assert runs[0].workflow_name == "CI"
    assert runs[0].head_sha == "abc"
    assert runs[0].passed
    assert runs[0].is_terminal


def test_parse_runs_rejects_non_array(script: types.ModuleType) -> None:
    with pytest.raises(script.GhJsonError):
        script.parse_runs({"oops": True})


def test_dedup_keeps_highest_attempt(script: types.ModuleType) -> None:
    older = _make_run(
        script,
        workflow="CI",
        sha="aaa",
        attempt=1,
        conclusion="failure",
        workflow_id=1,
        database_id=1,
        updated_at="2026-05-11T10:00:00Z",
    )
    rerun = _make_run(
        script,
        workflow="CI",
        sha="aaa",
        attempt=2,
        conclusion="success",
        workflow_id=1,
        database_id=2,
        updated_at="2026-05-11T11:00:00Z",
    )
    deduped = script.dedup_runs([older, rerun])
    assert len(deduped) == 1
    assert deduped[0].attempt == 2
    assert deduped[0].conclusion == "success"


def test_dedup_tiebreaks_on_updated_at(script: types.ModuleType) -> None:
    earlier = _make_run(
        script,
        workflow="CI",
        sha="aaa",
        attempt=1,
        workflow_id=1,
        database_id=1,
        updated_at="2026-05-11T09:00:00Z",
    )
    later = _make_run(
        script,
        workflow="CI",
        sha="aaa",
        attempt=1,
        workflow_id=1,
        database_id=2,
        updated_at="2026-05-11T11:00:00Z",
    )
    deduped = script.dedup_runs([earlier, later])
    assert len(deduped) == 1
    assert deduped[0].database_id == 2


def test_group_by_sha_newest_first(script: types.ModuleType) -> None:
    older = _make_run(
        script,
        workflow="CI",
        sha="old",
        created_at="2026-05-10T00:00:00Z",
        workflow_id=1,
        database_id=1,
    )
    newer = _make_run(
        script,
        workflow="CI",
        sha="new",
        created_at="2026-05-11T00:00:00Z",
        workflow_id=1,
        database_id=2,
    )
    groups = script.group_by_sha([older, newer])
    assert [sha for sha, _ in groups] == ["new", "old"]


def test_select_skips_incomplete_groups(script: types.ModuleType) -> None:
    runs = [
        # newest SHA still in progress
        _make_run(
            script,
            workflow="CI",
            sha="new",
            created_at="2026-05-11T12:00:00Z",
            status="in_progress",
            conclusion="",
            workflow_id=1,
            database_id=1,
        ),
        # older complete SHA
        _make_run(
            script,
            workflow="CI",
            sha="old",
            created_at="2026-05-10T00:00:00Z",
            workflow_id=1,
            database_id=2,
        ),
        _make_run(
            script,
            workflow="Deploy",
            sha="old",
            created_at="2026-05-10T00:00:00Z",
            workflow_id=2,
            database_id=3,
        ),
    ]
    result = script.select_run_set(runs)
    assert result.run_set is not None
    assert result.run_set.head_sha == "old"
    assert result.skipped_incomplete == 1


def test_select_requires_named_workflows(script: types.ModuleType) -> None:
    # Newest SHA has CI but not Deploy → skipped via --require.
    runs = [
        _make_run(
            script,
            workflow="CI",
            sha="new",
            created_at="2026-05-11T00:00:00Z",
            workflow_id=1,
            database_id=1,
        ),
        _make_run(
            script,
            workflow="CI",
            sha="old",
            created_at="2026-05-10T00:00:00Z",
            workflow_id=1,
            database_id=2,
        ),
        _make_run(
            script,
            workflow="Deploy",
            sha="old",
            created_at="2026-05-10T00:00:00Z",
            workflow_id=2,
            database_id=3,
        ),
    ]
    result = script.select_run_set(runs, require=("CI", "Deploy"))
    assert result.run_set is not None
    assert result.run_set.head_sha == "old"
    assert result.skipped_missing_required == 1


def test_select_returns_none_when_no_complete_set(
    script: types.ModuleType,
) -> None:
    runs = [
        _make_run(
            script,
            workflow="CI",
            sha="x",
            status="in_progress",
            conclusion="",
            workflow_id=1,
            database_id=1,
        ),
    ]
    result = script.select_run_set(runs)
    assert result.run_set is None
    assert result.skipped_incomplete == 1


@pytest.mark.parametrize(
    "conclusion,expected_pass",
    [
        ("success", True),
        ("skipped", True),
        ("neutral", True),
        ("failure", False),
        ("cancelled", False),
        ("timed_out", False),
        ("startup_failure", False),
    ],
)
def test_pass_conclusion_classification(
    script: types.ModuleType, conclusion: str, expected_pass: bool
) -> None:
    run = _make_run(
        script,
        workflow="CI",
        sha="aaa",
        conclusion=conclusion,
    )
    assert run.passed is expected_pass


def test_list_runs_uses_correct_arguments(script: types.ModuleType) -> None:
    capture: list[list[str]] = []
    payload = json.dumps(
        [
            {
                "databaseId": 1,
                "workflowName": "CI",
                "workflowDatabaseId": 10,
                "headSha": "abc",
                "headBranch": "master",
                "status": "completed",
                "conclusion": "success",
                "createdAt": "2026-05-11T00:00:00Z",
                "updatedAt": "2026-05-11T00:00:00Z",
                "event": "push",
                "attempt": 1,
                "displayTitle": "t",
                "url": "https://example",
            }
        ]
    )
    client = script.GhClient(
        repo="o/r",
        executable=sys.executable,
        runner=_fake_runner(stdout=payload, capture=capture),
    )
    runs = client.list_runs(branch="master", events=("push",), limit=42)
    assert len(runs) == 1
    argv = capture[0]
    assert "run" in argv and "list" in argv
    assert "--branch" in argv and "master" in argv
    assert "--event" in argv and "push" in argv
    assert "--limit" in argv and "42" in argv
    assert argv[-2:] == ["--repo", "o/r"]


def test_format_human_no_set(script: types.ModuleType) -> None:
    result = script.SelectionResult(
        run_set=None, skipped_incomplete=2, skipped_missing_required=1
    )
    text = script.format_human(result, branch="master")
    assert "No fully-completed" in text
    assert "Skipped 2" in text
    assert "Skipped 1" in text


def test_format_json_run_set_shape(script: types.ModuleType) -> None:
    runs = (
        _make_run(script, workflow="CI", sha="abc"),
        _make_run(script, workflow="Deploy", sha="abc", conclusion="failure"),
    )
    run_set = script.RunSet(
        head_sha="abc",
        head_branch="master",
        display_title="t",
        created_at="2026-05-11T00:00:00Z",
        runs=runs,
    )
    result = script.SelectionResult(run_set=run_set)
    payload = json.loads(script.format_json(result, branch="master"))
    assert payload["ok"] is False
    assert payload["run_set"]["head_sha"] == "abc"
    assert {r["workflow_name"] for r in payload["run_set"]["runs"]} == {
        "CI",
        "Deploy",
    }
