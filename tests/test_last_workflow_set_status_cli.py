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
        jobs_by_run: dict[int, Any] | None = None,
        check_runs_by_sha: dict[str, Any] | None = None,
        annotations_by_check_run: dict[int, Any] | None = None,
        logs_by_run: dict[int, Any] | None = None,
    ) -> None:
        self._runs = runs or []
        self._default_branch = default_branch_value
        self._raise_default = raise_on_default_branch
        self._raise_list = raise_on_list_runs
        self._jobs_by_run = jobs_by_run or {}
        self._check_runs_by_sha = check_runs_by_sha or {}
        self._annotations_by_check_run = annotations_by_check_run or {}
        self._logs_by_run = logs_by_run or {}
        self.list_runs_calls: list[dict[str, Any]] = []
        self.list_jobs_calls: list[int] = []
        self.list_sha_check_runs_calls: list[str] = []
        self.list_check_run_annotations_calls: list[int] = []
        self.fetch_failed_log_calls: list[int] = []

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

    def list_jobs(self, run_id: int) -> list[Any]:
        self.list_jobs_calls.append(run_id)
        value = self._jobs_by_run.get(run_id, [])
        if isinstance(value, Exception):
            raise value
        return list(value)

    def list_sha_check_runs(self, sha: str) -> list[Any]:
        self.list_sha_check_runs_calls.append(sha)
        value = self._check_runs_by_sha.get(sha, [])
        if isinstance(value, Exception):
            raise value
        return list(value)

    def list_check_run_annotations(self, check_run: Any) -> list[Any]:
        self.list_check_run_annotations_calls.append(check_run.check_run_id)
        value = self._annotations_by_check_run.get(check_run.check_run_id, [])
        if isinstance(value, Exception):
            raise value
        return list(value)

    def fetch_failed_log(self, run_id: int) -> str:
        self.fetch_failed_log_calls.append(run_id)
        value = self._logs_by_run.get(run_id, "")
        if isinstance(value, Exception):
            raise value
        return value


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


# ---------------------------------------------------------------------------
# Phase 3: failure diagnostics
# ---------------------------------------------------------------------------


def _make_job(
    script: types.ModuleType,
    *,
    name: str,
    conclusion: str = "failure",
    status: str = "completed",
    database_id: int = 0,
    url: str = "",
    steps: tuple[Any, ...] = (),
) -> Any:
    return script.Job(
        database_id=database_id or (hash(name) & 0xFFFFFFFF),
        name=name,
        status=status,
        conclusion=conclusion,
        url=url,
        steps=steps,
    )


def _make_check_run(
    script: types.ModuleType,
    *,
    name: str,
    check_run_id: int,
    conclusion: str = "failure",
    status: str = "completed",
) -> Any:
    return script.CheckRun(
        check_run_id=check_run_id,
        name=name,
        status=status,
        conclusion=conclusion,
    )


def _make_annotation(
    script: types.ModuleType,
    *,
    check_run: Any,
    path: str = "src/example.py",
    start_line: int = 12,
    title: str = "boom",
    message: str = "It exploded.",
) -> Any:
    return script.Annotation(
        check_run_id=check_run.check_run_id,
        check_run_name=check_run.name,
        path=path,
        start_line=start_line,
        end_line=start_line,
        annotation_level="failure",
        title=title,
        message=message,
    )


def test_parse_jobs_handles_steps(script: types.ModuleType) -> None:
    payload = {
        "jobs": [
            {
                "databaseId": 7,
                "name": "build",
                "status": "completed",
                "conclusion": "failure",
                "url": "https://example/job/7",
                "steps": [
                    {
                        "name": "Setup",
                        "status": "completed",
                        "conclusion": "success",
                        "number": 1,
                    },
                    {
                        "name": "Test",
                        "status": "completed",
                        "conclusion": "failure",
                        "number": 4,
                    },
                ],
            }
        ]
    }
    jobs = script.parse_jobs(payload)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.name == "build"
    assert not job.passed
    failed_steps = job.failed_steps
    assert len(failed_steps) == 1
    assert failed_steps[0].number == 4
    assert failed_steps[0].name == "Test"


def test_parse_check_runs_skips_invalid(script: types.ModuleType) -> None:
    payload = {
        "check_runs": [
            {"name": "no-id"},
            {
                "id": 99,
                "name": "build",
                "status": "completed",
                "conclusion": "failure",
            },
        ]
    }
    out = script.parse_check_runs(payload)
    assert len(out) == 1
    assert out[0].check_run_id == 99
    assert not out[0].passed
    assert out[0].is_terminal


def test_parse_annotations_uses_check_run_identity(
    script: types.ModuleType,
) -> None:
    check_run = _make_check_run(script, name="build", check_run_id=42)
    payload = [
        {
            "path": "src/x.py",
            "start_line": 10,
            "end_line": 11,
            "annotation_level": "failure",
            "title": "BOOM",
            "message": "exploded",
        }
    ]
    out = script.parse_annotations(payload, check_run=check_run)
    assert len(out) == 1
    assert out[0].check_run_id == 42
    assert out[0].check_run_name == "build"
    assert out[0].path == "src/x.py"


