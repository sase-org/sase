"""Remote ``sase screenshot`` command tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence
import json
import os
import shlex
import subprocess
from typing import Any

import pytest

from sase.dispatch.ssh_target import RemoteSshTarget
from sase.main import screenshot_handler
from sase.main.screenshot_handler import handle_screenshot_command
from sase.screenshot import local as screenshot_local
from sase.screenshot import remote as screenshot_remote
from sase.screenshot.local import ScreenshotOptions
from sase.screenshot.remote import capture_remote_screenshot
from tests.main.parser_cli_helpers import parse_sase_args


def _completed(
    cmd: Sequence[str],
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(cmd), returncode, stdout, stderr)


class _FakeSshRunner:
    """Fake SSH runner for remote screenshot transport tests."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        probe_returncode: int = 0,
        capture_returncode: int = 0,
        fetch_returncode: int = 0,
        version_returncode: int = 0,
        cleanup_returncode: int = 0,
        remote_tmux_window: str = "sase_tmux_9",
        remote_tmux_target: str = "@42",
        include_tmux_target: bool = True,
    ) -> None:
        self.probe_returncode = probe_returncode
        self.capture_returncode = capture_returncode
        self.fetch_returncode = fetch_returncode
        self.version_returncode = version_returncode
        self.cleanup_returncode = cleanup_returncode
        self.remote_tmux_window = remote_tmux_window
        self.remote_tmux_target = remote_tmux_target
        self.include_tmux_target = include_tmux_target
        self.remote_root = tmp_path / "remote"
        self.remote_bin = tmp_path / "remote-bin"
        self.remote_state = tmp_path / "remote-state"
        self.remote_root.mkdir()
        self.remote_bin.mkdir()
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
                "FAKE_PROBE_RC": str(self.probe_returncode),
                "FAKE_REMOTE_INCLUDE_TMUX_TARGET": (
                    "1" if self.include_tmux_target else "0"
                ),
                "FAKE_REMOTE_STATE": str(self.remote_state),
                "FAKE_REMOTE_TMUX_TARGET": self.remote_tmux_target,
                "FAKE_REMOTE_TMUX_WINDOW": self.remote_tmux_window,
                "FAKE_VERSION_RC": str(self.version_returncode),
                "PATH": f"{self.remote_bin}{os.pathsep}{env.get('PATH', '')}",
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
        self._write_executable(
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
    if rc:
        message = "Permission denied" if rc == 255 else "sase: not found"
        print(message, file=sys.stderr)
        sys.exit(rc)
    print('{"schema_version": 1}')
    sys.exit(0)

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

if args == ["--version"]:
    rc = int(os.environ["FAKE_VERSION_RC"])
    if rc:
        print("version failed", file=sys.stderr)
        sys.exit(rc)
    print("sase 0.17.1")
    sys.exit(0)

print(f"unexpected sase argv: {args!r}", file=sys.stderr)
sys.exit(64)
""",
        )
        self._write_executable(
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
        self._write_executable(
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
        self._write_executable(
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
        self._write_executable(
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

    def _write_executable(self, name: str, script: str) -> None:
        path = self.remote_bin / name
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


def _options(
    *,
    output: Path,
    svg_only: bool = False,
    keep: bool = False,
    window: str | None = None,
    presses: tuple[str, ...] = ("j", "k"),
    wait_for: tuple[str, ...] = ("Ready",),
    timeout: float = 5,
    tui_args: tuple[str, ...] = ("--", "-t", "axe"),
) -> ScreenshotOptions:
    return ScreenshotOptions(
        output=output,
        size=(80, 24),
        presses=presses,
        wait_for=wait_for,
        settle_ms=1,
        svg_only=svg_only,
        keep=keep,
        window=window,
        timeout=timeout,
        tui_args=tui_args,
    )


def _route_fake_remote_tmp(
    monkeypatch: pytest.MonkeyPatch,
    runner: _FakeSshRunner,
) -> None:
    monkeypatch.setattr(screenshot_remote, "_REMOTE_BASE", str(runner.remote_root))


def test_remote_capture_runs_svg_leg_over_ssh_and_rasterizes_locally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(
        tmp_path,
        remote_tmux_window="duplicate display",
        remote_tmux_target="@42",
    )
    output = tmp_path / "remote.png"
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(
            host="apollo.tailnet",
            requested_machine=host,
            enrolled_alias=host,
            enrolled=True,
        ),
    )

    from sase.ace.tui import visual_render

    monkeypatch.setattr(visual_render, "render_svg_to_png", lambda svg: b"PNG")

    result = capture_remote_screenshot(
        "apollo",
        _options(
            output=output,
            presses=("j", "literal key's $HOME | echo"),
            wait_for=("Agents Ready|Loading", 'quote " and $dollar; noop'),
            tui_args=(
                "--",
                "-t",
                "axe panel",
                "--query",
                "owner=$USER|status:open",
            ),
        ),
        runner=runner,
    )

    assert output.read_bytes() == b"PNG"
    assert result.host == "apollo.tailnet"
    assert result.remote_sase_version == "sase 0.17.1"
    assert result.svg.read_text(encoding="utf-8") == (
        "<svg><text>Remote Ready</text></svg>"
    )
    assert result.tmux_window == "duplicate display"
    assert result.tmux_target == "@42"
    assert runner.cleanup_count == 1
    assert runner.remote_svg is not None
    assert not Path(runner.remote_svg).exists()
    assert len(runner.calls[1]) == 6

    remote_capture = next(
        command
        for command in runner.remote_invocations
        if command[:3] == ["sase", "screenshot", "--svg"]
    )
    remote_argv = remote_capture
    assert "--host" not in remote_argv
    assert remote_argv[:4] == ["sase", "screenshot", "--svg", "-o"]
    assert "-s" in remote_argv
    assert remote_argv[remote_argv.index("-s") + 1] == "80x24"
    assert "-d" in remote_argv
    assert remote_argv[remote_argv.index("-d") + 1] == "1"
    presses = [
        remote_argv[index + 1]
        for index, value in enumerate(remote_argv)
        if value == "-p"
    ]
    waits = [
        remote_argv[index + 1]
        for index, value in enumerate(remote_argv)
        if value == "-w"
    ]
    assert presses == ["j", "literal key's $HOME | echo"]
    assert waits == ["Agents Ready|Loading", 'quote " and $dollar; noop']
    assert remote_argv[-5:] == [
        "--",
        "-t",
        "axe panel",
        "--query",
        "owner=$USER|status:open",
    ]


def test_remote_capture_keep_then_recapture_uses_printed_unique_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(
        tmp_path,
        remote_tmux_window="duplicate display",
        remote_tmux_target="@42",
    )
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    from sase.ace.tui import visual_render

    monkeypatch.setattr(visual_render, "render_svg_to_png", lambda svg: b"PNG")

    first = capture_remote_screenshot(
        "apollo",
        _options(output=tmp_path / "first.png", keep=True),
        runner=runner,
    )
    capture_remote_screenshot(
        "apollo",
        _options(
            output=tmp_path / "second.png",
            window=first.tmux_target,
        ),
        runner=runner,
    )

    remote_captures = [
        command
        for command in runner.remote_invocations
        if command[:3] == ["sase", "screenshot", "--svg"]
    ]
    assert first.tmux_target == "@42"
    assert remote_captures[1][remote_captures[1].index("-W") + 1] == "@42"


def test_remote_send_keys_hint_survives_local_and_remote_shells(
    tmp_path: Path,
) -> None:
    runner = _FakeSshRunner(tmp_path)
    target = "@42 target 'single' \"quoted\" | ok; $literal"
    key = 'literal key\'s "quoted" $HOME | echo; true'
    result = _FakeRemoteResult(
        svg=tmp_path / "shot.svg",
        png=tmp_path / "shot.png",
        host="apollo.tailnet",
        remote_sase_version="sase 0.17.1",
        screenshot_dir="/tmp/sase-requests",
        tmux_session="sase_ace_agents",
        tmux_window="duplicate display",
        tmux_target=target,
        tmux_pid=9090,
    )

    completed = subprocess.run(
        ["/bin/sh", "-c", result.send_keys_hint.replace("<KEY>", shlex.quote(key))],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
        env=runner.shell_env(),
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert completed.stderr == ""
    assert ["tmux", "send-keys", "-t", target, key] in runner.remote_invocations


def test_remote_capture_contract_failure_asks_for_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path, probe_returncode=127)
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "bad-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    assert "missing or too old" in str(excinfo.value)
    assert runner.cleanup_count == 0


def test_remote_capture_requires_retained_tmux_target_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path, include_tmux_target=False)
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "old-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    message = str(excinfo.value)
    assert "sase_tmux_target" in message
    assert "upgrade" in message
    assert runner.cleanup_count == 1


def test_remote_capture_ssh_failure_is_not_reported_as_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path, probe_returncode=255)
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "offline-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    message = str(excinfo.value)
    assert "SSH failed" in message
    assert "missing or too old" not in message
    assert runner.cleanup_count == 0


def test_remote_capture_cleans_remote_temp_file_after_capture_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path, capture_returncode=2)
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "bad-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    assert "remote screenshot capture" in str(excinfo.value)
    assert runner.cleanup_count == 1
    assert runner.remote_svg is not None
    assert not Path(runner.remote_svg).exists()


def test_remote_capture_cleans_remote_temp_file_after_fetch_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path, fetch_returncode=1)
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "bad-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    assert "failed to fetch remote SVG" in str(excinfo.value)
    assert runner.cleanup_count == 1
    assert runner.remote_svg is not None
    assert not Path(runner.remote_svg).exists()


def test_remote_capture_cleans_remote_temp_file_after_version_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path, version_returncode=1)
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "bad-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    assert "failed to read remote sase version" in str(excinfo.value)
    assert runner.cleanup_count == 1
    assert runner.remote_svg is not None
    assert not Path(runner.remote_svg).exists()


def test_remote_capture_preserves_capture_error_when_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(
        tmp_path,
        capture_returncode=2,
        cleanup_returncode=1,
    )
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_remote_screenshot(
            "bad-host", _options(output=tmp_path / "shot.png"), runner=runner
        )

    message = str(excinfo.value)
    assert "remote screenshot capture" in message
    assert "cleanup failed" not in message
    assert runner.cleanup_count == 1


def test_remote_capture_timeouts_share_one_bounded_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(tmp_path)
    _route_fake_remote_tmp(monkeypatch, runner)
    monkeypatch.setattr(
        screenshot_remote,
        "resolve_remote_ssh_target",
        lambda host: RemoteSshTarget(host=host, requested_machine=host),
    )

    capture_remote_screenshot(
        "apollo",
        _options(output=tmp_path / "shot.png", timeout=0.25),
        runner=runner,
    )

    timeouts = [
        value
        for kwargs in runner.call_kwargs
        if isinstance((value := kwargs.get("timeout")), (int, float))
    ]
    assert timeouts
    assert all(0 < timeout <= 10.25 for timeout in timeouts)


def test_remote_handler_prints_version_and_keep_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _FakeRemoteResult(
        svg=tmp_path / "shot.svg",
        png=tmp_path / "shot.png",
        host="apollo.tailnet",
        remote_sase_version="sase 0.17.1",
        screenshot_dir="/tmp/sase-requests",
        tmux_session="sase_ace_agents",
        tmux_window="sase_tmux_9",
        tmux_target="@42",
        tmux_pid=9090,
    )
    monkeypatch.setattr(
        screenshot_handler,
        "capture_remote_screenshot",
        lambda host, options: result,
    )
    args = parse_sase_args(
        ["screenshot", "--host", "apollo", "--keep", "-o", str(tmp_path / "shot.png")]
    )

    handle_screenshot_command(args)

    out = capsys.readouterr().out
    assert "host=apollo.tailnet\n" in out
    assert "remote_sase_version=sase 0.17.1\n" in out
    assert "png=" in out
    assert "svg=" in out
    assert "sase_tmux_target=@42\n" in out
    assert (
        "remote_send_keys_hint=printf '%s\\n' <KEY> | ssh apollo.tailnet "
        "'IFS= read -r key && tmux send-keys -t @42 \"$key\"'\n"
    ) in out
