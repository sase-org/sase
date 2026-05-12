"""Phase 1 unit tests for ``tools/last_workflow_set_status``.

Covers argparse parsing, the ``GhClient`` wrapper around ``gh``, and the
``resolve_branch``/``main`` integration flow. Phase 2 (run-set selection)
and Phase 3 (failure diagnostics) tests live in sibling files; shared
helpers live in ``_last_workflow_set_status_helpers``.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from _last_workflow_set_status_helpers import (
    StubClient,
    fake_runner,
    install_stub,
    load_script,
    make_run,
)


@pytest.fixture(scope="module")
def script() -> types.ModuleType:
    return load_script()


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


def test_gh_client_default_branch(script: types.ModuleType) -> None:
    """``gh --jq`` emits the selected value as raw text — no JSON quoting."""
    capture: list[list[str]] = []
    client = script.GhClient(
        repo="sase-org/sase",
        executable=sys.executable,  # any existing executable resolves on PATH
        runner=fake_runner(stdout="master\n", capture=capture),
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


def test_gh_client_default_branch_strips_surrounding_whitespace(
    script: types.ModuleType,
) -> None:
    client = script.GhClient(
        executable=sys.executable,
        runner=fake_runner(stdout="   trunk   \n"),
    )
    assert client.default_branch() == "trunk"


def test_gh_client_propagates_repo(script: types.ModuleType) -> None:
    capture: list[list[str]] = []
    client = script.GhClient(
        repo="o/r",
        executable=sys.executable,
        runner=fake_runner(stdout="[]", capture=capture),
    )
    client.run_json(["run", "list"])
    assert capture[0][-2:] == ["--repo", "o/r"]


def test_gh_client_omits_repo_when_unset(script: types.ModuleType) -> None:
    capture: list[list[str]] = []
    client = script.GhClient(
        repo=None,
        executable=sys.executable,
        runner=fake_runner(stdout="[]", capture=capture),
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
        runner=fake_runner(returncode=1, stderr="auth required"),
    )
    with pytest.raises(script.GhCommandError) as info:
        client.run_text(["repo", "view"])
    assert info.value.returncode == 1
    assert "auth required" in str(info.value)
    assert info.value.exit_code == script.EXIT_CONFIG_ERROR


def test_gh_client_invalid_json(script: types.ModuleType) -> None:
    client = script.GhClient(
        executable=sys.executable,
        runner=fake_runner(stdout="not-json"),
    )
    with pytest.raises(script.GhJsonError) as info:
        client.run_json(["repo", "view"])
    assert info.value.exit_code == script.EXIT_CONFIG_ERROR


def test_gh_client_empty_default_branch_is_error(
    script: types.ModuleType,
) -> None:
    client = script.GhClient(
        executable=sys.executable,
        runner=fake_runner(stdout="   \n"),
    )
    with pytest.raises(script.GhError):
        client.default_branch()


def test_gh_client_api_uses_gh_repo_env_not_repo_flag(
    script: types.ModuleType,
) -> None:
    """``gh api`` has no ``--repo`` flag — explicit repos must travel via env."""
    capture: list[list[str]] = []
    env_capture: list[dict[str, str] | None] = []
    client = script.GhClient(
        repo="sase-org/sase",
        executable=sys.executable,
        runner=fake_runner(
            stdout='{"check_runs": []}',
            capture=capture,
            env_capture=env_capture,
        ),
    )
    client.list_sha_check_runs("deadbeef")

    argv = capture[0]
    assert argv[1] == "api"
    assert argv[2] == "repos/{owner}/{repo}/commits/deadbeef/check-runs"
    assert "--repo" not in argv
    assert env_capture[0] == {"GH_REPO": "sase-org/sase"}


def test_gh_client_api_without_repo_passes_no_env_override(
    script: types.ModuleType,
) -> None:
    capture: list[list[str]] = []
    env_capture: list[dict[str, str] | None] = []
    client = script.GhClient(
        repo=None,
        executable=sys.executable,
        runner=fake_runner(
            stdout='{"check_runs": []}',
            capture=capture,
            env_capture=env_capture,
        ),
    )
    client.list_sha_check_runs("cafef00d")

    argv = capture[0]
    assert "--repo" not in argv
    assert env_capture[0] is None


def test_gh_client_non_api_subcommand_still_uses_repo_flag(
    script: types.ModuleType,
) -> None:
    capture: list[list[str]] = []
    env_capture: list[dict[str, str] | None] = []
    client = script.GhClient(
        repo="o/r",
        executable=sys.executable,
        runner=fake_runner(stdout="[]", capture=capture, env_capture=env_capture),
    )
    client.run_json(["run", "list"])
    assert capture[0][-2:] == ["--repo", "o/r"]
    assert env_capture[0] is None


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


def test_main_passing_set(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs = [
        make_run(script, workflow="CI", sha="aaa", title="msg"),
        make_run(script, workflow="Deploy Docs", sha="aaa", title="msg"),
    ]
    stub = StubClient(runs=runs)
    install_stub(script, monkeypatch, stub)

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
        make_run(script, workflow="CI", sha="aaa", conclusion="failure"),
        make_run(script, workflow="Deploy Docs", sha="aaa", conclusion="success"),
    ]
    install_stub(script, monkeypatch, StubClient(runs=runs))
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
        make_run(script, workflow="CI", sha="aaa", status="in_progress", conclusion=""),
    ]
    install_stub(script, monkeypatch, StubClient(runs=runs))
    code = script.main([])
    assert code == script.EXIT_NO_COMPLETE_SET
    out = capsys.readouterr().out
    assert "No fully-completed" in out


def test_main_json_output_passing(
    script: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs = [make_run(script, workflow="CI", sha="zzz", branch="main")]
    install_stub(
        script, monkeypatch, StubClient(runs=runs, default_branch_value="main")
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
    install_stub(script, monkeypatch, StubClient(runs=[]))
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
    stub = StubClient(
        raise_on_default_branch=script.GhMissingError(
            "gh not installed", exit_code=script.EXIT_CONFIG_ERROR
        )
    )
    install_stub(script, monkeypatch, stub)
    code = script.main([])
    assert code == script.EXIT_CONFIG_ERROR
    err = capsys.readouterr().err
    assert "gh not installed" in err
