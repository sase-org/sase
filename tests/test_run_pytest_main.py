"""What `tools/run_pytest main()` guarantees before it hands off to pytest.

`main()` is the last code that runs in this process: it sanitizes the inherited
commit-workflow environment, prepares the scratch root, and keeps the leased
worker descriptors inheritable across `execv`. These tests intercept the exec
and assert on the state it would have handed over.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._run_pytest_fixtures import (
    PINNED_ENV_VARS,
    isolate_run_pytest_environment,  # noqa: F401 (registers autouse env-isolation fixture)
    load_run_pytest,
)


pytestmark = pytest.mark.contract


def test_pinned_env_vars_cover_every_key_main_sanitizes() -> None:
    runner = load_run_pytest()
    assert set(runner.PYTEST_ENV_UNSET_KEYS) <= set(PINNED_ENV_VARS)


def test_sanitizes_commit_workflow_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv("SASE_COMMIT_METHOD", "create_pull_request")
    monkeypatch.setenv("SASE_COMMIT_METHOD_ALLOW_OVERRIDE", "1")
    monkeypatch.setenv("SASE_PR_NAME", "fix_just_tests")
    monkeypatch.setenv("SASE_PR_STATUS", "draft")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent")

    runner._sanitize_pytest_environment()

    for key in runner.PYTEST_ENV_UNSET_KEYS:
        assert key not in runner.os.environ
    assert runner.os.environ["SASE_AGENT_NAME"] == "agent"


def test_main_prepares_governed_environment_and_descriptors_before_exec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv("SASE_TEST_GATE_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_TEST_GATE_SLOTS", "4")
    monkeypatch.setenv("SASE_TEST_GATE_TIMEOUT", "0")
    monkeypatch.setenv("SASE_PYTEST_WORKER_FLOOR", "2")
    monkeypatch.setenv("SASE_PYTEST_WORKER_CEILING", "3")
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.delenv(runner.PYTEST_DIST_ENV, raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_GOVERNED", raising=False)
    monkeypatch.setenv("SASE_COMMIT_METHOD", "create_pull_request")
    scratch_root = tmp_path / "scratch"
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(scratch_root))
    observed: dict[str, object] = {}

    class ExecCalled(Exception):
        pass

    def _execv(_executable: str, command: list[str]) -> None:
        observed["command"] = command
        observed["disabled"] = runner.os.environ.get("SASE_TEST_GATE_DISABLED")
        observed["governed"] = runner.os.environ.get("SASE_TEST_GATE_GOVERNED")
        observed["workflow"] = runner.os.environ.get("SASE_COMMIT_METHOD")
        observed["tmpdir"] = runner.os.environ.get("TMPDIR")
        observed["inheritable"] = [
            runner.os.get_inheritable(fd) for fd in _token_descriptors(tmp_path)
        ]
        raise ExecCalled

    monkeypatch.setattr(runner.os, "execv", _execv)

    with pytest.raises(ExecCalled):
        runner.main(["fast", "tests/test_run_pytest_main.py"])

    command = observed["command"]
    assert isinstance(command, list)
    assert command[3:6] == ["-n", "3", "--dist=worksteal"]
    assert observed["disabled"] == "1"
    assert observed["governed"] == "1"
    assert observed["workflow"] is None
    assert observed["tmpdir"] == str(scratch_root)
    assert scratch_root.is_dir()
    assert observed["inheritable"] == [True, True, True]
    assert "SASE_TEST_GATE_DISABLED" not in runner.os.environ
    assert "SASE_TEST_GATE_GOVERNED" not in runner.os.environ


def test_main_serial_snapshot_mode_never_acquires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_DIST_ENV, "invalid-but-unused")
    observed: dict[str, list[str]] = {}

    class ExecCalled(Exception):
        pass

    def _unexpected_grant() -> None:
        raise AssertionError("serial snapshot mode attempted token acquisition")

    def _execv(_executable: str, command: list[str]) -> None:
        observed["command"] = command
        raise ExecCalled

    monkeypatch.setattr(runner, "_parallel_worker_grant", _unexpected_grant)
    monkeypatch.setattr(runner.os, "execv", _execv)

    with pytest.raises(ExecCalled):
        runner.main(
            [
                "fast",
                "--inline-snapshot=fix",
                "tests/test_run_pytest_main.py",
            ]
        )

    assert "-n" not in observed["command"]
    assert not any(arg.startswith("--dist") for arg in observed["command"])


def test_main_terminal_smoke_mode_redirects_and_never_acquires(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_DIST_ENV, "invalid-but-unused")
    scratch_root = tmp_path / "scratch"
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(scratch_root))
    observed: dict[str, object] = {}

    class ExecCalled(Exception):
        pass

    def _unexpected_grant() -> None:
        raise AssertionError("terminal smoke mode attempted token acquisition")

    def _execv(_executable: str, command: list[str]) -> None:
        observed["command"] = command
        observed["tmpdir"] = runner.os.environ.get("TMPDIR")
        observed["redirected"] = runner.os.environ.get(runner.PYTEST_TMP_REDIRECTED_ENV)
        raise ExecCalled

    monkeypatch.setattr(runner, "_parallel_worker_grant", _unexpected_grant)
    monkeypatch.setattr(runner.os, "execv", _execv)

    with pytest.raises(ExecCalled):
        runner.main(["terminal-smoke", "tests/ace/tui/terminal_smoke"])

    command = observed["command"]
    assert isinstance(command, list)
    assert "-n" not in command
    assert not any(arg.startswith("--dist") for arg in command)
    assert command[-3:] == [
        "-m",
        runner.TERMINAL_SMOKE_MARKER_EXPRESSION,
        "tests/ace/tui/terminal_smoke",
    ]
    assert observed["tmpdir"] == str(scratch_root)
    assert observed["redirected"] == "1"


def test_main_rejects_invalid_distribution_before_worker_acquisition(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_DIST_ENV, "loadscope")

    def _unexpected_grant() -> None:
        raise AssertionError("invalid distribution attempted token acquisition")

    monkeypatch.setattr(runner, "_parallel_worker_grant", _unexpected_grant)

    result = runner.main(["fast", "tests/test_run_pytest_main.py"])

    assert result == int(pytest.ExitCode.USAGE_ERROR)
    assert (
        "pytest runner configuration error: SASE_PYTEST_DIST must be one of: "
        "loadfile, worksteal; got 'loadscope'"
    ) in capsys.readouterr().err


def _token_descriptors(directory: Path) -> list[int]:
    descriptors: list[int] = []
    for descriptor_path in Path("/proc/self/fd").iterdir():
        try:
            target = descriptor_path.readlink()
        except OSError:
            continue
        if target.parent == directory and target.name.startswith("token-"):
            descriptors.append(int(descriptor_path.name))
    return sorted(descriptors)
