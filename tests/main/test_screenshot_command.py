"""Tests for the ``sase screenshot`` command."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence
import subprocess
import sys
from typing import Any

import pytest

from sase.ace.tui.screenshot_export import screenshot_request_dir
from sase.main import ace_tmux
from sase.main.screenshot_handler import handle_screenshot_command
from sase.screenshot import local as screenshot_local
from sase.screenshot.local import ScreenshotOptions, capture_local_screenshot
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
        export_errors: Sequence[str] = (),
    ) -> None:
        self.tmp_path = tmp_path
        self.cols = cols
        self.rows = rows
        self.session = ace_tmux._AGENTS_SESSION
        self.window = "sase_tmux_1"
        self.window_id = "@1"
        self.pane_pid = 4242
        self.transient_export_errors = transient_export_errors
        self.export_errors = list(export_errors)
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
            try:
                window = self._window_for_target(target)
            except AssertionError:
                return _completed(argv)
            for window_id, candidate in list(self.windows.items()):
                if candidate is window:
                    self.windows.pop(window_id)
                    break
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
        if self.export_errors:
            (request_dir / f"screen_{sequence}.error").write_text(
                self.export_errors.pop(0) + "\n",
                encoding="utf-8",
            )
            return
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


def test_local_capture_retries_visible_startup_settle_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = _FakeRunner(
        tmp_path,
        export_errors=(
            "timed out waiting for screenshot frame convergence; "
            "pending_workers=['startup-visible:agents']",
        ),
    )
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


def test_local_capture_does_not_retry_permanent_export_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = _FakeRunner(tmp_path, export_errors=("render failed permanently",))
    _sandbox_new_window_screenshots(monkeypatch, tmp_path)
    monkeypatch.setattr(ace_tmux.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(screenshot_local.time, "sleep", lambda seconds: None)

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_local_screenshot(_options(output=tmp_path / "shot.png"), runner=runner)

    assert "render failed permanently" in str(excinfo.value)
    assert sum(call[0] == "kill" and call[1] == "-USR2" for call in runner.calls) == 1


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
