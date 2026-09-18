"""Failure-path regressions for local screenshot tmux launches."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence
import subprocess
from typing import Any

import pytest

from sase.main import ace_tmux
from sase.screenshot import local as screenshot_local
from sase.screenshot.local import capture_local_screenshot
from tests.main.test_screenshot_command import (
    _completed,
    _FakeRunner,
    _options,
    _sandbox_new_window_screenshots,
)


def test_local_capture_releases_claim_when_pre_create_launch_times_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ListWindowsTimeoutRunner(_FakeRunner):
        def run(
            self,
            cmd: Sequence[str],
            **kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            argv = list(cmd)
            if argv[:2] == ["tmux", "list-windows"]:
                self.calls.append(argv)
                self.call_kwargs.append(dict(kwargs))
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
            return super().run(cmd, **kwargs)

    runner = _ListWindowsTimeoutRunner(tmp_path)
    _sandbox_new_window_screenshots(monkeypatch, tmp_path)
    monkeypatch.setattr(ace_tmux.shutil, "which", lambda name: f"/usr/bin/{name}")

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_local_screenshot(_options(output=tmp_path / "shot.png"), runner=runner)

    assert "timed out while trying to list tmux windows" in str(excinfo.value)
    assert not runner.windows
    assert not any(call[:2] == ["tmux", "kill-window"] for call in runner.calls)
    claim = (
        tmp_path
        / "new-window-requests"
        / ace_tmux._AGENTS_SESSION
        / "sase_tmux_1"
        / ace_tmux._WINDOW_CLAIM_FILE
    )
    assert not claim.exists()


def test_local_capture_cleans_window_and_claim_when_new_window_times_out_after_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NewWindowTimeoutRunner(_FakeRunner):
        def run(
            self,
            cmd: Sequence[str],
            **kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            argv = list(cmd)
            if argv[:2] == ["tmux", "new-window"]:
                super().run(cmd, **kwargs)
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
            return super().run(cmd, **kwargs)

    runner = _NewWindowTimeoutRunner(tmp_path)
    _sandbox_new_window_screenshots(monkeypatch, tmp_path)
    monkeypatch.setattr(ace_tmux.shutil, "which", lambda name: f"/usr/bin/{name}")

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_local_screenshot(_options(output=tmp_path / "shot.png"), runner=runner)

    assert "timed out while trying to create tmux window 'sase_tmux_1'" in str(
        excinfo.value
    )
    assert not runner.windows
    assert any(
        call[:3] == ["tmux", "kill-window", "-t"]
        and call[-1].startswith(f"{ace_tmux._AGENTS_SESSION}:sase_tmux_1_")
        for call in runner.calls
    )
    assert runner.screenshot_dir is not None
    assert not (runner.screenshot_dir / ace_tmux._WINDOW_CLAIM_FILE).exists()


def test_startup_capture_timeout_reports_last_visible_pane_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StartupCaptureTimeoutRunner(_FakeRunner):
        def __init__(self, tmp_path: Path) -> None:
            super().__init__(tmp_path)
            self.capture_count = 0

        def run(
            self,
            cmd: Sequence[str],
            **kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            argv = list(cmd)
            if argv[:2] == ["tmux", "capture-pane"]:
                self.calls.append(argv)
                self.call_kwargs.append(dict(kwargs))
                self.capture_count += 1
                if self.capture_count == 1:
                    return _completed(argv, stdout="LAST_VISIBLE_SCREEN\n")
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
            return super().run(cmd, **kwargs)

    runner = _StartupCaptureTimeoutRunner(tmp_path)
    _sandbox_new_window_screenshots(monkeypatch, tmp_path)
    monkeypatch.setattr(ace_tmux.shutil, "which", lambda name: f"/usr/bin/{name}")

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_local_screenshot(
            _options(output=tmp_path / "shot.png", wait_for=()),
            runner=runner,
        )

    message = str(excinfo.value)
    assert "timed out while trying to capture tmux pane @1" in message
    assert "LAST_VISIBLE_SCREEN" in message
    assert not runner.windows


def test_wait_for_capture_timeout_reports_last_visible_pane_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _WaitForCaptureTimeoutRunner(_FakeRunner):
        def __init__(self, tmp_path: Path) -> None:
            super().__init__(tmp_path)
            self.capture_count = 0

        def run(
            self,
            cmd: Sequence[str],
            **kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            argv = list(cmd)
            if argv[:2] == ["tmux", "capture-pane"]:
                self.calls.append(argv)
                self.call_kwargs.append(dict(kwargs))
                self.capture_count += 1
                if self.capture_count <= 2:
                    return _completed(argv, stdout="Agents\nReady\n")
                if self.capture_count == 3:
                    return _completed(argv, stdout="LAST_VISIBLE_SCREEN\n")
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
            return super().run(cmd, **kwargs)

    runner = _WaitForCaptureTimeoutRunner(tmp_path)
    _sandbox_new_window_screenshots(monkeypatch, tmp_path)
    monkeypatch.setattr(ace_tmux.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(screenshot_local.time, "sleep", lambda seconds: None)

    with pytest.raises(screenshot_local.ScreenshotCaptureError) as excinfo:
        capture_local_screenshot(
            _options(
                output=tmp_path / "shot.png",
                presses=(),
                wait_for=("NEVER_MATCH",),
            ),
            runner=runner,
        )

    message = str(excinfo.value)
    assert "timed out while trying to capture tmux pane @1" in message
    assert "LAST_VISIBLE_SCREEN" in message
    assert not runner.windows
