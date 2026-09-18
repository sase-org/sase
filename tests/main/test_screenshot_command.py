"""Tests for the ``sase screenshot`` command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence
import subprocess
import sys
from typing import Any

import pytest

from sase.ace.tui.screenshot_export import screenshot_request_dir
from sase.dispatch.ssh_target import RemoteSshTarget
from sase.main import ace_tmux
from sase.main import screenshot_handler
from sase.main.screenshot_handler import handle_screenshot_command
from sase.screenshot import local as screenshot_local
from sase.screenshot import remote as screenshot_remote
from sase.screenshot.local import ScreenshotOptions, capture_local_screenshot
from sase.screenshot.remote import capture_remote_screenshot
from tests.main.parser_cli_helpers import parse_sase_args


def _completed(
    cmd: Sequence[str],
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(cmd), returncode, stdout, stderr)


class _FakeRunner:
    """Fake tmux/kill runner that creates the request-dir export files."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        cols: int = 80,
        rows: int = 24,
        transient_export_errors: int = 0,
    ) -> None:
        self.tmp_path = tmp_path
        self.cols = cols
        self.rows = rows
        self.session = ace_tmux._AGENTS_SESSION
        self.window = "sase_tmux_1"
        self.window_id = "@1"
        self.pane_pid = 4242
        self.transient_export_errors = transient_export_errors
        self.screenshot_dir: Path | None = None
        self.windows: dict[str, dict[str, object]] = {}
        self.calls: list[list[str]] = []
        self.call_kwargs: list[dict[str, Any]] = []

    def run(
        self,
        cmd: Sequence[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        argv = list(cmd)
        self.calls.append(argv)
        self.call_kwargs.append(dict(kwargs))
        if argv[0] == "kill":
            self._write_export()
            return _completed(argv)
        if argv[0] != "tmux":
            raise AssertionError(f"unexpected command: {argv!r}")

        subcommand = argv[1]
        if subcommand in {"has-session", "new-session"}:
            return _completed(argv)
        if subcommand == "list-windows":
            names = [str(window["name"]) for window in self.windows.values()]
            return _completed(argv, stdout="\n".join(names) + "\n")
        if subcommand == "set-option":
            if "-w" not in argv:
                return _completed(argv)
            window = self._window_for_target(argv[argv.index("-t") + 1])
            window["metadata"] = argv[-1]
            self.screenshot_dir = Path(argv[-1])
            return _completed(argv)
        if subcommand == "new-window":
            temp_name = argv[argv.index("-n") + 1]
            for index, token in enumerate(argv):
                if token == "-e":
                    key, _, value = argv[index + 1].partition("=")
                    if key == "SASE_TUI_SCREENSHOT_DIR":
                        self.screenshot_dir = Path(value)
            assert self.screenshot_dir is not None
            self.windows[self.window_id] = {
                "name": temp_name,
                "metadata": str(self.screenshot_dir),
            }
            return _completed(
                argv,
                stdout=f"{self.session}\t{self.window_id}\t{temp_name}\t{self.pane_pid}\n",
            )
        if subcommand == "rename-window":
            window = self._window_for_target(argv[argv.index("-t") + 1])
            window["name"] = argv[-1]
            self.window = argv[-1]
            return _completed(argv)
        if subcommand == "resize-window":
            return _completed(argv)
        if subcommand == "display-message":
            template = argv[-1]
            if "window_width" in template:
                return _completed(argv, stdout=f"{self.cols}x{self.rows}\n")
            metadata = (
                str(self.screenshot_dir) if self.screenshot_dir is not None else ""
            )
            return _completed(
                argv,
                stdout=(
                    f"{self.session}\t{self.window_id}\t{self.window}\t"
                    f"{self.pane_pid}\t{metadata}\n"
                ),
            )
        if subcommand == "capture-pane":
            return _completed(argv, stdout="Agents\nReady\n")
        if subcommand == "send-keys":
            return _completed(argv)
        if subcommand == "kill-window":
            target = argv[argv.index("-t") + 1]
            self.windows.pop(target, None)
            return _completed(argv)
        raise AssertionError(f"unexpected tmux subcommand: {argv!r}")

    def _window_for_target(self, target: str) -> dict[str, object]:
        if target in self.windows:
            return self.windows[target]
        if ":" in target:
            _session, _, name = target.partition(":")
            for window in self.windows.values():
                if window["name"] == name:
                    return window
        raise AssertionError(f"unknown tmux target: {target}")

    def _write_export(self) -> None:
        request_dir = self.screenshot_dir or screenshot_request_dir(
            self.session,
            self.window,
        )
        request_dir.mkdir(parents=True, exist_ok=True)
        existing = []
        for pattern in ("screen_*.svg", "screen_*.error"):
            existing.extend(
                int(child.stem.split("_", 1)[1]) for child in request_dir.glob(pattern)
            )
        sequence = max(existing, default=0) + 1
        if self.transient_export_errors > 0:
            self.transient_export_errors -= 1
            (request_dir / f"screen_{sequence}.error").write_text(
                "Node must be running before calling wait_for_refresh\n",
                encoding="utf-8",
            )
            return
        (request_dir / f"screen_{sequence}.svg").write_text(
            "<svg><text>Ready</text></svg>",
            encoding="utf-8",
        )
        (request_dir / f"screen_{sequence}.done").write_text(
            f"svg=screen_{sequence}.svg\n",
            encoding="utf-8",
        )


class _FakeSshRunner:
    """Fake SSH runner for remote screenshot transport tests."""

    def __init__(
        self,
        *,
        probe_returncode: int = 0,
        capture_returncode: int = 0,
        fetch_returncode: int = 0,
    ) -> None:
        self.probe_returncode = probe_returncode
        self.capture_returncode = capture_returncode
        self.fetch_returncode = fetch_returncode
        self.calls: list[list[str]] = []
        self.remote_svg: str | None = None
        self.cleanup_count = 0

    def run(
        self,
        cmd: Sequence[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        argv = list(cmd)
        self.calls.append(argv)
        assert argv[:4] == ["ssh", "-o", "ConnectTimeout=5", "--"]
        remote_argv = argv[5:]

        if remote_argv == ["sase", "screenshot", "--contract"]:
            return _completed(
                argv,
                returncode=self.probe_returncode,
                stdout='{"schema_version": 1}\n',
                stderr="sase: not found\n" if self.probe_returncode else "",
            )
        if remote_argv[:3] == ["sase", "screenshot", "--svg"]:
            self.remote_svg = remote_argv[remote_argv.index("-o") + 1]
            return _completed(
                argv,
                returncode=self.capture_returncode,
                stdout=(
                    f"svg={self.remote_svg}\n"
                    "sase_tmux_window=sase_tmux_9\n"
                    "sase_tmux_session=sase_ace_agents\n"
                    "sase_tmux_target=sase_ace_agents:sase_tmux_9\n"
                    "sase_tmux_pid=9090\n"
                    "sase_screenshot_dir=/tmp/sase-requests\n"
                ),
                stderr="remote capture failed\n" if self.capture_returncode else "",
            )
        if remote_argv == ["cat", self.remote_svg]:
            return _completed(
                argv,
                returncode=self.fetch_returncode,
                stdout="<svg><text>Remote Ready</text></svg>",
                stderr="missing svg\n" if self.fetch_returncode else "",
            )
        if remote_argv == ["sase", "--version"]:
            return _completed(argv, stdout="sase 0.17.1\n")
        if remote_argv[:2] == ["sh", "-c"]:
            self.cleanup_count += 1
            return _completed(argv)
        raise AssertionError(f"unexpected remote command: {remote_argv!r}")


@dataclass(frozen=True)
class _FakeRemoteResult:
    svg: Path
    png: Path | None
    host: str
    remote_sase_version: str
    screenshot_dir: str
    tmux_session: str
    tmux_window: str
    tmux_pid: int

    @property
    def tmux_target(self) -> str:
        return f"{self.tmux_session}:{self.tmux_window}"

    @property
    def send_keys_hint(self) -> str:
        return f"ssh {self.host} tmux send-keys -t {self.tmux_target} '<KEY>'"


def _options(
    *,
    output: Path,
    svg_only: bool = False,
    keep: bool = False,
    window: str | None = None,
) -> ScreenshotOptions:
    return ScreenshotOptions(
        output=output,
        size=(80, 24),
        presses=("j", "k"),
        wait_for=("Ready",),
        settle_ms=1,
        svg_only=svg_only,
        keep=keep,
        window=window,
        timeout=5,
        tui_args=("--", "-t", "axe"),
    )


def _sandbox_new_window_screenshots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        ace_tmux,
        "screenshot_request_dir",
        lambda session, window_name: (
            tmp_path / "new-window-requests" / session / window_name
        ),
    )


def test_parser_accepts_local_screenshot_surface() -> None:
    args = parse_sase_args(
        [
            "screenshot",
            "-d",
            "25",
            "-H",
            "apollo",
            "-k",
            "-o",
            "/tmp/shot.png",
            "-p",
            "j",
            "-s",
            "90x30",
            "-w",
            "Ready",
            "--",
            "-t",
            "axe",
        ]
    )

    assert args.command == "screenshot"
    assert args.host == "apollo"
    assert args.keep is True
    assert args.output == Path("/tmp/shot.png")
    assert args.press == ["j"]
    assert args.settle_ms == 25
    assert args.size == (90, 30)
    assert args.wait_for == ["Ready"]
    assert args.tui_args == ["--", "-t", "axe"]


def test_contract_probe_prints_schema_json(capsys) -> None:
    args = parse_sase_args(["screenshot", "--contract"])

    handle_screenshot_command(args)

    assert capsys.readouterr().out == '{"schema_version": 1}\n'


def test_entry_contract_probe_exits_without_fallthrough(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import entry

    monkeypatch.setattr(sys, "argv", ["sase", "screenshot", "--contract"])

    with pytest.raises(SystemExit) as exc:
        entry.main()

    captured = capsys.readouterr()
    assert exc.value.code == 0
    assert captured.out == '{"schema_version": 1}\n'
    assert captured.err == ""


def test_local_capture_launches_renders_and_cleans_up(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = _FakeRunner(tmp_path)
    output = tmp_path / "shot.png"
    _sandbox_new_window_screenshots(monkeypatch, tmp_path)
    monkeypatch.setattr(ace_tmux.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(screenshot_local.time, "sleep", lambda seconds: None)

    from sase.ace.tui import visual_render

    monkeypatch.setattr(visual_render, "render_svg_to_png", lambda svg: b"PNG")

    result = capture_local_screenshot(_options(output=output), runner=runner)

    assert output.read_bytes() == b"PNG"
    assert result.png == output
    assert result.svg.name == "screen_1.svg"
    assert result.tmux_session == ace_tmux._AGENTS_SESSION
    assert result.tmux_window == "sase_tmux_1"
    assert result.tmux_pid == 4242
    assert any(
        call[:2] == ["tmux", "send-keys"] and call[-1] == "j" for call in runner.calls
    )
    assert any(call[:2] == ["tmux", "kill-window"] for call in runner.calls)
    new_window = next(
        call for call in runner.calls if call[:2] == ["tmux", "new-window"]
    )
    relaunch = new_window[-1]
    assert " -m sase tui -x -r 0 -t axe" in relaunch
    env_values = [
        new_window[index + 1] for index, token in enumerate(new_window) if token == "-e"
    ]
    assert "TEXTUAL_ANIMATIONS=none" in env_values
    assert "COLORTERM=truecolor" in env_values
    assert "TERM=xterm-256color" in env_values
    new_window_index = runner.calls.index(new_window)
    assert 0 < runner.call_kwargs[new_window_index]["timeout"] <= 5
    assert result.tmux_target == "@1"


def test_local_capture_retries_transient_startup_export_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = _FakeRunner(tmp_path, transient_export_errors=1)
    output = tmp_path / "shot.png"
    _sandbox_new_window_screenshots(monkeypatch, tmp_path)
    monkeypatch.setattr(ace_tmux.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(screenshot_local.time, "sleep", lambda seconds: None)

    from sase.ace.tui import visual_render

    monkeypatch.setattr(visual_render, "render_svg_to_png", lambda svg: b"PNG")

    result = capture_local_screenshot(_options(output=output), runner=runner)

    assert result.svg.name == "screen_2.svg"
    assert output.read_bytes() == b"PNG"
    assert sum(call[0] == "kill" and call[1] == "-USR2" for call in runner.calls) == 2
    assert any(call[:2] == ["tmux", "kill-window"] for call in runner.calls)


def test_local_capture_cleans_owned_window_when_resize_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class _ResizeFailRunner(_FakeRunner):
        def run(
            self,
            cmd: Sequence[str],
            **kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            argv = list(cmd)
            if argv[:2] == ["tmux", "resize-window"]:
                self.calls.append(argv)
                self.call_kwargs.append(dict(kwargs))
                return _completed(argv, returncode=1, stderr="resize failed\n")
            return super().run(cmd, **kwargs)

    runner = _ResizeFailRunner(tmp_path)
    _sandbox_new_window_screenshots(monkeypatch, tmp_path)
    monkeypatch.setattr(ace_tmux.shutil, "which", lambda name: f"/usr/bin/{name}")

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_local_screenshot(_options(output=tmp_path / "shot.png"), runner=runner)

    assert "failed to resize tmux window @1" in str(excinfo.value)
    assert any(call == ["tmux", "kill-window", "-t", "@1"] for call in runner.calls)
    assert runner.screenshot_dir is not None
    assert not (runner.screenshot_dir / ace_tmux._WINDOW_CLAIM_FILE).exists()


def test_local_capture_cleans_owned_window_when_metadata_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class _MetadataFailRunner(_FakeRunner):
        def run(
            self,
            cmd: Sequence[str],
            **kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            argv = list(cmd)
            if argv[:3] == ["tmux", "set-option", "-w"]:
                self.calls.append(argv)
                self.call_kwargs.append(dict(kwargs))
                return _completed(argv, returncode=1, stderr="metadata failed\n")
            return super().run(cmd, **kwargs)

    runner = _MetadataFailRunner(tmp_path)
    _sandbox_new_window_screenshots(monkeypatch, tmp_path)
    monkeypatch.setattr(ace_tmux.shutil, "which", lambda name: f"/usr/bin/{name}")

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_local_screenshot(_options(output=tmp_path / "shot.png"), runner=runner)

    assert "failed to record screenshot request dir" in str(excinfo.value)
    assert any(call == ["tmux", "kill-window", "-t", "@1"] for call in runner.calls)
    assert runner.screenshot_dir is not None
    assert not (runner.screenshot_dir / ace_tmux._WINDOW_CLAIM_FILE).exists()


def test_local_capture_keep_then_recapture_uses_printed_unique_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = _FakeRunner(tmp_path)
    _sandbox_new_window_screenshots(monkeypatch, tmp_path)
    monkeypatch.setattr(ace_tmux.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(screenshot_local.time, "sleep", lambda seconds: None)

    from sase.ace.tui import visual_render

    monkeypatch.setattr(visual_render, "render_svg_to_png", lambda svg: b"PNG")

    first = capture_local_screenshot(
        _options(output=tmp_path / "first.png", keep=True),
        runner=runner,
    )
    second = capture_local_screenshot(
        _options(
            output=tmp_path / "second.svg",
            svg_only=True,
            window=first.tmux_target,
        ),
        runner=runner,
    )

    assert first.tmux_target == "@1"
    assert second.tmux_target == "@1"
    assert (first.screenshot_dir / "screen_2.svg").exists()
    assert not any(call[:2] == ["tmux", "kill-window"] for call in runner.calls)


def test_existing_window_svg_capture_does_not_kill_or_rasterize(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = _FakeRunner(tmp_path)
    existing_request_dir = tmp_path / "existing-window-request"
    runner.screenshot_dir = existing_request_dir
    output = tmp_path / "shot.svg"
    monkeypatch.setattr(
        screenshot_local,
        "screenshot_request_dir",
        lambda session, window_name: existing_request_dir,
    )
    monkeypatch.setattr(screenshot_local.time, "sleep", lambda seconds: None)

    from sase.ace.tui import visual_render

    monkeypatch.setattr(
        visual_render,
        "render_svg_to_png",
        lambda svg: (_ for _ in ()).throw(AssertionError("should not rasterize")),
    )

    result = capture_local_screenshot(
        _options(output=output, svg_only=True, window="sase_ace_agents:sase_tmux_1"),
        runner=runner,
    )

    assert output.read_text(encoding="utf-8") == "<svg><text>Ready</text></svg>"
    assert result.svg == output
    assert result.png is None
    assert result.created_window is False
    assert not any(call[:2] == ["tmux", "new-window"] for call in runner.calls)
    assert not any(call[:2] == ["tmux", "kill-window"] for call in runner.calls)


def test_remote_capture_runs_svg_leg_over_ssh_and_rasterizes_locally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner()
    output = tmp_path / "remote.png"
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
        _options(output=output),
        runner=runner,
    )

    assert output.read_bytes() == b"PNG"
    assert result.host == "apollo.tailnet"
    assert result.remote_sase_version == "sase 0.17.1"
    assert result.svg.read_text(encoding="utf-8") == (
        "<svg><text>Remote Ready</text></svg>"
    )
    assert result.tmux_target == "sase_ace_agents:sase_tmux_9"
    assert runner.cleanup_count == 1

    remote_capture = next(
        call for call in runner.calls if call[5:8] == ["sase", "screenshot", "--svg"]
    )
    remote_argv = remote_capture[5:]
    assert "--host" not in remote_argv
    assert remote_argv[:4] == ["sase", "screenshot", "--svg", "-o"]
    assert "-s" in remote_argv
    assert remote_argv[remote_argv.index("-s") + 1] == "80x24"
    assert "-d" in remote_argv
    assert remote_argv[remote_argv.index("-d") + 1] == "1"
    assert remote_argv.count("-p") == 2
    assert remote_argv[remote_argv.index("-w") + 1] == "Ready"
    assert remote_argv[-3:] == ["--", "-t", "axe"]


def test_remote_capture_contract_failure_asks_for_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(probe_returncode=127)
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


def test_remote_capture_cleans_remote_temp_file_after_capture_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _FakeSshRunner(capture_returncode=2)
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
    assert "remote_send_keys_hint=ssh apollo.tailnet tmux send-keys" in out
