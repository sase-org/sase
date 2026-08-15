"""Tests for the startup-acknowledgement gate in :mod:`sase.monitor.start`.

Split out of ``test_monitor_start.py`` (which was already near this repo's
per-file line limit) because these all exercise the same contract:
``start_monitor`` must not report a monitor as running until its supervisor
has proven -- via the ``.monitor_started`` marker -- that it survived its own
startup window.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.core.paths import sase_projects_dir
from sase.monitor.models import MonitorError, MonitorRecord
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.procs.runtime import proc_started_path
from sase.running_field import WorkspaceClaim, get_claimed_workspaces

from ._fixtures import (
    make_starter_agent,
    patch_project_records,
    register_workspace_checkout,
    write_project_file,
)

_POLL_TIMEOUT = 60.0
_POLL_INTERVAL = 0.1


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _wait_for_done(
    artifacts_dir: str,
    *,
    timeout: float = _POLL_TIMEOUT,
) -> dict[str, object]:
    done_path = Path(artifacts_dir) / "done.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if done_path.exists():
            try:
                return json.loads(done_path.read_text())
            except json.JSONDecodeError:
                pass
        time.sleep(_POLL_INTERVAL)
    raise AssertionError(f"monitor at {artifacts_dir} never finished")


def _wait_for_recorded_supervisor_pid(
    project_name: str,
    *,
    exclude: Path,
    timeout: float = _POLL_TIMEOUT,
) -> int:
    """Poll for the ``pid`` a not-yet-acknowledged supervisor recorded.

    ``start_monitor`` overwrites this on the new member's ``agent_meta.json``
    with the real supervisor pid immediately after spawning it -- well
    before it blocks on the startup acknowledgement -- so a caller racing a
    signal against that window can learn the real pid without waiting for
    ``start_monitor`` to return. The member briefly inherits the *caller's*
    own pid as a placeholder when its artifacts directory is first created
    (before that overwrite lands), so a bare "some int pid is present" check
    is not enough -- this pid must belong to a distinct, real process,
    never this one.
    """
    artifacts_root = sase_projects_dir() / project_name / "artifacts" / "ace-run"
    deadline = time.monotonic() + timeout
    poll_interval = 0.02
    while time.monotonic() < deadline:
        for meta_path in artifacts_root.glob("*/*/*/agent_meta.json"):
            if meta_path.parent == exclude:
                continue
            try:
                meta = json.loads(meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            pid = meta.get("pid")
            if isinstance(pid, int) and pid != os.getpid():
                return pid
        time.sleep(poll_interval)
    raise AssertionError("supervisor pid was never recorded")


def test_startup_sigterm_settles_stopped_without_running_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_PROC_BOOTSTRAP_IMPORT_DELAY_SECONDS", "1.0")
    sentinel = tmp_path / "command-ran"
    write_project_file("proj")
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--0",
        agent_family="acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    request = StartMonitorRequest(
        command=f"touch {shlex.quote(str(sentinel))}",
        reason="verify startup sigterm",
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
        inherit_lane_workspace_claim=False,
    )

    # `start_monitor` now blocks until the supervisor acknowledges startup,
    # which -- with the delay above -- happens only after the startup
    # window this test means to interrupt. Run it on a thread and deliver
    # the SIGTERM from the outside the moment the supervisor's pid is on
    # disk, so the signal still lands inside that window instead of after
    # `start_monitor` has already returned.
    results: list[MonitorRecord] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(start_monitor(request))
        except BaseException as exc:  # noqa: BLE001 - reraised on the main thread
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        supervisor_pid = _wait_for_recorded_supervisor_pid(
            "proj", exclude=Path(starter_dir), timeout=10.0
        )
        os.kill(supervisor_pid, signal.SIGTERM)
    finally:
        thread.join(timeout=_POLL_TIMEOUT)
    assert not thread.is_alive()
    if errors:
        assert results == []
        assert any("acknowledge" in str(exc) or "killed" in str(exc) for exc in errors)
        assert not sentinel.exists()
        return
    record = results[0]

    done = _wait_for_done(record.artifacts_dir, timeout=10.0)
    assert done["monitor_state"] in {"stopped", "failed"}
    assert not sentinel.exists()


def test_supervisor_ack_marker_carries_real_pid_pgid_and_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_project_file("proj")
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--0",
        agent_family="acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    record = start_monitor(
        StartMonitorRequest(
            command="true",
            reason="verify ack marker",
            timeout_seconds=30.0,
            cwd=str(tmp_path),
            project_name="proj",
            lane="acme",
            inherit_lane_workspace_claim=False,
        )
    )

    marker = json.loads(proc_started_path(record.monitor_id).read_text())
    assert marker["pid"] == record.pid
    assert marker["proc_id"] == record.monitor_id
    assert marker["supervisor_id"] == record.supervisor_identity
    assert isinstance(marker["pgid"], int)

    _wait_for_done(record.artifacts_dir)


def test_start_monitor_raises_and_restores_the_claim_when_the_supervisor_never_acknowledges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression this epic exists to fix.

    A supervisor that dies during its own startup window must never be
    reported as a live, running monitor, and the workspace claim it never
    got to keep must go back to the still-live starter, not the free pool
    where another agent could take it.
    """
    sentinel = tmp_path / "command-ran"
    project_file = write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    import sase.procs.spawn as spawn_module

    real_popen = spawn_module.subprocess.Popen

    def fake_popen(*args: object, **kwargs: object) -> object:
        del args
        # A real process, but one that has already exited by the time
        # `start_monitor` checks whether it acknowledged startup -- the
        # exact "died during its own ~0.8s Python startup" shape reported
        # in the original incident.
        dead = real_popen(["true"])
        dead.wait()
        pass_fds = kwargs["pass_fds"]
        assert isinstance(pass_fds, tuple)
        pid_fd = pass_fds[0]
        assert isinstance(pid_fd, int)
        os.write(pid_fd, json.dumps({"pid": dead.pid}).encode() + b"\n")
        return SimpleNamespace(
            pid=dead.pid, poll=lambda: 0, wait=lambda timeout=None: 0
        )

    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)

    request = StartMonitorRequest(
        command=f"touch {shlex.quote(str(sentinel))}",
        reason="verify",
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
    )

    with pytest.raises(MonitorError, match="died without acknowledging startup"):
        start_monitor(request)

    assert not sentinel.exists()

    artifacts_root = sase_projects_dir() / "proj" / "artifacts" / "ace-run"
    member_dirs = [
        p.parent
        for p in artifacts_root.glob("*/*/*/agent_meta.json")
        if p.parent != Path(starter_dir)
    ]
    assert len(member_dirs) == 1
    meta = json.loads((member_dirs[0] / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "failed"
    assert meta["monitor_settled"] is True
    done = json.loads((member_dirs[0] / "done.json").read_text())
    assert done["monitor_state"] == "failed"

    # The starter's claim comes back exactly as it was -- not released into
    # the free pool where another agent could take workspace #3 out from
    # under the still-live starter.
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].workspace_num == 3
    assert claims[0].pid == os.getpid()
    assert claims[0].workflow == "ace-run"
    assert claims[0].cl_name == "acme"


def test_start_monitor_releases_a_fresh_numbered_claim_when_the_supervisor_never_acknowledges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "managed"))
    monkeypatch.setattr(
        "sase.workspace_provider.store._list_git_remote_urls",
        lambda _primary_workspace_dir: [],
    )
    primary = tmp_path / "primary"
    primary.mkdir()
    workspace_dir = register_workspace_checkout(primary, 12)
    project_file = write_project_file("proj", workspace_dir=str(primary))
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--0",
        agent_family="acme",
        model="claude-sonnet-5",
        workspace_dir=str(primary),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    import sase.procs.spawn as spawn_module

    real_popen = spawn_module.subprocess.Popen

    def fake_popen(*args: object, **kwargs: object) -> object:
        del args
        dead = real_popen(["true"])
        dead.wait()
        pass_fds = kwargs["pass_fds"]
        assert isinstance(pass_fds, tuple)
        pid_fd = pass_fds[0]
        assert isinstance(pid_fd, int)
        os.write(pid_fd, json.dumps({"pid": dead.pid}).encode() + b"\n")
        return SimpleNamespace(
            pid=dead.pid, poll=lambda: 0, wait=lambda timeout=None: 0
        )

    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)

    request = StartMonitorRequest(
        command="true",
        reason="verify fresh claim rollback",
        timeout_seconds=30.0,
        cwd=workspace_dir,
        project_name="proj",
        lane="acme",
        inherit_lane_workspace_claim=False,
    )

    with pytest.raises(MonitorError, match="died without acknowledging startup"):
        start_monitor(request)

    assert get_claimed_workspaces(project_file) == []

    artifacts_root = sase_projects_dir() / "proj" / "artifacts" / "ace-run"
    member_dirs = [
        p.parent
        for p in artifacts_root.glob("*/*/*/agent_meta.json")
        if p.parent != Path(starter_dir)
    ]
    assert len(member_dirs) == 1
    meta = json.loads((member_dirs[0] / "agent_meta.json").read_text())
    assert meta["workspace_num"] == 12
    assert meta["workspace_dir"] == workspace_dir
    assert meta["monitor_state"] == "failed"


