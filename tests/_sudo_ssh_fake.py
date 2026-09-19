"""OpenSSH-accurate fake SSH endpoint for sudo transport tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_REAL_RUN = subprocess.run

_FAKE_REMOTE_SASE = r"""#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
if args[:2] == ["sudo", "exec"] and "--contract" in args:
    caps = [
        item
        for item in os.environ.get("SASE_FAKE_REMOTE_CAPABILITIES", "").split(",")
        if item
    ]
    print(json.dumps({"schema_version": 1, "capabilities": caps}))
    raise SystemExit(0)


def _opt(flag: str) -> str | None:
    if flag in args:
        return args[args.index(flag) + 1]
    return None


if args[:2] == ["sudo", "exec"]:
    manifest_path = Path(_opt("--manifest") or "")
    sha = _opt("--expected-sha256")
    ledger_path = Path(_opt("--ledger") or "")
    handshake_path = _opt("--handshake")
    detach = "--detach" in args
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    log_path = manifest_path.parent / "output.log"
    outcome = os.environ.get("SASE_FAKE_LEDGER_OUTCOME", "completed")
    sleep_for = float(os.environ.get("SASE_FAKE_EXEC_SLEEP", "0"))

    def write_ledger(status_outcome: str) -> None:
        ledger_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "request_id": manifest.get("request_id", "sudo-1"),
                    "manifest_sha256": sha,
                    "outcome": status_outcome,
                    "entries": [],
                    "diagnostic": None if status_outcome == "completed" else "fake",
                }
            )
            + "\n",
            encoding="utf-8",
        )

    if detach:
        if outcome == "auth_failed":
            write_ledger("auth_failed")
            raise SystemExit(10)
        pid = os.fork()
        if pid == 0:
            time.sleep(0.02)
            log_path.write_text("starting reviewed command\n", encoding="utf-8")
            deadline = time.time() + sleep_for
            while time.time() < deadline:
                if (manifest_path.parent / "stop").exists():
                    write_ledger("cancelled")
                    os._exit(0)
                time.sleep(0.02)
            log_path.write_text("starting reviewed command\ndone\n", encoding="utf-8")
            write_ledger(outcome)
            os._exit(0)
        boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        start = stat.split(") ", 1)[1].split()[19]
        Path(str(handshake_path)).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "sudo_exec_started",
                    "manifest_sha256": sha,
                    "executor_pid": pid,
                    "executor_identity": f"{boot}:{start}",
                    "ledger_path": str(ledger_path),
                    "log_path": str(log_path),
                    "started_at": time.time(),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        raise SystemExit(0)
    if sleep_for:
        time.sleep(sleep_for)
    write_ledger(outcome)
    raise SystemExit(0)

raise SystemExit(f"unexpected sase argv: {args!r}")
"""


def openssh_join_remote_argv(argv: list[str]) -> tuple[bool, str, str]:
    """Return ``(tty, host, joined_command)`` using OpenSSH's space-join rule."""
    if not argv or argv[0] != "ssh":
        raise AssertionError(f"expected ssh argv, got {argv!r}")
    rest = list(argv[1:])
    tty = False
    while rest and rest[0].startswith("-"):
        flag = rest.pop(0)
        if flag == "-t":
            tty = True
            continue
        raise AssertionError(f"unsupported ssh flag {flag!r}")
    if not rest:
        raise AssertionError("ssh argv is missing a host")
    host = rest.pop(0)
    return tty, host, " ".join(rest)


def current_process_identity(pid: int) -> str:
    """Return the Linux ``boot_id:start_ticks`` identity for *pid*."""
    boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    start = stat.split(") ", 1)[1].split()[19]
    return f"{boot}:{start}"


_FAKE_LOGIN_SHELL = r"""#!/usr/bin/env python3
import os
import subprocess
import sys

if sys.argv[1:2] != ["-lc"] or len(sys.argv) != 3:
    print(f"unexpected login shell argv: {sys.argv[1:]!r}", file=sys.stderr)
    raise SystemExit(64)

env = dict(os.environ)
if env.get("SASE_FAKE_LOGIN_PROVIDES_SASE") == "1":
    env["PATH"] = env["SASE_FAKE_LOGIN_BIN"] + os.pathsep + env.get("PATH", "")
raise SystemExit(subprocess.run(["/bin/sh", "-c", sys.argv[2]], env=env).returncode)
"""


