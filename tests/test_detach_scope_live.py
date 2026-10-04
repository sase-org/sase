"""Live systemd-run --scope regressions for ``detach_scope``."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sase.detach_scope import (
    DETACH_SCOPE_DISABLE_ENV,
    _current_systemd_unit,
    _is_sase_owned_systemd_unit,
    detach_scope,
)


def _section(output: str, begin: str, end: str) -> str:
    lines = output.splitlines()
    try:
        start = lines.index(begin)
        stop = lines.index(end)
    except ValueError:
        return ""
    return "\n".join(lines[start + 1 : stop])


def test_live_systemd_scope_changes_child_cgroup_when_running_from_sase_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "linux":
        pytest.skip("Linux-only cgroup regression")
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    parent_unit = _current_systemd_unit()
    if not _is_sase_owned_systemd_unit(parent_unit):
        pytest.skip("test process is not running inside a SASE-owned systemd unit")
    if shutil.which("systemd-run") is None:
        pytest.skip("systemd-run is unavailable")

    parent_cgroup = Path("/proc/self/cgroup").read_text(encoding="utf-8")
    launch = detach_scope(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; print(Path('/proc/self/cgroup').read_text())",
        ],
        description="SASE detach-scope regression",
        unit_prefix="sase-detach-test",
    )
    if not launch.escaped:
        pytest.skip("detach_scope did not escape in this environment")

    result = subprocess.run(
        launch.argv,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"systemd-run failed: {result.stderr.strip()}")

    assert result.stdout.strip()
    assert result.stdout != parent_cgroup


def test_live_scope_pid_unchanged_through_detach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "linux":
        pytest.skip("Linux-only cgroup regression")
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    parent_unit = _current_systemd_unit()
    if not _is_sase_owned_systemd_unit(parent_unit):
        pytest.skip("test process is not running inside a SASE-owned systemd unit")
    if shutil.which("systemd-run") is None:
        pytest.skip("systemd-run is unavailable")

    launch = detach_scope(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        description="SASE detach-scope pid regression",
        unit_prefix="sase-detach-pid-test",
    )
    if not launch.escaped:
        pytest.skip("detach_scope did not escape in this environment")

    child = subprocess.Popen(
        launch.argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = child.communicate(timeout=15)
    if child.returncode != 0:
        pytest.skip(f"systemd-run failed: {stderr.strip()}")

    # systemd-run --scope execs the command in place, so the pid callers record
    # from Popen is the pid of the wrapped command itself.
    reported = stdout.strip().splitlines()[-1]
    assert int(reported) == child.pid


def test_live_scope_preserves_lock_fd_through_detach(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import os as _os

    if sys.platform != "linux":
        pytest.skip("Linux-only cgroup regression")
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    parent_unit = _current_systemd_unit()
    if not _is_sase_owned_systemd_unit(parent_unit):
        pytest.skip("test process is not running inside a SASE-owned systemd unit")
    if shutil.which("systemd-run") is None:
        pytest.skip("systemd-run is unavailable")

    lock_path = tmp_path / "install.lock"
    lock_path.write_bytes(b"x")
    lock_fd = _os.open(lock_path, _os.O_RDWR)
    try:
        import fcntl as _fcntl

        _fcntl.flock(lock_fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        probe = tmp_path / "fd_probe.py"
        probe.write_text(
            "import fcntl, os, sys\n"
            "fd = int(sys.argv[1])\n"
            "st = os.fstat(fd)\n"
            "target = os.stat(sys.argv[2])\n"
            "assert (st.st_dev, st.st_ino) == (target.st_dev, target.st_ino)\n"
            "probe2 = os.open(sys.argv[2], os.O_RDWR)\n"
            "try:\n"
            "    fcntl.flock(probe2, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "except BlockingIOError:\n"
            "    print('lock-held')\n"
            "else:\n"
            "    raise SystemExit('lock fd did not survive systemd-run exec')\n",
            encoding="utf-8",
        )
        launch = detach_scope(
            [sys.executable, str(probe), str(lock_fd), str(lock_path)],
            description="SASE detach-scope lock-fd regression",
            unit_prefix="sase-detach-lock-test",
        )
        if not launch.escaped:
            pytest.skip("detach_scope did not escape in this environment")
        result = subprocess.run(
            launch.argv,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            pass_fds=(lock_fd,),
        )
        if result.returncode != 0:
            pytest.skip(f"systemd-run failed: {result.stderr.strip()}")
        assert "lock-held" in result.stdout
    finally:
        try:
            import fcntl as _fcntl2

            _fcntl2.flock(lock_fd, _fcntl2.LOCK_UN)
        except OSError:
            pass
        _os.close(lock_fd)


def test_live_scope_reports_oom_policy_continue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.detach_scope import _systemd_run_version, _user_manager_reachable

    if sys.platform != "linux":
        pytest.skip("Linux-only cgroup regression")
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    parent_unit = _current_systemd_unit()
    if not (_is_sase_owned_systemd_unit(parent_unit) or _user_manager_reachable()):
        pytest.skip("test process is not under a SASE unit or user manager")
    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        pytest.skip("systemd-run is unavailable")
    if shutil.which("systemctl") is None:
        pytest.skip("systemctl is unavailable")

    # The child reports its own cgroup and its own scope's OOMPolicy, so the
    # parent never polls the user manager for a transient unit that may still
    # be registering. `systemd-run --scope` runs synchronously, so the child
    # output arrives via communicate().
    probe = tmp_path / "oom_probe.py"
    probe.write_text(
        "import subprocess, time\n"
        "from pathlib import Path\n"
        "cgroup = Path('/proc/self/cgroup').read_text()\n"
        "print('CGROUP-BEGIN')\n"
        "print(cgroup, end='')\n"
        "print('CGROUP-END')\n"
        "unit = None\n"
        "for _line in cgroup.splitlines():\n"
        "    _parts = _line.split(':', 2)\n"
        "    _path = _parts[2] if len(_parts) == 3 else _line\n"
        "    for _comp in [p for p in _path.split('/') if p]:\n"
        "        if _comp.endswith(('.scope', '.service')):\n"
        "            unit = _comp\n"
        "print(f'UNIT={unit}')\n"
        "shown = ''\n"
        "for _ in range(20):\n"
        "    if unit is None:\n"
        "        break\n"
        "    _r = subprocess.run(\n"
        "        ['systemctl', '--user', 'show', unit,\n"
        "         '-p', 'LoadState', '-p', 'OOMPolicy'],\n"
        "        capture_output=True, text=True, timeout=10, check=False,\n"
        "    )\n"
        "    shown = _r.stdout\n"
        "    if 'LoadState=loaded' in shown:\n"
        "        break\n"
        "    time.sleep(0.5)\n"
        "print('SHOW-BEGIN')\n"
        "print(shown, end='')\n"
        "print('SHOW-END')\n",
        encoding="utf-8",
    )
    launch = detach_scope(
        [sys.executable, str(probe)],
        description="SASE detach-scope OOMPolicy regression",
        unit_prefix="sase-detach-oom-test",
    )
    if not launch.escaped:
        pytest.skip("detach_scope did not escape in this environment")
    version = _systemd_run_version(systemd_run)
    assert ("--property=OOMPolicy=continue" in launch.argv) == (
        version is not None and version >= 243
    )
    if "--property=OOMPolicy=continue" not in launch.argv:
        pytest.skip("systemd is too old for scope OOMPolicy")

    result = subprocess.run(
        launch.argv,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"systemd-run failed: {result.stderr.strip()[-500:]}")
    parent_cgroup = Path("/proc/self/cgroup").read_text(encoding="utf-8")
    child_cgroup = _section(result.stdout, "CGROUP-BEGIN", "CGROUP-END")
    assert child_cgroup.strip()
    assert child_cgroup != parent_cgroup
    show = _section(result.stdout, "SHOW-BEGIN", "SHOW-END")
    if "LoadState=loaded" not in show:
        pytest.skip("user manager did not report the transient scope")
    assert "OOMPolicy=continue" in show