def test_start_monitor_kills_a_supervisor_that_never_writes_the_ack_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_project_file("proj")
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--0",
        agent_family="acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    import sase.procs.spawn as spawn_module

    monkeypatch.setenv("SASE_PROC_START_ACK_TIMEOUT_SECONDS", "0.3")

    real_popen = spawn_module.subprocess.Popen
    spawned: list[subprocess.Popen[bytes]] = []

    def fake_popen(*args: object, **kwargs: object) -> object:
        del args
        # Alive, but wedged before it could write `.monitor_started`.
        stalled = real_popen(["sleep", "30"])
        spawned.append(stalled)
        pass_fds = kwargs["pass_fds"]
        assert isinstance(pass_fds, tuple)
        pid_fd = pass_fds[0]
        assert isinstance(pid_fd, int)
        os.write(pid_fd, json.dumps({"pid": stalled.pid}).encode() + b"\n")
        return SimpleNamespace(
            pid=stalled.pid, poll=lambda: 0, wait=lambda timeout=None: 0
        )

    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)

    request = StartMonitorRequest(
        command="true",
        reason="verify",
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
        inherit_lane_workspace_claim=False,
    )

    with pytest.raises(MonitorError, match="did not acknowledge startup"):
        start_monitor(request)

    assert len(spawned) == 1
    # `start_monitor` must not leave a live, unacknowledged supervisor
    # running behind a caller that has already given up on it.
    try:
        spawned[0].wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        spawned[0].kill()
        spawned[0].wait(timeout=5.0)
        pytest.fail("supervisor was left running after the ack timeout")
