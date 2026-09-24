"""Phase monitor-wrap: a monitor's command runs inside ``sase tool run``.

Covers the monitor-wrapping policy table: host-owned ``execution_argv``
launches stay byte-identical, an exact catalog match at the monitor cwd's
project root upgrades to a named run, other verify-profile commands wrap
ad-hoc in the proc argv only, and ``monitor_command`` /
``monitor_execution_argv`` stay byte-identical so ``-f`` host completion
keeps resolving the raw command. When a wrap produces a ToolRun, monitor
start reserves it and the proc runs the claiming ``_adopt`` worker instead
(``test_monitor_tool_handoff.py`` covers the reservation contract and the
E1.5 fallback when reservation fails).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

import pytest

from sase.monitor.models import MonitorRecord
from sase.monitor.proc_adapter import _compile_monitor_argv
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.monitor.tool_wrap import (
    format_unwrapped_log_line,
    resolve_monitor_tool_wrap,
)
from sase.procs.store import get_proc
from sase.running_field import WorkspaceClaim

from ._fixtures import make_starter_agent, wait_for_done, write_project_file

SANDBOX_CATALOG = """\
tools:
  check:
    argv: ["true"]
    description: sandbox verify probe
    stages: none
    inputs: []
    env: []
    args: deny
    fingerprint:
      repos: []
      toolchain: {}
  echoargs:
    argv: ["printf"]
    description: sandbox args-allow probe
    stages: none
    inputs: []
    env: []
    args: allow
    fingerprint:
      repos: []
      toolchain: {}
