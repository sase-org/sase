from __future__ import annotations

import hashlib
import importlib.util
import os
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_run_pytest() -> ModuleType:
    loader = SourceFileLoader("run_pytest_tool", str(ROOT / "tools" / "run_pytest"))
    spec = importlib.util.spec_from_file_location(
        "run_pytest_tool", ROOT / "tools" / "run_pytest", loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalizes_invocation_relative_file_selector() -> None:
    runner = _load_run_pytest()

    result = runner._normalize_args(["test_repeat_launcher.py"], ROOT / "tests")

    assert result == ["tests/test_repeat_launcher.py"]


def test_normalizes_invocation_relative_node_selector() -> None:
    runner = _load_run_pytest()

    result = runner._normalize_args(
        [
            "test_repeat_launcher.py::TestExtractRepeatAndName::test_parses_repeat_and_name"
        ],
        ROOT / "tests",
    )

    assert result == [
        "tests/test_repeat_launcher.py::TestExtractRepeatAndName::test_parses_repeat_and_name"
    ]


def test_preserves_repo_relative_selector() -> None:
    runner = _load_run_pytest()

    result = runner._normalize_args(["tests/test_repeat_launcher.py"], ROOT / "tests")

    assert result == ["tests/test_repeat_launcher.py"]


def test_strips_just_separator_and_preserves_keyword_expression() -> None:
    runner = _load_run_pytest()

    result = runner._normalize_args(
        ["--", "-k", "test_repeat_launcher.py", "test_repeat_launcher.py"],
        ROOT / "tests",
    )

    assert result == [
        "-k",
        "test_repeat_launcher.py",
        "tests/test_repeat_launcher.py",
    ]


def test_visual_mode_selects_visual_marker() -> None:
    runner = _load_run_pytest()

    result = runner._pytest_command("visual", ["tests/ace/tui/visual"])

    assert result[0:3] == [runner.sys.executable, "-m", "pytest"]
    assert result[-3:] == [
        "-m",
        runner.VISUAL_MARKER_EXPRESSION,
        "tests/ace/tui/visual",
    ]


def test_fast_mode_selects_not_slow_and_not_visual_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_run_pytest()
    monkeypatch.delenv(runner.PYTEST_DIST_ENV, raising=False)

    result = runner._pytest_command("fast", [])

    assert "-n" in result
    assert "--dist=worksteal" in result
    assert result[-2:] == ["-m", runner.FAST_MARKER_EXPRESSION]
    assert result[-1] == "not slow and not visual"


def test_parallel_grant_uses_actual_lease_grant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _load_run_pytest()
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    events: list[object] = []

    class FakeLease:
        def __init__(self, **kwargs: object) -> None:
            events.append(("init", kwargs))

        def acquire(self, floor: int, ceiling: int, *, exact: bool) -> int:
            events.append(("acquire", floor, ceiling, exact))
            return 7

        def make_inheritable(self) -> None:
            events.append("inheritable")

    monkeypatch.setattr(runner, "WorkerTokenLease", FakeLease)
    monkeypatch.setattr(runner, "configured_token_budget", lambda: (12, False))
    monkeypatch.setattr(runner, "automatic_worker_range", lambda _budget: (2, 9))
    monkeypatch.setattr(runner, "gate_directory", lambda: tmp_path)
    monkeypatch.setattr(runner, "gate_timeout", lambda: 3.0)

    granted, lease = runner._parallel_worker_grant()

    assert granted == 7
    assert lease is not None
    assert events == [
        (
            "init",
            {
                "directory": tmp_path,
                "budget": 12,
                "timeout": 3.0,
                "capacity_is_explicit": False,
                "governed": True,
            },
        ),
        ("acquire", 2, 9, False),
        "inheritable",
    ]


def test_exact_worker_override_requests_exact_governed_capacity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _load_run_pytest()
    monkeypatch.setenv("SASE_PYTEST_WORKERS", "6")
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    acquisition: list[tuple[int, int, bool]] = []

    class FakeLease:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def acquire(self, floor: int, ceiling: int, *, exact: bool) -> int:
            acquisition.append((floor, ceiling, exact))
            return 6

        def make_inheritable(self) -> None:
            pass

    monkeypatch.setattr(runner, "WorkerTokenLease", FakeLease)
    monkeypatch.setattr(runner, "configured_token_budget", lambda: (8, True))
    monkeypatch.setattr(runner, "gate_directory", lambda: tmp_path)
    monkeypatch.setattr(runner, "gate_timeout", lambda: 1.0)

    granted, lease = runner._parallel_worker_grant()

    assert granted == 6
    assert lease is not None
    assert acquisition == [(6, 6, True)]


@pytest.mark.parametrize("invalid", ["", "0", "-1", "many"])
def test_worker_override_must_be_positive(
    monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    runner = _load_run_pytest()
    monkeypatch.setenv("SASE_PYTEST_WORKERS", invalid)

    with pytest.raises(pytest.UsageError, match="SASE_PYTEST_WORKERS"):
        runner._parallel_worker_grant()


def test_disabled_gate_skips_acquisition(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_run_pytest()
    monkeypatch.setenv("SASE_TEST_GATE_DISABLED", "1")
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    monkeypatch.setattr(runner, "configured_token_budget", lambda: (8, True))
    monkeypatch.setattr(runner, "automatic_worker_range", lambda _budget: (2, 5))

    assert runner._parallel_worker_grant() == (5, None)


def test_command_uses_granted_worker_count_and_worksteal_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_run_pytest()
    monkeypatch.delenv(runner.PYTEST_DIST_ENV, raising=False)

    result = runner._pytest_command("fast", [], worker_count=7)

    assert result[3:6] == ["-n", "7", "--dist=worksteal"]


def test_loadfile_distribution_environment_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_DIST_ENV, "loadfile")

    result = runner._pytest_command("fast", [], worker_count=7)

    assert result[3:6] == ["-n", "7", "--dist=loadfile"]


@pytest.mark.parametrize("invalid", ["", "load", "work-steal", "each"])
def test_distribution_override_rejects_unsupported_modes(
    monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    runner = _load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_DIST_ENV, invalid)

    with pytest.raises(
        pytest.UsageError,
        match=r"SASE_PYTEST_DIST must be one of: loadfile, worksteal",
    ):
        runner._configured_distribution_mode()


def test_rejects_xdist_count_that_could_bypass_grant() -> None:
    runner = _load_run_pytest()

    with pytest.raises(pytest.UsageError, match="SASE_PYTEST_WORKERS"):
        runner._reject_numprocesses_args(["tests", "-n", "12"])


def test_inline_snapshot_fix_disables_default_xdist() -> None:
    runner = _load_run_pytest()

    result = runner._pytest_command(
        "fast", ["--inline-snapshot=fix", "tests/test_run_pytest_tool.py"]
    )

    assert "-n" not in result
    assert not any(arg.startswith("--dist") for arg in result)
    assert result[-2:] == ["--inline-snapshot=fix", "tests/test_run_pytest_tool.py"]


def test_inline_snapshot_separate_value_disables_default_xdist() -> None:
    runner = _load_run_pytest()

    result = runner._pytest_command(
        "fast", ["--inline-snapshot", "short-report", "tests/test_run_pytest_tool.py"]
    )

    assert "-n" not in result
    assert not any(arg.startswith("--dist") for arg in result)


def test_inline_snapshot_disable_preserves_default_xdist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_run_pytest()
    monkeypatch.delenv(runner.PYTEST_DIST_ENV, raising=False)

    result = runner._pytest_command(
        "fast", ["--inline-snapshot=disable", "tests/test_run_pytest_tool.py"]
    )

    assert "-n" in result
    assert "--dist=worksteal" in result


def test_inline_snapshot_fix_shortcut_disables_default_xdist() -> None:
    runner = _load_run_pytest()

    result = runner._pytest_command("fast", ["--fix", "tests/test_run_pytest_tool.py"])

    assert "-n" not in result
    assert not any(arg.startswith("--dist") for arg in result)


def test_slow_mode_selects_slow_marker() -> None:
    runner = _load_run_pytest()

    result = runner._pytest_command("slow", ["tests/perf"])

    assert result[-3:] == ["-m", runner.SLOW_MARKER_EXPRESSION, "tests/perf"]


def test_terminal_smoke_mode_selects_marker_and_stays_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_DIST_ENV, "invalid-but-unused")

    result = runner._pytest_command(
        "terminal-smoke", ["tests/ace/tui/terminal_smoke"], worker_count=7
    )

    assert "-n" not in result
    assert not any(arg.startswith("--dist") for arg in result)
    assert result[-3:] == [
        "-m",
        runner.TERMINAL_SMOKE_MARKER_EXPRESSION,
        "tests/ace/tui/terminal_smoke",
    ]


def test_cov_mode_excludes_visual_tests_matching_dedicated_visual_test_job() -> None:
    runner = _load_run_pytest()

    result = runner._pytest_command("cov", [])

    assert [
        "-m",
        runner.FAST_MARKER_EXPRESSION,
    ] in [result[index : index + 2] for index in range(len(result) - 1)]
    assert "--cov=src/sase" in result


def test_visual_flag_selects_visual_mode() -> None:
    runner = _load_run_pytest()

    mode, args = runner._resolve_mode_and_args(
        "fast", ["--visual", "-k", "axe", "tests/ace/tui/visual"]
    )

    assert mode == "visual"
    assert args == ["-k", "axe", "tests/ace/tui/visual"]


def test_sanitizes_commit_workflow_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_run_pytest()
    monkeypatch.setenv("SASE_COMMIT_METHOD", "create_pull_request")
    monkeypatch.setenv("SASE_COMMIT_METHOD_ALLOW_OVERRIDE", "1")
    monkeypatch.setenv("SASE_PR_NAME", "fix_just_tests")
    monkeypatch.setenv("SASE_PR_STATUS", "draft")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent")

    runner._sanitize_pytest_environment()

    for key in runner.PYTEST_ENV_UNSET_KEYS:
        assert key not in runner.os.environ
    assert runner.os.environ["SASE_AGENT_NAME"] == "agent"


def test_configured_pytest_tmpdir_defaults_to_disk_backed_workspace_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_run_pytest()
    monkeypatch.delenv(runner.PYTEST_TMPDIR_ENV, raising=False)

    scratch_root = runner._configured_pytest_tmpdir()
    workspace_key = hashlib.sha256(os.fsencode(ROOT)).hexdigest()[:8]

    assert scratch_root == Path("/var/tmp") / f"sase-{workspace_key}"
    assert ROOT not in scratch_root.parents


def test_prepare_pytest_tmpdir_honors_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _load_run_pytest()
    scratch_root = tmp_path / "pytest scratch"
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(scratch_root))

    assert runner._prepare_pytest_tmpdir() == scratch_root
    assert scratch_root.is_dir()
    assert runner.os.environ["TMPDIR"] == str(scratch_root)
    assert runner.os.environ[runner.PYTEST_TMP_REDIRECTED_ENV] == "1"


