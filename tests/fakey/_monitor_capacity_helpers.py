"""Shared detached-supervisor bootstrap fakes for monitor capacity tests."""

from __future__ import annotations

import json
import os
import subprocess

from sase.procs.runtime import proc_started_path, write_json_atomic

_REAL_POPEN = subprocess.Popen


class FakeSupervisorPid:
    """A no-op process proxy reporting a real, currently-live supervisor PID."""

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self) -> int:
        return 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0


def make_bootstrap_popen(supervisor_pid: int):  # noqa: ANN201
    """Return a Popen fake reporting *supervisor_pid* for proc bootstrap only.

    ``spawn_module.subprocess`` is the process-wide ``subprocess`` module, so
    patching its ``Popen`` also intercepts unrelated calls this test does not
    own (workspace resolution shells out to real ``git``); those still run for
    real.
    """

    def fake_bootstrap_popen(*args: object, **kwargs: object) -> object:
        argv = args[0] if args else kwargs.get("args")
        if not isinstance(argv, list) or "--proc-id" not in argv:
            return _REAL_POPEN(*args, **kwargs)  # type: ignore[arg-type]
        proc_id = argv[argv.index("--proc-id") + 1]
        pass_fds = kwargs["pass_fds"]
        assert isinstance(pass_fds, tuple)
        pid_fd = pass_fds[0]
        assert isinstance(pid_fd, int)
        os.write(pid_fd, json.dumps({"pid": supervisor_pid}).encode() + b"\n")
        write_json_atomic(proc_started_path(proc_id), {"pid": supervisor_pid})
        return FakeSupervisorPid(supervisor_pid)

    return fake_bootstrap_popen