def test_diagnostics_annotations_preferred_over_logs(
    script: types.ModuleType,
) -> None:
    failed_run = _make_run(
        script,
        workflow="CI",
        sha="abc",
        conclusion="failure",
        database_id=100,
        workflow_id=10,
    )
    other_run = _make_run(
        script,
        workflow="Deploy",
        sha="abc",
        conclusion="success",
        database_id=200,
        workflow_id=20,
    )
    run_set = script.RunSet(
        head_sha="abc",
        head_branch="master",
        display_title="",
        created_at="2026-05-11T00:00:00Z",
        runs=(failed_run, other_run),
    )
    failing_check_run = _make_check_run(
        script, name="build", check_run_id=555, conclusion="failure"
    )
    annotation = _make_annotation(script, check_run=failing_check_run)
    stub = _StubClient(
        jobs_by_run={
            100: [
                _make_job(script, name="build", conclusion="failure", database_id=1),
            ]
        },
        check_runs_by_sha={"abc": [failing_check_run]},
        annotations_by_check_run={555: [annotation]},
        logs_by_run={100: "should not be read"},
    )

    diagnostics = script.gather_failure_diagnostics(stub, run_set, tail=10)

    assert len(diagnostics) == 1
    diag = diagnostics[0]
    assert diag.source == script.DIAG_SOURCE_ANNOTATIONS
    assert diag.annotations == (annotation,)
    assert diag.log_tail == ()
    # Annotations were found, so the log endpoint must not have been hit.
    assert stub.fetch_failed_log_calls == []


def test_diagnostics_logs_tailed_to_requested_lines(
    script: types.ModuleType,
) -> None:
    failed_run = _make_run(
        script,
        workflow="CI",
        sha="abc",
        conclusion="failure",
        database_id=100,
    )
    run_set = script.RunSet(
        head_sha="abc",
        head_branch="master",
        display_title="",
        created_at="2026-05-11T00:00:00Z",
        runs=(failed_run,),
    )
    log = "\n".join(f"line {i}" for i in range(100))
    stub = _StubClient(
        jobs_by_run={100: [_make_job(script, name="build", conclusion="failure")]},
        # No matching check-runs → fall back to logs.
        check_runs_by_sha={"abc": []},
        logs_by_run={100: log},
    )

    diagnostics = script.gather_failure_diagnostics(stub, run_set, tail=5)

    assert len(diagnostics) == 1
    diag = diagnostics[0]
    assert diag.source == script.DIAG_SOURCE_LOGS
    assert diag.log_tail == (
        "line 95",
        "line 96",
        "line 97",
        "line 98",
        "line 99",
    )
    assert stub.fetch_failed_log_calls == [100]


def test_diagnostics_jobs_only_when_logs_empty(
    script: types.ModuleType,
) -> None:
    failed_run = _make_run(
        script,
        workflow="CI",
        sha="abc",
        conclusion="failure",
        database_id=100,
    )
    run_set = script.RunSet(
        head_sha="abc",
        head_branch="master",
        display_title="",
        created_at="2026-05-11T00:00:00Z",
        runs=(failed_run,),
    )
    failing_job = _make_job(
        script,
        name="build",
        conclusion="failure",
        steps=(
            script.JobStep(
                name="Compile",
                status="completed",
                conclusion="failure",
                number=2,
            ),
        ),
    )
    stub = _StubClient(
        jobs_by_run={100: [failing_job]},
        check_runs_by_sha={"abc": []},
        logs_by_run={100: ""},
    )

    diagnostics = script.gather_failure_diagnostics(stub, run_set, tail=20)

    diag = diagnostics[0]
    assert diag.source == script.DIAG_SOURCE_JOBS_ONLY
    assert diag.failed_jobs == (failing_job,)
    assert diag.annotations == ()
    assert diag.log_tail == ()
    # We still attempt the log fetch exactly once, even when annotations
    # are absent and the log turns out to be empty.
    assert stub.fetch_failed_log_calls == [100]


def test_diagnostics_cancelled_run_does_not_retry_log(
    script: types.ModuleType,
) -> None:
    cancelled_run = _make_run(
        script,
        workflow="CI",
        sha="abc",
        conclusion="cancelled",
        database_id=100,
    )
    run_set = script.RunSet(
        head_sha="abc",
        head_branch="master",
        display_title="",
        created_at="2026-05-11T00:00:00Z",
        runs=(cancelled_run,),
    )
    log_error = script.GhCommandError(
        ["gh", "run", "view", "100", "--log-failed"],
        1,
        "no logs available for cancelled run",
    )
    stub = _StubClient(
        jobs_by_run={100: [_make_job(script, name="build", conclusion="cancelled")]},
        check_runs_by_sha={"abc": []},
        logs_by_run={100: log_error},
    )

    diagnostics = script.gather_failure_diagnostics(stub, run_set, tail=10)

    diag = diagnostics[0]
    assert diag.source == script.DIAG_SOURCE_JOBS_ONLY
    assert diag.log_tail == ()
    assert "cancelled" in diag.log_error
    # Crucially, exactly one log fetch attempt — no retry loop.
    assert stub.fetch_failed_log_calls == [100]