def test_configured_pytest_tmpdir_resolves_relative_override_from_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, "build/pytest-scratch")

    assert runner._configured_pytest_tmpdir() == ROOT / "build" / "pytest-scratch"


def test_configured_pytest_tmpdir_rejects_empty_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, "")

    with pytest.raises(pytest.UsageError, match="must not be empty"):
        runner._configured_pytest_tmpdir()


@pytest.mark.parametrize(
    "unsafe_root",
    [Path("/"), Path("/tmp"), Path("/var/tmp"), ROOT, ROOT.parent],
)
def test_configured_pytest_tmpdir_rejects_broad_cleanup_targets(
    monkeypatch: pytest.MonkeyPatch, unsafe_root: Path
) -> None:
    runner = _load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(unsafe_root))

    with pytest.raises(pytest.UsageError, match="dedicated scratch directory"):
        runner._configured_pytest_tmpdir()


def test_reaper_removes_only_stale_pytest_run_directories(tmp_path: Path) -> None:
    runner = _load_run_pytest()
    user_root = tmp_path / "pytest-of-user"
    stale_run = user_root / "pytest-1"
    fresh_run = user_root / "pytest-2"
    stale_garbage = user_root / "garbage-deadbeef"
    unrelated = user_root / "other"
    for directory in (stale_run, fresh_run, stale_garbage, unrelated):
        directory.mkdir(parents=True)

    now = 100_000.0
    stale_time = now - runner.PYTEST_TMP_REAP_HORIZON_SECONDS - 1
    stale_lock = stale_run / ".lock"
    stale_lock.touch()
    os.utime(stale_lock, (stale_time, stale_time))
    os.utime(stale_run, (stale_time, stale_time))
    os.utime(stale_garbage, (stale_time, stale_time))
    os.utime(unrelated, (stale_time, stale_time))
    os.utime(fresh_run, (now, now))

    runner._reap_stale_pytest_runs(tmp_path, now=now)

    assert not stale_run.exists()
    assert not stale_garbage.exists()
    assert fresh_run.is_dir()
    assert unrelated.is_dir()


