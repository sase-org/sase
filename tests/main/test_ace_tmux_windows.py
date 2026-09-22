"""Tests for ``sase tui --tmux`` against a real tmux server on a socket."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import uuid
from typing import Any

import pytest

from sase.main import ace_tmux
from tests.main.ace_tmux_helpers import (
    SocketTmuxRunner,
    patch_screenshot_request_dir,
)


@pytest.fixture(autouse=True)
def _sandbox_screenshot_request_dirs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    patch_screenshot_request_dir(monkeypatch, tmp_path)


def test_create_agent_tmux_window_uses_real_window_ids_on_isolated_socket(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")
    monkeypatch.setattr(
        ace_tmux,
        "screenshot_request_dir",
        lambda session, window_name: tmp_path / "requests" / session / window_name,
    )
    socket_path = Path("/tmp") / f"sase-test-tmux-{uuid.uuid4().hex}.sock"
    runner = SocketTmuxRunner(socket_path)
    first: Any = None
    second: Any = None
    try:
        first = ace_tmux.create_agent_tmux_window(
            "sleep 60",
            cols=40,
            rows=10,
            runner=runner.run,
            timeout=5,
        )
        second = ace_tmux.create_agent_tmux_window(
            "sleep 60",
            cols=40,
            rows=10,
            runner=runner.run,
            timeout=5,
        )

        assert first.window_name == "sase_tmux_1"
        assert second.window_name == "sase_tmux_2"
        assert first.target.startswith("@")
        assert second.target.startswith("@")
        assert first.target != second.target
        assert first.screenshot_dir != second.screenshot_dir

        first_dir = runner.run(
            [
                "tmux",
                "display-message",
                "-p",
                "-t",
                first.target,
                "#{@sase_screenshot_dir}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        second_dir = runner.run(
            [
                "tmux",
                "display-message",
                "-p",
                "-t",
                second.target,
                "#{@sase_screenshot_dir}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        assert first_dir.stdout.strip() == first.screenshot_dir
        assert second_dir.stdout.strip() == second.screenshot_dir
    finally:
        for window in (first, second):
            if window is not None:
                ace_tmux.release_tmux_window_claim(window.screenshot_dir)
        runner.run(
            ["tmux", "kill-server"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass


def test_fresh_agent_session_disappears_after_owned_window_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")
    monkeypatch.setattr(
        ace_tmux,
        "screenshot_request_dir",
        lambda session, window_name: tmp_path / "requests" / session / window_name,
    )
    socket_path = Path("/tmp") / f"sase-test-tmux-{uuid.uuid4().hex}.sock"
    runner = SocketTmuxRunner(socket_path)
    window: Any = None
    try:
        window = ace_tmux.create_agent_tmux_window(
            "sleep 60",
            cols=40,
            rows=10,
            runner=runner.run,
            timeout=5,
        )

        windows = runner.run(
            [
                "tmux",
                "list-windows",
                "-t",
                ace_tmux._AGENTS_SESSION,
                "-F",
                "#{window_name}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        assert window.window_name in windows.stdout
        assert ace_tmux._BOOTSTRAP_WINDOW_PREFIX not in windows.stdout
        assert "placeholder" not in windows.stdout

        runner.run(
            ["tmux", "kill-window", "-t", window.target],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        ace_tmux.release_tmux_window_claim(window.screenshot_dir)
        has_session = runner.run(
            ["tmux", "has-session", "-t", ace_tmux._AGENTS_SESSION],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        assert has_session.returncode != 0
    finally:
        if window is not None:
            ace_tmux.release_tmux_window_claim(window.screenshot_dir)
        runner.run(
            ["tmux", "kill-server"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass


def test_size_setup_failure_removes_owned_bootstrap_window(
    tmp_path: Path,
) -> None:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")

    class _DefaultSizeFailRunner(SocketTmuxRunner):
        def run(
            self,
            cmd: list[str],
            **kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            if cmd[:2] == ["tmux", "set-option"] and "-w" not in cmd:
                self.calls.append(list(cmd))
                return subprocess.CompletedProcess(
                    cmd,
                    1,
                    "",
                    "default-size failed\n",
                )
            return super().run(cmd, **kwargs)

    socket_path = Path("/tmp") / f"sase-test-tmux-{uuid.uuid4().hex}.sock"
    runner = _DefaultSizeFailRunner(socket_path)
    try:
        with pytest.raises(ace_tmux.TmuxLaunchError) as excinfo:
            ace_tmux.create_agent_tmux_window(
                "sleep 60",
                cols=40,
                rows=10,
                runner=runner.run,
                timeout=5,
            )

        assert "failed to set tmux default-size" in str(excinfo.value)
        has_session = runner.run(
            ["tmux", "has-session", "-t", ace_tmux._AGENTS_SESSION],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        assert has_session.returncode != 0
    finally:
        runner.run(
            ["tmux", "kill-server"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass


def test_preexisting_placeholder_window_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")
    monkeypatch.setattr(
        ace_tmux,
        "screenshot_request_dir",
        lambda session, window_name: tmp_path / "requests" / session / window_name,
    )
    socket_path = Path("/tmp") / f"sase-test-tmux-{uuid.uuid4().hex}.sock"
    runner = SocketTmuxRunner(socket_path)
    window: Any = None
    try:
        runner.run(
            [
                "tmux",
                "new-session",
                "-d",
                "-s",
                ace_tmux._AGENTS_SESSION,
                "-n",
                "placeholder",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )

        window = ace_tmux.create_agent_tmux_window(
            "sleep 60",
            cols=40,
            rows=10,
            runner=runner.run,
            timeout=5,
        )
        runner.run(
            ["tmux", "kill-window", "-t", window.target],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        ace_tmux.release_tmux_window_claim(window.screenshot_dir)

        windows = runner.run(
            [
                "tmux",
                "list-windows",
                "-t",
                ace_tmux._AGENTS_SESSION,
                "-F",
                "#{window_name}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        assert windows.returncode == 0
        assert windows.stdout.splitlines() == ["placeholder"]
    finally:
        if window is not None:
            ace_tmux.release_tmux_window_claim(window.screenshot_dir)
        runner.run(
            ["tmux", "kill-server"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass


def test_claim_window_cleans_real_window_after_post_create_timeout(
    tmp_path: Path,
) -> None:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")

    class _PostCreateTimeoutRunner(SocketTmuxRunner):
        def run(
            self,
            cmd: list[str],
            **kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            if cmd[:2] == ["tmux", "new-window"]:
                super().run(cmd, **kwargs)
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
            return super().run(cmd, **kwargs)

    socket_path = Path("/tmp") / f"sase-test-tmux-{uuid.uuid4().hex}.sock"
    runner = _PostCreateTimeoutRunner(socket_path)
    session = "sase-test-post-create"
    try:
        runner.run(
            ["tmux", "new-session", "-d", "-s", session, "-n", "placeholder"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )

        with pytest.raises(ace_tmux.TmuxLaunchError) as excinfo:
            ace_tmux._claim_window(
                session,
                "sleep 60",
                runner=runner.run,
                timeout=5,
            )

        assert "timed out while trying to create tmux window 'sase_tmux_1'" in str(
            excinfo.value
        )
        windows = runner.run(
            ["tmux", "list-windows", "-t", session, "-F", "#{window_name}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        assert "sase_tmux_1_" not in windows.stdout
        claim = tmp_path / session / "sase_tmux_1" / ace_tmux._WINDOW_CLAIM_FILE
        assert not claim.exists()
    finally:
        runner.run(
            ["tmux", "kill-server"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass
