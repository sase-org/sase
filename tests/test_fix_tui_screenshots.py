"""CLI, environment, and lock tests for ``tools/fix_tui_screenshots``."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from tests._fix_tui_screenshots_helpers import (
    ACE_NODE,
    PAGER_NODE,
    FakeRunner,
    ScriptedCapture,
    commit_all,
    git_index,
    init_repo,
    make_png,
    silent_hooks,
    write_golden,
)
from tests._legacy_visual_update import (
    LEGACY_VISUAL_UPDATE_OPTION,
    reject_legacy_visual_update_option,
)
from tests.ace.tui.visual._visual_maintenance_run import _default_is_ci
from tests.ace.tui.visual._visual_maintenance import (
    EXIT_DRIFT,
    EXIT_FAILURE,
    EXIT_SUCCESS,
    EXIT_USAGE,
    MaintenanceHooks,
    UsageError,
    build_parser,
    build_run_pytest_command,
    main,
    parse_command,
    resolve_scope,
    validate_pytest_args,
)


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "fix_tui_screenshots"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("fix_tui_screenshots_tool", str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "fix_tui_screenshots_tool", TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _OptionConfig:
    def __init__(self, enabled: bool) -> None:
        self._enabled = enabled

    def getoption(self, name: str, default: bool = False) -> bool:
        if name == LEGACY_VISUAL_UPDATE_OPTION:
            return self._enabled
        return default


def test_tool_script_is_executable() -> None:
    assert TOOL_PATH.exists()
    assert TOOL_PATH.stat().st_mode & 0o111


def test_help_lists_sorted_check_flag_and_exit_codes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_command(["-h"])
    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "-c, --check" in output
    assert "Exit codes:" in output
    assert str(EXIT_SUCCESS) in output
    assert "1  check mode" in output or "1  check" in output
    assert str(EXIT_USAGE) in output
    assert str(EXIT_FAILURE) in output
    assert "just" in output


def test_check_short_alias_and_double_dash_selectors() -> None:
    request = parse_command(
        ["-c", "--", "tests/ace/tui/visual/test_example.py", "-k", "example"]
    )
    assert request.check is True
    assert request.scope == "targeted"
    assert "cli_selectors" in request.scope_reasons
    assert request.pytest_args == (
        "tests/ace/tui/visual/test_example.py",
        "-k",
        "example",
    )


def test_full_scope_without_selectors() -> None:
    request = parse_command([])
    assert request.check is False
    assert request.scope == "full"
    assert request.scope_reasons == ()


def test_pytest_addopts_keyword_makes_targeted_scope() -> None:
    request = parse_command([], environ={"PYTEST_ADDOPTS": "-k snapshot"})
    assert request.scope == "targeted"
    assert "PYTEST_ADDOPTS" in request.scope_reasons


def test_rejects_legacy_update_flag() -> None:
    with pytest.raises(UsageError, match="just fix-tui-screenshots"):
        parse_command(["--", "--sase-update-visual-snapshots"])


def test_pytest_rejects_legacy_visual_update_option() -> None:
    with pytest.raises(pytest.UsageError, match="just fix-tui-screenshots"):
        reject_legacy_visual_update_option(_OptionConfig(True))


def test_pytest_allows_visual_runs_without_legacy_update_option() -> None:
    reject_legacy_visual_update_option(_OptionConfig(False))


def test_rejects_capture_dir_override() -> None:
    with pytest.raises(UsageError, match="maintenance runner owns"):
        parse_command(["--", "--sase-visual-capture-dir", "/tmp/other"])


def test_rejects_disabled_capture_plugin() -> None:
    with pytest.raises(UsageError, match="disable the visual capture plugin"):
        parse_command(["--", "-p", "no:sase-visual-capture"])


def test_rejects_marker_override() -> None:
    with pytest.raises(UsageError, match="replace the visual marker"):
        parse_command(["--", "-m", "not visual"])


def test_validate_pytest_args_accepts_keyword_expression() -> None:
    validate_pytest_args(["-k", "login", "tests/ace/tui/visual/test_a.py"])


def test_resolve_scope_treats_last_failed_as_targeted() -> None:
    scope, reasons = resolve_scope(["--lf"])
    assert scope == "targeted"
    assert reasons == ("cli_selectors",)


def test_parser_only_exposes_check_and_help() -> None:
    parser = build_parser()
    option_strings = [
        flag
        for action in parser._actions
        for flag in action.option_strings
        if flag.startswith("--")
    ]
    assert option_strings == ["--help", "--check"] or set(option_strings) == {
        "--help",
        "--check",
    }


def test_build_run_pytest_command_forwards_capture_options(tmp_path: Path) -> None:
    command = build_run_pytest_command(
        repo_root=tmp_path,
        capture_dir=tmp_path / "capture",
        run_id="run1",
        scope="targeted",
        pytest_args=("tests/ace/tui/visual/test_a.py", "-k", "a"),
        ace_root=tmp_path / "tests/ace/tui/visual/snapshots/png",
        pager_root=tmp_path / "tests/pager/visual/snapshots/png",
    )
    assert command[:3] == [
        sys.executable,
        str(tmp_path / "tools" / "run_pytest"),
        "visual",
    ]
    assert "--sase-visual-capture-dir" in command
    assert "--sase-visual-capture-scope" in command
    assert "targeted" in command
    assert command[-3:] == ["tests/ace/tui/visual/test_a.py", "-k", "a"]


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, False),
        ({"CI": "true"}, True),
        ({"GITHUB_ACTIONS": "true"}, True),
        ({"CI": "true", "SASE_AGENT": "1"}, False),
        ({"CI": "true", "SASE_MONITOR_ID": "fhsavmh28p9v"}, False),
        ({"GITHUB_ACTIONS": "true", "SASE_AGENT": "1"}, True),
        ({"GITHUB_ACTIONS": "true", "SASE_MONITOR_ID": "fhsavmh28p9v"}, True),
        ({"CI": "true", "GITHUB_ACTIONS": "true", "SASE_AGENT": "1"}, True),
    ],
)
def test_default_ci_detection_ignores_sase_agent_ci_flag(
    environ: dict[str, str],
    expected: bool,
) -> None:
    assert _default_is_ci(environ) is expected


def test_update_refuses_ci_environment(tmp_path: Path) -> None:
    init_repo(tmp_path)
    runner = FakeRunner(captures=[], repo_root=tmp_path)
    code = main(
        [],
        repo_root=tmp_path,
        hooks=silent_hooks(runner, ci=True),
        environ={"CI": "true"},
    )
    assert code == EXIT_USAGE
    assert runner.calls == []


def test_update_allows_sase_agent_workspace_ci_flag(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    write_golden(tmp_path, "ace", "keep.png", red)
    write_golden(tmp_path, "pager", "keep.png", red)
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "keep", "ace", red),
            ScriptedCapture(PAGER_NODE, "keep", "pager", red),
        ],
        repo_root=tmp_path,
    )
    code = main(
        [],
        repo_root=tmp_path,
        hooks=MaintenanceHooks(
            preflight=lambda _update: None,
            run_pytest=runner,
            renderer_identity=lambda: {"packages": {}, "fonts": {}},
        ),
        environ={"CI": "true", "SASE_AGENT": "1"},
    )
    assert code == EXIT_SUCCESS
    assert runner.calls


def test_update_allows_sase_monitor_ci_flag(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    write_golden(tmp_path, "ace", "keep.png", red)
    write_golden(tmp_path, "pager", "keep.png", red)
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "keep", "ace", red),
            ScriptedCapture(PAGER_NODE, "keep", "pager", red),
        ],
        repo_root=tmp_path,
    )
    code = main(
        [],
        repo_root=tmp_path,
        hooks=MaintenanceHooks(
            preflight=lambda _update: None,
            run_pytest=runner,
            renderer_identity=lambda: {"packages": {}, "fonts": {}},
        ),
        environ={"CI": "true", "SASE_MONITOR_ID": "fhsavmh28p9v"},
    )
    assert code == EXIT_SUCCESS
    assert runner.calls


def test_check_allows_ci_environment(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    write_golden(tmp_path, "ace", "keep.png", red)
    write_golden(tmp_path, "pager", "keep.png", red)
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "keep", "ace", red),
            ScriptedCapture(PAGER_NODE, "keep", "pager", red),
        ],
        repo_root=tmp_path,
    )
    code = main(
        ["--check"],
        repo_root=tmp_path,
        hooks=silent_hooks(runner, ci=True),
        environ={"GITHUB_ACTIONS": "1"},
    )
    assert code == EXIT_SUCCESS
    assert runner.calls


def test_update_refuses_non_linux_platform(tmp_path: Path) -> None:
    init_repo(tmp_path)
    hooks = silent_hooks(FakeRunner(captures=[], repo_root=tmp_path))

    def refuse_update(update: bool) -> None:
        if update:
            raise UsageError("goldens must be generated on Linux")

    hooks = MaintenanceHooks(
        preflight=refuse_update,
        run_pytest=hooks.run_pytest,
        is_ci=hooks.is_ci,
        renderer_identity=hooks.renderer_identity,
    )
    code = main([], repo_root=tmp_path, hooks=hooks, environ={})
    assert code == EXIT_USAGE


def test_renderer_preflight_failure_is_usage(tmp_path: Path) -> None:
    init_repo(tmp_path)

    def boom(_update: bool) -> None:
        raise UsageError("renderer environment mismatch")

    hooks = MaintenanceHooks(
        preflight=boom,
        run_pytest=FakeRunner(captures=[], repo_root=tmp_path),
        is_ci=lambda _env: False,
    )
    code = main(["--check"], repo_root=tmp_path, hooks=hooks, environ={})
    assert code == EXIT_USAGE


def test_overlapping_run_refuses_without_overwriting_scratch(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    write_golden(tmp_path, "ace", "keep.png", red)
    write_golden(tmp_path, "pager", "keep.png", red)
    commit_all(tmp_path)
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import fcntl, os, sys, time\n"
                "from pathlib import Path\n"
                "path = Path(sys.argv[1])\n"
                "path.parent.mkdir(parents=True, exist_ok=True)\n"
                "fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)\n"
                "fcntl.flock(fd, fcntl.LOCK_EX)\n"
                "path.write_text('pid=holder\\n', encoding='utf-8')\n"
                "print('locked', flush=True)\n"
                "time.sleep(30)\n"
            ),
            str(tmp_path / ".pytest_cache/sase-visual/maintenance.lock"),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        line = holder.stdout.readline()
        assert "locked" in line
        runner = FakeRunner(
            captures=[
                ScriptedCapture(ACE_NODE, "keep", "ace", red),
                ScriptedCapture(PAGER_NODE, "keep", "pager", red),
            ],
            repo_root=tmp_path,
        )
        code = main(
            ["--check"],
            repo_root=tmp_path,
            hooks=silent_hooks(runner),
            environ={},
        )
        assert code == EXIT_USAGE
        assert runner.calls == []
    finally:
        holder.terminate()
        holder.wait(timeout=10)


def test_check_mode_leaves_git_index_and_mtimes_on_drift(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    ace = write_golden(tmp_path, "ace", "shot.png", red)
    pager = write_golden(tmp_path, "pager", "shot.png", red)
    commit_all(tmp_path)
    before_index = git_index(tmp_path)
    ace_mtime = ace.stat().st_mtime_ns
    pager_mtime = pager.stat().st_mtime_ns
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", blue),
            ScriptedCapture(PAGER_NODE, "shot", "pager", red),
        ],
        repo_root=tmp_path,
    )
    code = main(
        ["--check"],
        repo_root=tmp_path,
        hooks=silent_hooks(runner),
        environ={},
    )
    assert code == EXIT_DRIFT
    assert ace.read_bytes() == red
    assert pager.read_bytes() == red
    assert ace.stat().st_mtime_ns == ace_mtime
    assert pager.stat().st_mtime_ns == pager_mtime
    assert git_index(tmp_path) == before_index
    manifests = sorted(
        (tmp_path / ".pytest_cache/sase-visual/runs").glob("*/manifest.json"),
        key=lambda path: path.stat().st_mtime_ns,
    )
    manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
    assert manifest["status"] == "drift"
    assert manifest["child_exit_code"] == 0
    assert any(item["kind"] == "updated" for item in manifest["changes"])


def test_tool_main_is_wired() -> None:
    module = _load_tool()
    assert callable(module.main)