def test_reaper_removes_stale_top_level_scratch_entries(tmp_path: Path) -> None:
    runner = _load_run_pytest()
    stale_inline_snapshot = tmp_path / "inline-snapshot-abc"
    stale_artifact_tree = tmp_path / "tmpab12cd34" / "artifacts"
    fresh_inline_snapshot = tmp_path / "inline-snapshot-def"
    locked_run = tmp_path / "pytest-1"
    skipped_symlink = tmp_path / "inline-snapshot-link"
    for directory in (
        stale_inline_snapshot,
        stale_artifact_tree,
        fresh_inline_snapshot,
        locked_run,
    ):
        directory.mkdir(parents=True)
    lock_path = locked_run / ".lock"
    lock_path.touch()
    skipped_symlink.symlink_to(fresh_inline_snapshot, target_is_directory=True)

    now = 100_000.0
    stale_time = now - runner.PYTEST_TMP_REAP_HORIZON_SECONDS - 1
    os.utime(stale_inline_snapshot, (stale_time, stale_time))
    os.utime(stale_artifact_tree.parent, (stale_time, stale_time))
    os.utime(fresh_inline_snapshot, (now, now))
    os.utime(locked_run, (stale_time, stale_time))
    os.utime(lock_path, (now, now))

    runner._reap_stale_pytest_runs(tmp_path, now=now)

    assert not stale_inline_snapshot.exists()
    assert not stale_artifact_tree.parent.exists()
    assert fresh_inline_snapshot.is_dir()
    assert locked_run.is_dir()
    assert skipped_symlink.is_symlink()


