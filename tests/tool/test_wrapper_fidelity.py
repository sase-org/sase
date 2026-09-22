"""Phase wrapper-fidelity: process groups, merged streams, identity-matched reaping."""

from __future__ import annotations

import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

import pytest

from sase.config.core import clear_config_cache
from sase.core.process_identity import process_identity_token
from sase.core.tool_run import (
    tool_run_begin,
    tool_run_list,
    tool_run_observe,
)
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.executor_process import should_merge_streams
from sase.tool.liveness import current_boot_id, reconcile_unsettled_tool_runs


SASE = Path(__file__).resolve().parents[2] / ".venv" / "bin" / "sase"
NEEDS_SASE = pytest.mark.skipif(
    not SASE.exists(), reason="workspace sase executable missing"
)
NEEDS_POSIX = pytest.mark.skipif(
    os.name != "posix", reason="process groups are POSIX-only"
)
NEEDS_LINUX = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="parent-death signal is Linux-only",
)

_OWNERSHIP_ENV = (
    "SASE_AGENT",
    "SASE_AGENT_NAME",
    "SASE_MONITOR_ID",
    "SASE_MONITOR_ARTIFACTS_DIR",
    "SASE_PROC_ID",
    "SASE_TOOL_RUN_ID",
    "SASE_TOOL_NAME",
    "SASE_TOOL_PROJECT_ROOT",
    "SASE_TOOL_RUN_AGENT",
    "SASE_TOOL_RUN_EVENTS",
)


def _home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    for key in _OWNERSHIP_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


def _env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["SASE_HOME"] = str(home)
    for key in _OWNERSHIP_ENV:
        env.pop(key, None)
    return env


