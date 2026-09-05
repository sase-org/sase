"""What `tools/run_pytest main()` guarantees before it hands off to pytest.

`main()` is the last code that runs in this process: it sanitizes the inherited
commit-workflow environment, prepares the scratch root, and keeps the leased
worker descriptors inheritable across `execv`. These tests intercept the exec
and assert on the state it would have handed over.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._run_pytest_fixtures import (
    AMBIENT_MODE_ENV_VARS,
    PINNED_ENV_VARS,
    isolate_run_pytest_environment,  # noqa: F401 (registers autouse env-isolation fixture)
    load_run_pytest,
)
from tests._suite_gate_env import FDS_ENV


pytestmark = pytest.mark.contract


def test_pinned_env_vars_cover_every_key_main_sanitizes() -> None:
    runner = load_run_pytest()
    assert set(runner.PYTEST_ENV_UNSET_KEYS) <= set(PINNED_ENV_VARS)


def test_pinned_env_vars_cover_every_request_main_writes_for_its_plugins() -> None:
    """The record requests leak past teardown unless they are pinned too.

    `main()` writes these straight to `os.environ` for the plugins it is about
    to `execv` into. A test that drives `main()` without pinning them leaves
    them set for every later test on the same worker, which is what made
    `test_repeat_runs_neither_lease_the_gate_nor_record_health` fail only when
    a health test happened to run before it.
    """
    runner = load_run_pytest()
    assert {
        runner.COVERAGE_CORE_ENV,
        runner.RECORD_ENV,
        runner.TIMINGS_RECORD_ENV,
        runner.TEST_COST_RECORD_ENV,
    } <= set(PINNED_ENV_VARS)


def test_pinned_env_vars_cover_every_lane_switch_main_writes() -> None:
    runner = load_run_pytest()
    assert runner.ACE_PAGE_GROUP_ISOLATION_ENV in PINNED_ENV_VARS


def test_ambient_mode_env_vars_name_the_switch_the_contention_harness_exports() -> None:
    runner = load_run_pytest()
    assert runner.HEALTH_DISABLED_ENV in AMBIENT_MODE_ENV_VARS
    assert runner._contention_environment(Path("failures.json")).keys() >= {
        runner.HEALTH_DISABLED_ENV
    }


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
        fds = [
            int(value)
            for value in runner.os.environ.get(FDS_ENV, "").split(",")
            if value
        ]
        observed["inheritable"] = [runner.os.get_inheritable(fd) for fd in fds]
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


def test_main_cost_mode_arms_cost_and_health_recorders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(tmp_path / "scratch"))
    monkeypatch.setenv("SASE_TEST_GATE_DIR", str(tmp_path / "gate"))
    monkeypatch.setattr(runner, "_parallel_worker_grant", lambda: (2, None))
    observed: dict[str, object] = {}

    class ExecCalled(Exception):
        pass

    def _execv(_executable: str, command: list[str]) -> None:
        observed["command"] = command
        observed["health_request"] = runner.os.environ.get(runner.RECORD_ENV)
        observed["timings_request"] = runner.os.environ.get(runner.TIMINGS_RECORD_ENV)
        observed["cost_request"] = runner.os.environ.get(runner.TEST_COST_RECORD_ENV)
        raise ExecCalled

    monkeypatch.setattr(runner.os, "execv", _execv)

    with pytest.raises(ExecCalled):
        runner.main(["cost", "tests/test_run_pytest_main.py"])

    command = observed["command"]
    assert isinstance(command, list)
    assert runner.TIMINGS_PLUGIN_MODULE not in command
    assert runner.TEST_COST_PLUGIN_MODULE in command
    assert runner.HEALTH_PLUGIN_MODULE in command
    assert runner.GLOBAL_STATE_LEAK_PLUGIN_MODULE in command
    assert "--sase-detect-global-leaks" in command
    assert "--sase-fail-on-global-leaks" in command

    health_request = json.loads(str(observed["health_request"]))
    assert health_request["mode"] == "cost"
    assert observed["timings_request"] is None

    cost_request = json.loads(str(observed["cost_request"]))
    assert cost_request["mode"] == "cost"
    assert cost_request["worker_count"] == 2
    assert Path(cost_request["directory"]).name == "cost"


def test_main_cost_mode_loads_global_state_detector_without_selector(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(tmp_path / "scratch"))
    monkeypatch.setenv("SASE_TEST_GATE_DIR", str(tmp_path / "gate"))
    monkeypatch.setattr(runner, "_parallel_worker_grant", lambda: (2, None))
    observed: dict[str, object] = {}

    class ExecCalled(Exception):
        pass

    def _execv(_executable: str, command: list[str]) -> None:
        observed["command"] = command
        raise ExecCalled

    monkeypatch.setattr(runner.os, "execv", _execv)

    with pytest.raises(ExecCalled):
        runner.main(["cost"])

    command = observed["command"]
    assert isinstance(command, list)
    leak_plugin_index = command.index(runner.GLOBAL_STATE_LEAK_PLUGIN_MODULE)
    assert command[leak_plugin_index - 1] == "-p"
    assert "--sase-detect-global-leaks" in command
    assert "--sase-fail-on-global-leaks" in command
    assert [
        "-m",
        runner.FAST_MARKER_EXPRESSION,
    ] in [command[index : index + 2] for index in range(len(command) - 1)]


def test_main_ace_page_group_isolation_uses_manifest_without_recorders(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = load_run_pytest()
    test_path = tmp_path / "tests/ace/tui/widgets/test_example.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_example(): pass\n", encoding="utf-8")
    manifest = tmp_path / "manifest.txt"
    manifest.write_text(
        "tests/ace/tui/widgets/test_example.py\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(runner, "ACE_PAGE_GROUP_MANIFEST", Path("manifest.txt"))
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(tmp_path / "scratch"))
    monkeypatch.setattr(runner, "_parallel_worker_grant", lambda: (2, None))
    monkeypatch.delenv(runner.RECORD_ENV, raising=False)
    monkeypatch.delenv(runner.TIMINGS_RECORD_ENV, raising=False)
    monkeypatch.delenv(runner.TEST_COST_RECORD_ENV, raising=False)
    observed: dict[str, object] = {}

    class ExecCalled(Exception):
        pass

    def _execv(_executable: str, command: list[str]) -> None:
        observed["command"] = command
        observed["isolation"] = runner.os.environ.get(
            runner.ACE_PAGE_GROUP_ISOLATION_ENV
        )
        observed["health_request"] = runner.os.environ.get(runner.RECORD_ENV)
        observed["timings_request"] = runner.os.environ.get(runner.TIMINGS_RECORD_ENV)
        observed["cost_request"] = runner.os.environ.get(runner.TEST_COST_RECORD_ENV)
        raise ExecCalled

    monkeypatch.setattr(runner.os, "execv", _execv)

    with pytest.raises(ExecCalled):
        runner.main([runner.ACE_PAGE_GROUP_ISOLATION_MODE])

    command = observed["command"]
    assert isinstance(command, list)
    assert command[-3:] == [
        "-m",
        runner.FAST_MARKER_EXPRESSION,
        "tests/ace/tui/widgets/test_example.py",
    ]
    assert runner.HEALTH_PLUGIN_MODULE not in command
    assert runner.TIMINGS_PLUGIN_MODULE not in command
    assert runner.TEST_COST_PLUGIN_MODULE not in command
    assert observed["isolation"] == "1"
    assert observed["health_request"] is None
    assert observed["timings_request"] is None
    assert observed["cost_request"] is None


def test_main_ace_page_group_isolation_rejects_extra_pytest_args(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = load_run_pytest()

    result = runner.main([runner.ACE_PAGE_GROUP_ISOLATION_MODE, "-k", "one"])

    assert result == int(pytest.ExitCode.USAGE_ERROR)
    assert "runs its manifest exactly" in capsys.readouterr().err