def test_reaper_preserves_run_with_fresh_lock(tmp_path: Path) -> None:
    runner = _load_run_pytest()
    run_directory = tmp_path / "pytest-of-user" / "pytest-1"
    run_directory.mkdir(parents=True)
    lock_path = run_directory / ".lock"
    lock_path.touch()

    now = 100_000.0
    stale_time = now - runner.PYTEST_TMP_REAP_HORIZON_SECONDS - 1
    os.utime(run_directory, (stale_time, stale_time))
    os.utime(lock_path, (now, now))

    runner._reap_stale_pytest_runs(tmp_path, now=now)

    assert run_directory.is_dir()


def test_reaper_ignores_cleanup_races(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _load_run_pytest()
    run_directory = tmp_path / "pytest-of-user" / "pytest-1"
    run_directory.mkdir(parents=True)
    now = 100_000.0
    stale_time = now - runner.PYTEST_TMP_REAP_HORIZON_SECONDS - 1
    os.utime(run_directory, (stale_time, stale_time))
    monkeypatch.setattr(
        runner.shutil,
        "rmtree",
        lambda _path: (_ for _ in ()).throw(OSError("lost cleanup race")),
    )

    runner._reap_stale_pytest_runs(tmp_path, now=now)

    assert run_directory.is_dir()


def test_main_prepares_governed_environment_and_descriptors_before_exec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _load_run_pytest()
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
        runner.main(["fast", "tests/test_run_pytest_tool.py"])

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
    runner = _load_run_pytest()
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
                "tests/test_run_pytest_tool.py",
            ]
        )

    assert "-n" not in observed["command"]
    assert not any(arg.startswith("--dist") for arg in observed["command"])


def test_main_terminal_smoke_mode_redirects_and_never_acquires(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _load_run_pytest()
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
    runner = _load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_DIST_ENV, "loadscope")

    def _unexpected_grant() -> None:
        raise AssertionError("invalid distribution attempted token acquisition")

    monkeypatch.setattr(runner, "_parallel_worker_grant", _unexpected_grant)

    result = runner.main(["fast", "tests/test_run_pytest_tool.py"])

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