def _wait_running(env: dict[str, str], timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            listed = tool_run_list({"schema_version": 1, "limit": 10})
        except Exception:  # noqa: BLE001 - store may still be creating.
            time.sleep(0.05)  # sase-test-wait: store create race
            continue
        for run in listed.get("runs") or ():
            if run.get("state") == "running":
                return run
        time.sleep(0.05)  # sase-test-wait: poll running ToolRun row
    raise AssertionError("tool run did not become running")


def _wait_child_facts(run_id: str, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        listed = tool_run_list({"schema_version": 1, "limit": 10})
        for run in listed.get("runs") or ():
            if run.get("run_id") == run_id and run.get("child_pgid"):
                return run
        time.sleep(0.05)  # sase-test-wait: observe lands right after spawn
    raise AssertionError("child facts were not observed at spawn")


def _wait_state(run_id: str, state: str, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reconcile_unsettled_tool_runs()
        listed = tool_run_list({"schema_version": 1, "limit": 10})
        for run in listed.get("runs") or ():
            if run.get("run_id") == run_id and run.get("state") == state:
                return run
        time.sleep(0.05)  # sase-test-wait: lost transition settles
    raise AssertionError(f"tool run {run_id} did not become {state}")


def _wait_pidfile(pidfile: Path, timeout: float = 20.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return int(pidfile.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            time.sleep(0.05)  # sase-test-wait: fixture writes its pid
    raise AssertionError("fixture child did not report its pid")


def _alive(pid: int) -> bool:
    """Return whether *pid* is a living process (a zombie counts as dead)."""

    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        state = stat.rsplit(")", 1)[1].split()[0]
    except IndexError:
        return True
    return state != "Z"


def _kill_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def _cleanup_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass


def _definition() -> dict:
    return {
        "schema_version": 1,
        "name": "ad-hoc",
        "argv": ["true"],
        "description": "",
        "stages": "none",
        "inputs": [],
        "env": [],
        "args": "allow",
        "fingerprint": {"repos": [], "toolchain": {}},
    }


def _begin_with_dead_wrapper() -> str:
    """Begin a run whose wrapper is provably dead (stale pid, reused identity)."""

    finished = subprocess.Popen(["true"])
    finished.wait()
    started = tool_run_begin(
        {
            "schema_version": 1,
            "definition": _definition(),
            "display_argv": ["true"],
            "project": "fixture",
            "commit_running": True,
            "wrapper_pid": finished.pid,
            "boot_id": current_boot_id() or None,
            "process_start_identity": f"{current_boot_id()}:1",
        }
    )
    return str(started["run"]["run_id"])


@NEEDS_POSIX
@NEEDS_SASE
def test_owner_child_shares_wrapper_group_and_group_kill_leaves_no_survivors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A TERM-ignoring child under an owner dies with the wrapper's group."""

    home = _home(monkeypatch, tmp_path)
    env = _env(home)
    env["SASE_MONITOR_ID"] = "fixture-owner"
    pidfile = tmp_path / "child.pid"
    wrapper = subprocess.Popen(
        [
            str(SASE),
            "tool",
            "run",
            "--",
            "sh",
            "-c",
            f'trap "" TERM; echo $$ > {pidfile}; exec sleep 60',
        ],
        env=env,
        cwd=tmp_path,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    child_pid: int | None = None
    try:
        run = _wait_running(env)
        child_pid = _wait_pidfile(pidfile)
        # The child joins the wrapper's own process group so the owner's
        # killpg reaches the whole tree.
        assert os.getpgid(child_pid) == wrapper.pid
        observed = _wait_child_facts(str(run["run_id"]))
        assert observed["child_pgid"] == wrapper.pid
        os.killpg(wrapper.pid, signal.SIGTERM)
        time.sleep(1.0)  # sase-test-wait: TERM is ignored, nothing exits yet
        assert _alive(child_pid)
        assert wrapper.poll() is None
        # Pass the 5 s supervisor grace: the wrapper must skip its own
        # SIGKILL escalation under a live owner, so the child survives until
        # the owner itself escalates.
        time.sleep(4.5)  # sase-test-wait: outlast TERM_ESCALATE_SECONDS
        assert _alive(child_pid)
        assert wrapper.poll() is None
        os.killpg(wrapper.pid, signal.SIGKILL)
        wrapper.wait(timeout=5)
        assert not _alive(child_pid)
        lost = _wait_state(str(run["run_id"]), "lost")
        assert lost["child_pgid"] == wrapper.pid
    finally:
        _cleanup_group(wrapper.pid)
        if wrapper.poll() is None:
            wrapper.kill()
            wrapper.wait(timeout=2)
        if child_pid is not None:
            _kill_pid(child_pid)


@NEEDS_LINUX
@NEEDS_SASE
def test_inline_caller_group_sigkill_leaves_no_survivors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A SIGKILL of an inline caller's group leaves nothing behind."""

    home = _home(monkeypatch, tmp_path)
    env = _env(home)
    pidfile = tmp_path / "child.pid"
    caller_py = tmp_path / "caller.py"
    caller_py.write_text(
        "import os\n"
        f"os.execv({str(SASE)!r}, [{str(SASE)!r}, 'tool', 'run', '--', "
        f"'sh', '-c', 'echo $$ > {pidfile}; exec sleep 60'])\n",
        encoding="utf-8",
    )
    caller = subprocess.Popen(
        [sys.executable, str(caller_py)],
        env=env,
        cwd=tmp_path,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    child_pid: int | None = None
    try:
        run = _wait_running(env)
        child_pid = _wait_pidfile(pidfile)
        # Inline children run in their own group (so the wrapper can signal
        # them without signaling itself); the parent-death signal covers the
        # caller-group SIGKILL no handler can catch.
        assert os.getpgid(child_pid) == child_pid
        assert os.getpgid(child_pid) != caller.pid
        observed = _wait_child_facts(str(run["run_id"]))
        assert observed["child_pgid"] == child_pid
        os.killpg(caller.pid, signal.SIGKILL)
        caller.wait(timeout=5)
        deadline = time.monotonic() + 5
        while _alive(child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)  # sase-test-wait: parent-death SIGKILL lands
        assert not _alive(child_pid)
        lost = _wait_state(str(run["run_id"]), "lost")
        assert lost["child_pgid"] == child_pid
    finally:
        _cleanup_group(caller.pid)
        if caller.poll() is None:
            caller.kill()
            caller.wait(timeout=2)
        if child_pid is not None:
            _cleanup_group(child_pid)
            _kill_pid(child_pid)


@NEEDS_SASE
def test_merged_same_fd_target_preserves_interleave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One merged pipe keeps out/err write order when fds share a target."""

    home = _home(monkeypatch, tmp_path)
    env = _env(home)
    outpath = tmp_path / "merged.log"
    with outpath.open("wb") as handle:
        proc = subprocess.Popen(
            [
                str(SASE),
                "tool",
                "run",
                "--",
                "sh",
                "-c",
                "for i in 1 2 3 4 5 6 7 8 9 10; do echo out$i; echo err$i >&2; done",
            ],
            env=env,
            cwd=tmp_path,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        try:
            assert proc.wait(timeout=30) == 0
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2)
    lines = outpath.read_text(encoding="utf-8", errors="replace").splitlines()
    sequence = [line for line in lines if re.fullmatch(r"(out|err)(10|[1-9])", line)]
    expected = [item for pair in range(1, 11) for item in (f"out{pair}", f"err{pair}")]
    assert sequence == expected


def test_owner_run_merges_streams_in_write_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Under an enclosing owner both streams pass through once, in order."""

    _home(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_MONITOR_ID", "mon-owner")
    code = execute_tool_run(
        ToolRunCliRequest(
            quiet=False,
            verbose=False,
            tail_lines=200,
            words=(
                "--",
                "sh",
                "-c",
                "for i in 1 2 3 4; do echo out$i; echo err$i >&2; done",
            ),
        )
    )
    captured = capsys.readouterr()
    assert code == 0
    sequence = [
        line
        for line in captured.out.splitlines()
        if re.fullmatch(r"(out|err)[1-4]", line)
    ]
    assert sequence == [
        "out1",
        "err1",
        "out2",
        "err2",
        "out3",
        "err3",
        "out4",
        "err4",
    ]


def test_reconcile_without_reap_never_signals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read-only reconcile authorizes but never signals; reaping is explicit."""

    _home(monkeypatch, tmp_path)
    guarded = subprocess.Popen(
        ["sleep", "60"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        run_id = _begin_with_dead_wrapper()
        token = process_identity_token(guarded.pid)
        assert token
        tool_run_observe(
            {
                "schema_version": 1,
                "run_id": run_id,
                "child_pid": guarded.pid,
                "child_pgid": guarded.pid,
                "child_process_start_identity": token,
            }
        )
        result = reconcile_unsettled_tool_runs()
        assert _alive(guarded.pid)
        candidates = result.get("reap_candidates") or []
        assert [item["run_id"] for item in candidates if isinstance(item, dict)] == [
            run_id
        ]
    finally:
        _kill_pid(guarded.pid)
        guarded.wait(timeout=5)


def test_reap_signals_identity_matched_group_but_spares_stale_pgid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit reaping kills the matched group and spares a stale pgid."""

    _home(monkeypatch, tmp_path)
    matched = subprocess.Popen(
        ["sleep", "60"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    stale = subprocess.Popen(
        ["sleep", "60"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        matched_id = _begin_with_dead_wrapper()
        tool_run_observe(
            {
                "schema_version": 1,
                "run_id": matched_id,
                "child_pid": matched.pid,
                "child_pgid": matched.pid,
                "child_process_start_identity": process_identity_token(matched.pid),
            }
        )
        stale_id = _begin_with_dead_wrapper()
        tool_run_observe(
            {
                "schema_version": 1,
                "run_id": stale_id,
                "child_pid": stale.pid,
                "child_pgid": stale.pid,
                # A PID-reuse mismatch: well-formed but not this process.
                "child_process_start_identity": f"{current_boot_id()}:1",
            }
        )
        result = reconcile_unsettled_tool_runs(reap_orphans=True)
        diagnostics = [str(item) for item in result.get("diagnostics") or ()]
        assert not _alive(matched.pid)
        assert any(
            f"run {matched_id}" in item and "SIGTERM" in item for item in diagnostics
        )
        assert _alive(stale.pid)
        assert any(
            f"run {stale_id}" in item and "no longer matches" in item
            for item in diagnostics
        )
    finally:
        _kill_pid(matched.pid)
        _kill_pid(stale.pid)
        matched.wait(timeout=5)
        stale.wait(timeout=5)


def test_reap_spares_own_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A candidate naming our own group is a diagnostic, never a signal."""

    _home(monkeypatch, tmp_path)
    run_id = _begin_with_dead_wrapper()
    own_pgid = os.getpgrp()
    tool_run_observe(
        {
            "schema_version": 1,
            "run_id": run_id,
            "child_pid": own_pgid,
            "child_pgid": own_pgid,
            "child_process_start_identity": process_identity_token(own_pgid),
        }
    )
    result = reconcile_unsettled_tool_runs(reap_orphans=True)
    diagnostics = [str(item) for item in result.get("diagnostics") or ()]
    assert any("own process group" in item for item in diagnostics)


def test_should_merge_streams_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compact mode keeps two pipes; owners always merge."""

    assert should_merge_streams(owns_output=False, compact=False) is True
    assert should_merge_streams(owns_output=True, compact=True) is False
    monkeypatch.setattr(
        "sase.tool.executor_process._streams_share_target", lambda: True
    )
    assert should_merge_streams(owns_output=True, compact=False) is True
    assert should_merge_streams(owns_output=True, compact=True) is False
    monkeypatch.setattr(
        "sase.tool.executor_process._streams_share_target", lambda: False
    )
    assert should_merge_streams(owns_output=True, compact=False) is False