def test_diagnostics_multiple_failed_workflows_reported_independently(
    script: types.ModuleType,
) -> None:
    run_a = _make_run(
        script,
        workflow="CI",
        sha="abc",
        conclusion="failure",
        database_id=100,
        workflow_id=10,
    )
    run_b = _make_run(
        script,
        workflow="Lint",
        sha="abc",
        conclusion="failure",
        database_id=200,
        workflow_id=20,
    )
    run_set = script.RunSet(
        head_sha="abc",
        head_branch="master",
        display_title="",
        created_at="2026-05-11T00:00:00Z",
        runs=(run_a, run_b),
    )
    cr_a = _make_check_run(script, name="build", check_run_id=11, conclusion="failure")
    annotation_a = _make_annotation(
        script, check_run=cr_a, path="a.py", title="A failed"
    )
    stub = _StubClient(
        jobs_by_run={
            100: [_make_job(script, name="build", conclusion="failure")],
            200: [_make_job(script, name="ruff", conclusion="failure")],
        },
        # Only run_a has a matching check-run; run_b falls back to logs.
        check_runs_by_sha={"abc": [cr_a]},
        annotations_by_check_run={11: [annotation_a]},
        logs_by_run={200: "tail line 1\ntail line 2\n"},
    )

    diagnostics = script.gather_failure_diagnostics(stub, run_set, tail=5)

    assert len(diagnostics) == 2
    by_run = {d.run.database_id: d for d in diagnostics}
    diag_a = by_run[100]
    diag_b = by_run[200]
    assert diag_a.source == script.DIAG_SOURCE_ANNOTATIONS
    assert diag_a.annotations == (annotation_a,)
    assert diag_b.source == script.DIAG_SOURCE_LOGS
    assert diag_b.log_tail == ("tail line 1", "tail line 2")
    # Only run_b should have used the log endpoint.
    assert stub.fetch_failed_log_calls == [200]


def test_main_failing_set_includes_diagnostics(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs = [
        _make_run(
            script,
            workflow="CI",
            sha="abc",
            conclusion="failure",
            database_id=100,
            workflow_id=10,
        ),
        _make_run(
            script,
            workflow="Deploy",
            sha="abc",
            conclusion="success",
            database_id=200,
            workflow_id=20,
        ),
    ]
    failing_job = _make_job(
        script,
        name="build",
        conclusion="failure",
        steps=(
            script.JobStep(
                name="Test",
                status="completed",
                conclusion="failure",
                number=3,
            ),
        ),
    )
    cr = _make_check_run(script, name="build", check_run_id=42, conclusion="failure")
    annotation = _make_annotation(script, check_run=cr, path="src/x.py", title="oops")
    stub = _StubClient(
        runs=runs,
        jobs_by_run={100: [failing_job]},
        check_runs_by_sha={"abc": [cr]},
        annotations_by_check_run={42: [annotation]},
    )
    _install_stub(script, monkeypatch, stub)

    code = script.main(["--json"])
    assert code == script.EXIT_FAIL
    payload = json.loads(capsys.readouterr().out)
    diags = payload["diagnostics"]
    assert len(diags) == 1
    assert diags[0]["source"] == script.DIAG_SOURCE_ANNOTATIONS
    assert diags[0]["annotations"][0]["path"] == "src/x.py"
    # Only the failed run should have been queried for jobs.
    assert stub.list_jobs_calls == [100]


def test_main_human_output_renders_diagnostic_block(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs = [
        _make_run(
            script,
            workflow="CI",
            sha="abc",
            conclusion="failure",
            database_id=100,
        ),
    ]
    failing_job = _make_job(
        script,
        name="build",
        conclusion="failure",
    )
    stub = _StubClient(
        runs=runs,
        jobs_by_run={100: [failing_job]},
        check_runs_by_sha={"abc": []},
        logs_by_run={100: "alpha\nbeta\ngamma\n"},
    )
    _install_stub(script, monkeypatch, stub)

    code = script.main(["--tail", "2"])
    assert code == script.EXIT_FAIL
    out = capsys.readouterr().out
    assert "CI (failure detail)" in out
    assert "job: build" in out
    assert "log tail (last 2 line(s))" in out
    assert "beta" in out and "gamma" in out
    # Tail should have trimmed the earlier line.
    assert "alpha" not in out.split("log tail", 1)[1]
