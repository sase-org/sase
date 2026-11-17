"""pty+tmux regression probe for video stills in the tracked viewer pane."""

from __future__ import annotations

import fcntl
import io
import os
import shutil
import subprocess
import sys
import termios
import time
from pathlib import Path
from struct import pack

import pytest


pytestmark = [pytest.mark.slow, pytest.mark.terminal_smoke]

_REPO_ROOT = Path(__file__).resolve().parents[4]

_SENTINEL_TITLE = "sase-video-probe-title"
_MAX_CLIENT_BYTES = 4 * 1024 * 1024


def _tmux(
    socket: str, *args: str, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["tmux", "-L", socket, *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_video_pane_tmux_probe(tmp_path: Path) -> None:
    """A video opened in the tmux viewer pane shows a still, not mpv."""

    pexpect = pytest.importorskip("pexpect")
    if os.name != "posix":
        pytest.skip("pty+tmux probe requires a POSIX pty")
    for tool in ("tmux", "ffmpeg", "kitten"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} is not on PATH")

    clip = tmp_path / "clip.mp4"
    generated = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=640x360:rate=30",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if generated.returncode != 0 or not clip.exists():
        pytest.skip(f"could not generate probe clip: {generated.stderr.strip()}")

    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    marker = tmp_path / "mpv-marker"
    shim = shim_dir / "mpv"
    shim.write_text(
        '#!/bin/sh\ntouch "$SASE_VIDEO_PROBE_MPV_MARKER"\nexit 0\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)

    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"TMUX", "TMUX_PANE"}
    }
    env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
    env["SASE_VIDEO_PROBE_MPV_MARKER"] = str(marker)

    socket = f"sase-video-probe-{os.getpid()}"
    try:
        assert (
            _tmux(
                socket,
                "-f",
                "/dev/null",
                "new-session",
                "-d",
                "-s",
                "probe",
                "-x",
                "120",
                "-y",
                "40",
                "/bin/sh",
                env=env,
            ).returncode
            == 0
        )
        assert (
            _tmux(
                socket, "set-option", "-s", "allow-passthrough", "all", env=env
            ).returncode
            == 0
        )
        assert (
            _tmux(
                socket,
                "set-option",
                "-t",
                "probe",
                "pane-border-status",
                "top",
                env=env,
            ).returncode
            == 0
        )
        assert (
            _tmux(
                socket,
                "set-option",
                "-t",
                "probe",
                "pane-border-format",
                "#{pane_title}",
                env=env,
            ).returncode
            == 0
        )
        assert (
            _tmux(
                socket, "select-pane", "-t", "probe", "-T", _SENTINEL_TITLE, env=env
            ).returncode
            == 0
        )

        log = io.BytesIO()
        child = pexpect.spawn(
            "tmux",
            ["-L", socket, "attach-session", "-t", "probe"],
            dimensions=(40, 120),
            encoding=None,
            timeout=30,
            env=env,
        )
        child.logfile_read = log
        try:
            fcntl.ioctl(
                child.child_fd, termios.TIOCSWINSZ, pack("HHHH", 40, 120, 1200, 800)
            )
            child.sendline(
                f"{sys.executable} -m sase.ace.tui.graphics.viewer --kind file {clip}"
            )
            child.expect(b"Viewing artifact", timeout=30)
            first_pixel = time.monotonic()
            child.expect(b"\x1b_G", timeout=10)
            assert time.monotonic() - first_pixel <= 1.0
            child.expect(b"\x1b_G", timeout=15)
            title = _tmux(
                socket, "display-message", "-p", "-t", "probe", "#{pane_title}", env=env
            )
            assert title.stdout.strip() == _SENTINEL_TITLE
            time.sleep(2.0)  # sase-test-wait: let scrub track and storyboard settle
            before_step = len(log.getvalue())
            child.send("l")
            stepped = time.monotonic()
            while time.monotonic() - stepped <= 0.3:
                data = log.getvalue()[before_step:]
                if b"\x1b_G" in data:
                    break
                time.sleep(0.02)  # sase-test-wait: poll pty log for kitty APC
            else:
                raise AssertionError("no kitty APC within 300 ms of an l press")
            for _ in range(9):
                child.send("l")
                time.sleep(0.05)  # sase-test-wait: space l presses for byte budget
            assert len(log.getvalue()) < _MAX_CLIENT_BYTES
            title = _tmux(
                socket, "display-message", "-p", "-t", "probe", "#{pane_title}", env=env
            )
            assert title.stdout.strip() == _SENTINEL_TITLE
            child.send("q")
            child.sendline("exit")
            child.expect(pexpect.EOF, timeout=15)
        finally:
            if child.isalive():
                child.terminate(force=True)
            child.close()

        payload = log.getvalue()
        assert payload.count(b"\x1b_G") >= 2
        assert len(payload) < _MAX_CLIENT_BYTES
        assert not marker.exists()
    finally:
        _tmux(socket, "kill-server", env=env)