def _path_without_command(raw: str, name: str) -> str:
    """Return *raw* PATH with directories that contain *name* removed."""
    parts: list[str] = []
    for item in raw.split(os.pathsep):
        if item and not (Path(item) / name).exists():
            parts.append(item)
    return os.pathsep.join(parts)


class FakeOpenSSHEndpoint:
    """Join remote argv like OpenSSH and execute it against an isolated root."""

    def __init__(
        self,
        root: Path,
        *,
        capabilities: tuple[str, ...] = ("detached_execution",),
        login_provides_sase: bool = True,
    ) -> None:
        self.root = root
        self.capabilities = capabilities
        self.login_provides_sase = login_provides_sase
        self.calls: list[list[str]] = []
        self.joined: list[str] = []
        self.unreachable = False
        self.fail_after_calls: int | None = None
        self.liveness_exit: int | None = None
        self.system_bin = root / "system-bin"
        self.login_bin = root / "login-bin"
        self.system_bin.mkdir(parents=True, exist_ok=True)
        self.login_bin.mkdir(parents=True, exist_ok=True)
        python3 = self.system_bin / "python3"
        if not python3.exists():
            python3.symlink_to(sys.executable)
        login_shell = self.system_bin / "fake-login-shell"
        login_shell.write_text(
            f"#!{sys.executable}\n" + _FAKE_LOGIN_SHELL.split("\n", 1)[1],
            encoding="utf-8",
        )
        login_shell.chmod(0o755)
        shim = self.login_bin / "sase"
        script = _FAKE_REMOTE_SASE
        if script.startswith("#!"):
            script = script.split("\n", 1)[1]
        shim.write_text(f"#!{sys.executable}\n{script}", encoding="utf-8")
        shim.chmod(0o755)

    def __call__(
        self, argv: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[Any]:
        if not argv or argv[0] != "ssh":
            return _REAL_RUN(argv, **kwargs)
        self.calls.append(list(argv))
        empty_out: str | bytes = "" if kwargs.get("text") else b""
        if self.unreachable or (
            self.fail_after_calls is not None
            and len(self.calls) > self.fail_after_calls
        ):
            return subprocess.CompletedProcess(
                argv, 255, stdout=empty_out, stderr=empty_out
            )
        _tty, _host, joined = openssh_join_remote_argv(argv)
        self.joined.append(joined)
        if self.liveness_exit is not None and "/proc/" in joined:
            return subprocess.CompletedProcess(
                argv, self.liveness_exit, stdout=empty_out, stderr=empty_out
            )
        env = os.environ.copy()
        env["PATH"] = os.pathsep.join(
            part
            for part in (
                str(self.system_bin),
                _path_without_command(env.get("PATH", ""), "sase"),
            )
            if part
        )
        env["SHELL"] = str(self.system_bin / "fake-login-shell")
        env["SASE_FAKE_LOGIN_BIN"] = str(self.login_bin)
        env["SASE_FAKE_LOGIN_PROVIDES_SASE"] = "1" if self.login_provides_sase else "0"
        env["SASE_FAKE_REMOTE_CAPABILITIES"] = ",".join(self.capabilities)
        env.setdefault("SASE_FAKE_EXEC_SLEEP", "0")
        env.setdefault("SASE_FAKE_LEDGER_OUTCOME", "completed")
        text = bool(kwargs.get("text"))
        stdin = kwargs.get("input")
        try:
            return _REAL_RUN(
                ["/bin/sh", "-c", joined],
                input=stdin,
                env=env,
                stdout=subprocess.PIPE
                if kwargs.get("stdout") is not subprocess.DEVNULL
                else subprocess.DEVNULL,
                stderr=subprocess.PIPE
                if kwargs.get("stderr") is not subprocess.DEVNULL
                else subprocess.DEVNULL,
                timeout=kwargs.get("timeout"),
                check=False,
                text=text,
            )
        except subprocess.TimeoutExpired:
            raise