"""


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_PROC_ID",
        "SASE_TOOL_BYPASS",
        "SASE_TOOL_NAME",
        "SASE_TOOL_PROJECT_ROOT",
        "SASE_TOOL_RUN_AGENT",
        "SASE_TOOL_RUN_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    from sase.config.core import clear_config_cache

    clear_config_cache()


def _sase_argv() -> list[str]:
    return [sys.executable, "-m", "sase"]


def _sandbox_project(tmp_path: Path, name: str = "proj") -> Path:
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    sase_dir = root / "sase"
    sase_dir.mkdir(parents=True)
    (sase_dir / "sase.yml").write_text(SANDBOX_CATALOG, encoding="utf-8")
    return root


def test_epic_execution_argv_is_byte_identical() -> None:
    execution = [sys.executable, "bootstrap.py", "--", "sase", "bead", "work"]
    argv, reason = resolve_monitor_tool_wrap(
        "sase bead work plan.md",
        execution,
        "verify",
        "/repo",
        "verify",
        env={},
    )
    assert argv == execution
    assert reason is None


def test_already_wrapped_commands_are_untouched() -> None:
    for command in (
        "sase tool run check",
        "sase tool run -- /bin/sh -c 'just check'",
        f"{sys.executable} -m sase tool run check",
        "/usr/bin/sase tool run check-full",
    ):
        argv, reason = resolve_monitor_tool_wrap(
            command, None, "verify", "/repo", "verify", env={}
        )
        assert argv == _compile_monitor_argv(command)
        assert reason is None


def test_tool_run_without_sase_is_not_a_wrapped_shape(tmp_path: Path) -> None:
    # `tool run` with no `sase` in front is an ordinary command: with no
    # catalog entry it wraps ad-hoc under a verify profile.
    root = _sandbox_project(tmp_path)
    argv, reason = resolve_monitor_tool_wrap(
        "tool run check", None, "verify", str(root), "verify", env={}
    )
    assert argv == [
        *_sase_argv(),
        "tool",
        "run",
        "--",
        "/bin/sh",
        "-c",
        "tool run check",
    ]
    assert reason is None


def test_named_upgrade_matches_catalog_at_monitor_cwd(tmp_path: Path) -> None:
    root = _sandbox_project(tmp_path)
    argv, reason = resolve_monitor_tool_wrap(
        "true", None, "verify", str(root), "verify", env={}
    )
    assert argv == [*_sase_argv(), "tool", "run", "check"]
    assert reason is None


def test_extra_args_match_only_with_args_allow(tmp_path: Path) -> None:
    root = _sandbox_project(tmp_path)
    argv, reason = resolve_monitor_tool_wrap(
        "printf %s hi", None, "verify", str(root), "verify", env={}
    )
    assert argv == [*_sase_argv(), "tool", "run", "echoargs", "--", "%s", "hi"]
    assert reason is None

    # `check` denies extra args, so this is not a catalog match: ad-hoc.
    argv, reason = resolve_monitor_tool_wrap(
        "true --extra", None, "verify", str(root), "verify", env={}
    )
    assert argv == [*_sase_argv(), "tool", "run", "--", "/bin/sh", "-c", "true --extra"]
    assert reason is None


def test_named_upgrade_requires_the_catalog_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _sandbox_project(tmp_path)
    subdir = root / "sub"
    subdir.mkdir()
    # The starter's own cwd is irrelevant: resolution uses the monitor's cwd.
    monkeypatch.chdir(tmp_path)
    argv, reason = resolve_monitor_tool_wrap(
        "true", None, "verify", str(subdir), "verify", env={}
    )
    assert argv == [*_sase_argv(), "tool", "run", "--", "/bin/sh", "-c", "true"]
    assert reason is None


def test_shell_operators_block_the_named_upgrade(tmp_path: Path) -> None:
    root = _sandbox_project(tmp_path)
    # `printf` allows extra args, but shell operators keep the whole
    # command inside an ad-hoc `/bin/sh -c`, verbatim.
    command = "printf %s hi; sleep 1"
    argv, reason = resolve_monitor_tool_wrap(
        command, None, "verify", str(root), "verify", env={}
    )
    assert argv == [*_sase_argv(), "tool", "run", "--", "/bin/sh", "-c", command]
    assert reason is None


def test_compound_command_containing_tool_run_outer_wraps(
    tmp_path: Path,
) -> None:
    root = _sandbox_project(tmp_path)
    command = "sase tool run check && echo done"
    argv, reason = resolve_monitor_tool_wrap(
        command, None, "verify", str(root), "verify", env={}
    )
    assert argv == [*_sase_argv(), "tool", "run", "--", "/bin/sh", "-c", command]
    assert reason is None


def test_env_prefix_and_expansion_stay_adhoc(tmp_path: Path) -> None:
    root = _sandbox_project(tmp_path)
    for command in ("FOO=1 printf %s hi", "printf %s *.py", "printf %s $HOME"):
        argv, reason = resolve_monitor_tool_wrap(
            command, None, "verify", str(root), "verify", env={}
        )
        assert argv == [*_sase_argv(), "tool", "run", "--", "/bin/sh", "-c", command]
        assert reason is None


def test_compound_verify_command_becomes_single_adhoc(tmp_path: Path) -> None:
    root = _sandbox_project(tmp_path)
    command = "true && true"
    argv, reason = resolve_monitor_tool_wrap(
        command, None, "verify", str(root), "verify", env={}
    )
    assert argv == [*_sase_argv(), "tool", "run", "--", "/bin/sh", "-c", command]
    assert reason is None


def test_no_profile_untouched_under_verify_wrapped_under_all(
    tmp_path: Path,
) -> None:
    root = _sandbox_project(tmp_path)
    argv, reason = resolve_monitor_tool_wrap(
        "sleep 30", None, None, str(root), "verify", env={}
    )
    assert argv == _compile_monitor_argv("sleep 30")
    assert reason == "no profile (monitor.tool_wrap is verify)"

    argv, reason = resolve_monitor_tool_wrap(
        "sleep 30", None, None, str(root), "all", env={}
    )
    assert argv == [*_sase_argv(), "tool", "run", "--", "/bin/sh", "-c", "sleep 30"]
    assert reason is None


def test_off_wraps_nothing(tmp_path: Path) -> None:
    root = _sandbox_project(tmp_path)
    argv, reason = resolve_monitor_tool_wrap(
        "true", None, "verify", str(root), "off", env={}
    )
    assert argv == _compile_monitor_argv("true")
    assert reason == "monitor.tool_wrap is off"


def test_bypass_leaves_raw(tmp_path: Path) -> None:
    root = _sandbox_project(tmp_path)
    argv, reason = resolve_monitor_tool_wrap(
        "true",
        None,
        "verify",
        str(root),
        "verify",
        env={"SASE_TOOL_BYPASS": "stale install"},
    )
    assert argv == _compile_monitor_argv("true")
    assert reason == "SASE_TOOL_BYPASS is set"


def test_unknown_tool_wrap_fails_open_to_verify(tmp_path: Path) -> None:
    root = _sandbox_project(tmp_path)
    argv, reason = resolve_monitor_tool_wrap(
        "sleep 30", None, None, str(root), "sometimes", env={}
    )
    assert argv == _compile_monitor_argv("sleep 30")
    assert reason == "no profile (monitor.tool_wrap is verify)"


def test_catalog_failure_leaves_raw_with_reason() -> None:
    def _broken(_cwd: Path | str | None) -> object:
        raise RuntimeError("bindings gone")

    argv, reason = resolve_monitor_tool_wrap(
        "true", None, "verify", "/repo", "verify", env={}, load_catalog=_broken
    )
    assert argv == _compile_monitor_argv("true")
    assert reason == "tool catalog unavailable (bindings gone)"


def test_unwrapped_log_line_is_exactly_one_line() -> None:
    line = format_unwrapped_log_line("monitor.tool_wrap is off")
    assert line == "sase: running unwrapped (monitor.tool_wrap is off)\n"
    assert line.count("\n") == 1


def test_get_monitor_tool_wrap_defaults_and_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.config.core as config_core
    from sase.config._settings import get_monitor_tool_wrap

    monkeypatch.setattr(config_core, "load_merged_config", lambda: {})
    assert get_monitor_tool_wrap() == "verify"
    monkeypatch.setattr(
        config_core, "load_merged_config", lambda: {"monitor": {"tool_wrap": "all"}}
    )
    assert get_monitor_tool_wrap() == "all"
    monkeypatch.setattr(
        config_core, "load_merged_config", lambda: {"monitor": {"tool_wrap": "off"}}
    )
    assert get_monitor_tool_wrap() == "off"
    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {"monitor": {"tool_wrap": "sometimes"}},
    )
    assert get_monitor_tool_wrap() == "verify"
    monkeypatch.setattr(config_core, "load_merged_config", lambda: {"monitor": "nope"})
    assert get_monitor_tool_wrap() == "verify"

    def _broken() -> dict[str, object]:
        raise RuntimeError("config gone")

    monkeypatch.setattr(config_core, "load_merged_config", _broken)
    assert get_monitor_tool_wrap() == "verify"


def _start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    command: str,
    cwd: str,
    profile: str | None = None,
    tool_wrap: str = "verify",
    timeout_seconds: float = 120.0,
    timestamp: str = "20260812120000",
) -> MonitorRecord:
    from sase.monitor import store as store_module

    import sase.monitor.start as start_module

    monkeypatch.setattr(start_module, "get_monitor_tool_wrap", lambda: tool_wrap)
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    make_starter_agent(
        "proj",
        timestamp,
        "acme",
        model="claude-sonnet-5",
        workspace_dir=cwd,
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )

    def live_records(
        project_name: str | None, *, only_monitors: bool = False
    ) -> list[object]:
        from sase.core.paths import sase_projects_dir

        records = []
        for name in [project_name] if project_name else ["proj"]:
            artifacts_root = sase_projects_dir() / name / "artifacts" / "ace-run"
            for meta_path in artifacts_root.glob("*/*/*/agent_meta.json"):
                from ._fixtures import record_from_disk

                record = record_from_disk(meta_path.parent)
                if only_monitors and (
                    record.agent_meta is None
                    or record.agent_meta.agent_session_role != "monitor"
                ):
                    continue
                records.append(record)
        return records

    monkeypatch.setattr(store_module, "project_records", live_records)
    return start_monitor(
        StartMonitorRequest(
            command=command,
            reason="verify wrap",
            timeout_seconds=timeout_seconds,
            cwd=cwd,
            project_name="proj",
            start_status="TESTING",
            stop_status="TESTED",
            lane="acme",
            profile=profile,
        )
    )


def _meta(record: MonitorRecord) -> dict[str, object]:
    meta_path = Path(record.artifacts_dir) / "agent_meta.json"
    loaded: dict[str, object] = json.loads(meta_path.read_text(encoding="utf-8"))
    return loaded


def test_verify_true_becomes_named_check_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.tool_run import tool_run_list

    root = _sandbox_project(tmp_path)
    record = _start(
        tmp_path, monkeypatch, command="true", cwd=str(root), profile="verify"
    )
    assert record.tool_run_id
    proc = get_proc(record.monitor_id)
    assert proc is not None
    assert proc.argv == [*_sase_argv(), "tool", "_adopt", record.tool_run_id]

    meta = _meta(record)
    assert meta["monitor_command"] == "true"
    assert "monitor_execution_argv" not in meta

    done = wait_for_done(record.artifacts_dir)
    assert done["monitor_state"] == "completed"

    runs = tool_run_list({"schema_version": 1, "limit": 10})["runs"]
    assert len(runs) == 1
    run = runs[0]
    assert run.get("run_id") == record.tool_run_id
    assert run.get("tool_name") == "check"
    assert run.get("owner_kind") == "monitor"
    assert run.get("owner_id") == record.monitor_id  # type: ignore[attr-defined]
    # The starter is promoted to an agent session on monitor start; the run records
    # that promoted starter through the SASE_TOOL_RUN_AGENT overlay.
    assert meta["monitor_starter_agent"]
    assert run.get("agent") == meta["monitor_starter_agent"]

    log = Path(record.artifacts_dir) / "live_reply.md"  # type: ignore[attr-defined]
    text = log.read_text(encoding="utf-8", errors="replace")
    assert re.search(r"(?m)^sase tool run [0-9a-f]+$", text)
    assert re.search(r"(?m)^succeeded  exit=0  duration=\d+ms$", text)
    assert "running unwrapped" not in text


def test_verify_compound_becomes_single_adhoc_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.tool_run import tool_run_list, tool_run_show

    root = _sandbox_project(tmp_path)
    command = "true && true"
    record = _start(
        tmp_path, monkeypatch, command=command, cwd=str(root), profile="verify"
    )
    assert record.tool_run_id
    proc = get_proc(record.monitor_id)
    assert proc is not None
    assert proc.argv == [*_sase_argv(), "tool", "_adopt", record.tool_run_id]
    assert _meta(record)["monitor_command"] == command

    done = wait_for_done(record.artifacts_dir)
    assert done["monitor_state"] == "completed"

    runs = tool_run_list({"schema_version": 1, "limit": 10})["runs"]
    assert len(runs) == 1
    assert runs[0].get("run_id") == record.tool_run_id
    assert runs[0].get("owner_kind") == "monitor"
    assert runs[0].get("tool_name") is None
    shown = tool_run_show(record.tool_run_id)["run"]
    assert shown["state"] == "succeeded"
    assert shown["launch_mode"] == "handoff"


def test_no_profile_monitor_runs_raw_with_reason_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.tool_run import tool_run_list

    root = _sandbox_project(tmp_path)
    record = _start(tmp_path, monkeypatch, command="true", cwd=str(root))
    proc = get_proc(record.monitor_id)
    assert proc is not None
    assert proc.argv == ["/bin/sh", "-c", "true"]

    done = wait_for_done(record.artifacts_dir)
    assert done["monitor_state"] == "completed"

    log = Path(record.artifacts_dir) / "live_reply.md"  # type: ignore[attr-defined]
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    unwrapped = [line for line in lines if line.startswith("sase: running unwrapped (")]
    assert unwrapped == [
        "sase: running unwrapped (no profile (monitor.tool_wrap is verify))"
    ]

    assert tool_run_list({"schema_version": 1, "limit": 10})["runs"] == []


def test_off_wraps_nothing_but_logs_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.tool_run import tool_run_list

    root = _sandbox_project(tmp_path)
    record = _start(
        tmp_path,
        monkeypatch,
        command="true",
        cwd=str(root),
        profile="verify",
        tool_wrap="off",
    )
    proc = get_proc(record.monitor_id)
    assert proc is not None
    assert proc.argv == ["/bin/sh", "-c", "true"]

    done = wait_for_done(record.artifacts_dir)
    assert done["monitor_state"] == "completed"

    log = Path(record.artifacts_dir) / "live_reply.md"  # type: ignore[attr-defined]
    text = log.read_text(encoding="utf-8", errors="replace")
    assert "sase: running unwrapped (monitor.tool_wrap is off)\n" in text
    assert tool_run_list({"schema_version": 1, "limit": 10})["runs"] == []


def test_already_wrapped_monitor_is_not_rewrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.tool_run import tool_run_list

    root = _sandbox_project(tmp_path)
    # Spell the wrapper as this interpreter's `sase`, not whatever `sase` is
    # first on PATH: CI does not put the venv's `bin` on PATH.
    command = shlex.join([*_sase_argv(), "tool", "run", "check"])
    record = _start(
        tmp_path,
        monkeypatch,
        command=command,
        cwd=str(root),
        profile="verify",
    )
    # The agent-written wrapper is reserved and run by the worker, not
    # wrapped a second time.
    assert record.tool_run_id
    proc = get_proc(record.monitor_id)
    assert proc is not None
    assert proc.argv == [*_sase_argv(), "tool", "_adopt", record.tool_run_id]

    done = wait_for_done(record.artifacts_dir)
    assert done["monitor_state"] == "completed"

    # One semantic run, not two.
    runs = tool_run_list({"schema_version": 1, "limit": 10})["runs"]
    assert len(runs) == 1
    assert runs[0].get("run_id") == record.tool_run_id
    assert runs[0].get("tool_name") == "check"


def test_completion_argv_still_resolves_the_raw_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.monitor.host_completion_state import _command_argv

    root = _sandbox_project(tmp_path)
    record = _start(
        tmp_path, monkeypatch, command="true", cwd=str(root), profile="verify"
    )
    meta = _meta(record)
    assert meta["monitor_command"] == "true"
    assert "monitor_execution_argv" not in meta
    assert _command_argv(meta) == ["true"]
    wait_for_done(record.artifacts_dir)


def test_auto_evidence_selects_tail_through_wrapper_header_footer(
    tmp_path: Path,
) -> None:
    """Auto evidence extraction still finds the tail under wrapper lines.

    A timeout outcome keeps the log's real tail selectable even though the
    retained log opens with the wrapper's ``sase tool run <id>`` header and
    closes with its completion footer. (Live timeout/failure settlement
    launches a recovery follow-up agent, which has no runner in a sandbox;
    the live header/footer landing is covered by the named-run test above.)
    """
    from sase.monitor.result_projection import (
        build_monitor_result_wire,
        select_monitor_result_evidence,
        selected_raw_limits,
    )

    command = "echo hello-evidence; sleep 60"
    log_path = tmp_path / "live_reply.md"
    log_path.write_text(
        "sase tool run ef3fe08789955213264bf594c3025804\n"
        "hello-evidence\n"
        "succeeded  exit=0  duration=12ms\n",
        encoding="utf-8",
    )
    result = build_monitor_result_wire(
        monitor_id="mon-evidence",
        monitor_state="timeout",
        exit_code=None,
        command=command,
        cwd=str(tmp_path),
        started_at="unknown",
        stopped_at="unknown",
        elapsed_seconds=5.0,
        timeout_seconds=5.0,
        timeout_kind="total-timeout",
        retained_log={
            "log_ref": "file:monitor-retained-log:test",
            "local_locator": str(log_path),
            "total_observed_bytes": log_path.stat().st_size,
            "complete": True,
            "drain_confirmed": True,
        },
    )
    selection = select_monitor_result_evidence(result, next_output="auto")
    limits = selected_raw_limits(selection, requested_tail_lines=200)
    assert limits is not None
    tail_lines, max_chars = limits
    text = log_path.read_text(encoding="utf-8")
    tail = "".join(text.splitlines(keepends=True)[-tail_lines:])[:max_chars]
    assert "hello-evidence" in tail
