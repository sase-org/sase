"""Fixtures for remote screenshot command transport tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence
import json
import os
import subprocess
from typing import Any

from sase.screenshot import remote as screenshot_remote


def _completed(
    cmd: Sequence[str],
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(cmd), returncode, stdout, stderr)


def _version_payload(*packages: dict[str, Any]) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "runtime": {
                "executable": "/home/bryan/.local/bin/sase",
                "python_executable": "/venv/bin/python",
                "python_version": "3.12.8",
            },
            "packages": list(packages)
            or [
                {
                    "name": "sase-core-rs",
                    "role": "core",
                    "display_version": "0.17.1",
                },
                {
                    "name": "sase",
                    "role": "host",
                    "display_version": "0.17.1+861.g3fb42fa11",
                },
            ],
        }
    )


class _FakeSshRunner:
    """Fake SSH runner for remote screenshot transport tests."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        probe_returncode: int = 0,
        probe_stdout: str = '{"schema_version": 2}',
        probe_stderr: str = "",
        capture_returncode: int = 0,
        fetch_returncode: int = 0,
        version_returncode: int = 0,
        version_stdout: str | None = None,
        version_stderr: str = "",
        cleanup_returncode: int = 0,
        login_provides_sase: bool = True,
        remote_tmux_window: str = "sase_tmux_9",
        remote_tmux_target: str = "@42",
        include_tmux_target: bool = True,
    ) -> None:
        self.probe_returncode = probe_returncode
        self.probe_stdout = probe_stdout
        self.probe_stderr = probe_stderr
        self.capture_returncode = capture_returncode
        self.fetch_returncode = fetch_returncode
        self.version_returncode = version_returncode
        self.version_stdout = (
            _version_payload() if version_stdout is None else version_stdout
        )
        self.version_stderr = version_stderr
        self.cleanup_returncode = cleanup_returncode
        self.login_provides_sase = login_provides_sase
        self.remote_tmux_window = remote_tmux_window
        self.remote_tmux_target = remote_tmux_target
        self.include_tmux_target = include_tmux_target
        self.remote_root = tmp_path / "remote"
        self.remote_system_bin = tmp_path / "remote-system-bin"
        self.remote_login_bin = tmp_path / "remote-login-bin"
        self.remote_state = tmp_path / "remote-state"
        self.remote_root.mkdir()
        self.remote_system_bin.mkdir()
        self.remote_login_bin.mkdir()
        self.remote_state.mkdir()
        self.calls: list[list[str]] = []
        self.call_kwargs: list[dict[str, Any]] = []
        self.remote_svg: str | None = None
        self.cleanup_count = 0
        self._write_remote_programs()

    @property
    def remote_invocations(self) -> list[list[str]]:
        log = self.remote_state / "argv.jsonl"
        if not log.exists():
            return []
        return [
            json.loads(line)
            for line in log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def shell_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "FAKE_CAPTURE_RC": str(self.capture_returncode),
                "FAKE_CLEANUP_RC": str(self.cleanup_returncode),
                "FAKE_FETCH_RC": str(self.fetch_returncode),
                "FAKE_LOGIN_BIN": str(self.remote_login_bin),
                "FAKE_LOGIN_PROVIDES_SASE": ("1" if self.login_provides_sase else "0"),
                "FAKE_PROBE_RC": str(self.probe_returncode),
                "FAKE_PROBE_STDERR": self.probe_stderr,
                "FAKE_PROBE_STDOUT": self.probe_stdout,
                "FAKE_REMOTE_INCLUDE_TMUX_TARGET": (
                    "1" if self.include_tmux_target else "0"
                ),
                "FAKE_REMOTE_STATE": str(self.remote_state),
                "FAKE_REMOTE_TMUX_TARGET": self.remote_tmux_target,
                "FAKE_REMOTE_TMUX_WINDOW": self.remote_tmux_window,
                "FAKE_SYSTEM_PATH": self._system_path(),
                "FAKE_VERSION_RC": str(self.version_returncode),
                "FAKE_VERSION_STDERR": self.version_stderr,
                "FAKE_VERSION_STDOUT": self.version_stdout,
                "PATH": self._system_path(),
                "SHELL": str(self.remote_system_bin / "fake-login-shell"),
            }
        )
        return env

    def run(
        self,
        cmd: Sequence[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        argv = list(cmd)
        self.calls.append(argv)
        self.call_kwargs.append(dict(kwargs))
        assert argv[:4] == ["ssh", "-o", "ConnectTimeout=5", "--"]
        assert len(argv) == 6
        completed = subprocess.run(
            ["/bin/sh", "-c", argv[5]],
            capture_output=True,
            text=True,
            check=False,
            timeout=kwargs.get("timeout"),
            env=self.shell_env(),
        )
        self._refresh_state()
        return _completed(
            argv,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _system_path(self) -> str:
        return os.pathsep.join((str(self.remote_system_bin), "/usr/bin", "/bin"))

    def _refresh_state(self) -> None:
        remote_svg = self.remote_state / "remote_svg.txt"
        if remote_svg.exists():
            self.remote_svg = remote_svg.read_text(encoding="utf-8")
        cleanup_log = self.remote_state / "cleanup.jsonl"
        if cleanup_log.exists():
            self.cleanup_count = len(
                cleanup_log.read_text(encoding="utf-8").splitlines()
            )

    def _write_remote_programs(self) -> None:
        self._write_system_executable(
            "fake-login-shell",
            """#!/usr/bin/env python3
import json
import os
import pathlib
import subprocess
import sys

state = pathlib.Path(os.environ["FAKE_REMOTE_STATE"])
with (state / "argv.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(["login-shell", *sys.argv[1:]]) + "\\n")

if sys.argv[1:2] != ["-lc"] or len(sys.argv) != 3:
    print(f"unexpected login shell argv: {sys.argv[1:]!r}", file=sys.stderr)
    sys.exit(64)

env = dict(os.environ)
if env["FAKE_LOGIN_PROVIDES_SASE"] == "1":
    env["PATH"] = env["FAKE_LOGIN_BIN"] + os.pathsep + env["FAKE_SYSTEM_PATH"]
else:
    env["PATH"] = env["FAKE_SYSTEM_PATH"]

completed = subprocess.run(["/bin/sh", "-c", sys.argv[2]], check=False, env=env)
sys.exit(completed.returncode)
""",
        )
        self._write_login_executable(
            "sase",
            """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

state = pathlib.Path(os.environ["FAKE_REMOTE_STATE"])

def log(argv):
    with (state / "argv.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(argv) + "\\n")

args = sys.argv[1:]
log(["sase", *args])

if args == ["screenshot", "--contract"]:
    rc = int(os.environ["FAKE_PROBE_RC"])
    stdout = os.environ["FAKE_PROBE_STDOUT"]
    stderr = os.environ["FAKE_PROBE_STDERR"]
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    sys.exit(rc)

if args[:2] == ["screenshot", "--svg"]:
    remote_svg = args[args.index("-o") + 1]
    (state / "remote_svg.txt").write_text(remote_svg, encoding="utf-8")
    pathlib.Path(remote_svg).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(remote_svg).write_text(
        "<svg><text>Remote Ready</text></svg>",
        encoding="utf-8",
    )
    rc = int(os.environ["FAKE_CAPTURE_RC"])
    if rc:
        print("remote capture failed", file=sys.stderr)
        sys.exit(rc)
    print(f"svg={remote_svg}")
    print("sase_tmux_window=" + os.environ["FAKE_REMOTE_TMUX_WINDOW"])
    print("sase_tmux_session=sase_ace_agents")
    if os.environ["FAKE_REMOTE_INCLUDE_TMUX_TARGET"] == "1":
        print("sase_tmux_target=" + os.environ["FAKE_REMOTE_TMUX_TARGET"])
    print("sase_tmux_pid=9090")
    print("sase_screenshot_dir=/tmp/sase-requests")
    sys.exit(0)

if args == ["version", "--json"]:
    rc = int(os.environ["FAKE_VERSION_RC"])
    stdout = os.environ["FAKE_VERSION_STDOUT"]
    stderr = os.environ["FAKE_VERSION_STDERR"]
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    sys.exit(rc)

if args == ["--version"]:
    print("unsupported legacy --version", file=sys.stderr)
    sys.exit(64)

print(f"unexpected sase argv: {args!r}", file=sys.stderr)
sys.exit(64)
""",
        )
        self._write_system_executable(
            "cat",
            """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

state = pathlib.Path(os.environ["FAKE_REMOTE_STATE"])
with (state / "argv.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(["cat", *sys.argv[1:]]) + "\\n")

rc = int(os.environ["FAKE_FETCH_RC"])
if rc:
    print("missing svg", file=sys.stderr)
    sys.exit(rc)

sys.stdout.write(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
""",
        )
        self._write_system_executable(
            "rm",
            """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

state = pathlib.Path(os.environ["FAKE_REMOTE_STATE"])
argv = ["rm", *sys.argv[1:]]
with (state / "argv.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(argv) + "\\n")
with (state / "cleanup.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(argv) + "\\n")

rc = int(os.environ["FAKE_CLEANUP_RC"])
if rc:
    print("cleanup failed", file=sys.stderr)
    sys.exit(rc)

force = "-f" in sys.argv[1:]
for raw in sys.argv[1:]:
    if raw.startswith("-"):
        continue
    path = pathlib.Path(raw)
    try:
        path.unlink()
    except FileNotFoundError:
        if not force:
            raise
sys.exit(0)
""",
        )
        self._write_system_executable(
            "ssh",
            """#!/usr/bin/env python3
import json
import os
import pathlib
import subprocess
import sys

state = pathlib.Path(os.environ["FAKE_REMOTE_STATE"])
argv = sys.argv[1:]
with (state / "argv.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(["ssh", *argv]) + "\\n")

remote = list(argv)
if remote[:2] == ["-o", "ConnectTimeout=5"]:
    remote = remote[2:]
if remote[:1] == ["--"]:
    remote = remote[1:]
if not remote:
    sys.exit(64)

command = " ".join(remote[1:])
if not command:
    sys.exit(0)

completed = subprocess.run(
    ["/bin/sh", "-c", command],
    check=False,
    env=os.environ,
)
sys.exit(completed.returncode)
""",
        )
        self._write_system_executable(
            "tmux",
            """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

state = pathlib.Path(os.environ["FAKE_REMOTE_STATE"])
argv = ["tmux", *sys.argv[1:]]
with (state / "argv.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(argv) + "\\n")

if sys.argv[1:2] == ["send-keys"]:
    sys.exit(0)

print(f"unexpected tmux argv: {sys.argv[1:]!r}", file=sys.stderr)
sys.exit(64)
""",
        )

    def _write_system_executable(self, name: str, script: str) -> None:
        self._write_executable(self.remote_system_bin / name, script)

    def _write_login_executable(self, name: str, script: str) -> None:
        self._write_executable(self.remote_login_bin / name, script)

    def _write_executable(self, path: Path, script: str) -> None:
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)


@dataclass(frozen=True)
class _FakeRemoteResult:
    svg: Path
    png: Path | None
    host: str
    remote_sase_version: str
    screenshot_dir: str
    tmux_session: str
    tmux_window: str
    tmux_target: str
    tmux_pid: int

    @property
    def send_keys_hint(self) -> str:
        return screenshot_remote._remote_send_keys_hint(self.host, self.tmux_target)


__all__ = ["_FakeRemoteResult", "_FakeSshRunner", "_version_payload"]
