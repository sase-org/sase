"""In-pane motion and native-open builders for terminal video artifacts.

Deferred: only the inspect view (itself deferred off TUI first paint) imports
this module, so none of its names may be re-exported from the eager facades
(``graphics/__init__.py``, ``_viewer_loop.py``, ``viewer.py``).
"""

from __future__ import annotations

import base64
import os
import select
import shutil
import subprocess
import sys
import termios
import tty
from collections.abc import Sequence
from pathlib import Path

from ._viewer_loop_media import (
    video_still_preview_required,
    video_vo_uses_kitty_placement,
)
from ._viewer_loop_types import (
    VIDEO_PLAYBACK_BACKENDS,
    ArtifactVideoPlaybackConfig,
)
from ._viewer_types import ArtifactFileImageArea

_KITTY_SHM_CACHE: bool | None = None


def normalize_video_backend(backend: str) -> str:
    """Return a known backend, mapping unknown values onto ``auto``."""

    return backend if backend in VIDEO_PLAYBACK_BACKENDS else "auto"


def motion_playback_block_reason(
    config: ArtifactVideoPlaybackConfig,
    *,
    mpv_available: bool | None = None,
) -> str | None:
    """Return why in-pane motion is unavailable, or ``None`` when allowed.

    ``mpv`` and ``auto`` run only where the topology allows rendering: outside
    tmux, or with a non-kitty ``vo``. ``auto`` without mpv behaves like
    ``poster``; ``poster``, a forbidden topology, or ``mpv`` with mpv missing
    each name their reason.
    """

    backend = normalize_video_backend(config.backend)
    if backend == "poster":
        return "poster backend configured — scrub with h/l or 0–9"
    if video_still_preview_required(config):
        return "in-pane playback is unavailable here — scrub with h/l or 0–9"
    available = (
        shutil.which("mpv") is not None if mpv_available is None else mpv_available
    )
    if not available:
        if backend == "mpv":
            return "mpv is not installed — set backend to poster or install mpv"
        return "mpv is not installed — scrub with h/l or 0–9"
    return None


def _kitty_shm_available(
    vo: str,
    *,
    force: bool = False,
) -> bool:
    """Return whether the kitty shared-memory transport probed usable.

    The probe runs only outside tmux with a kitty ``vo``; every other
    topology returns False without touching the terminal. A successful probe
    is cached for the viewer process.
    """

    global _KITTY_SHM_CACHE
    from ._viewer_tmux_common import is_tmux_session

    if is_tmux_session() or not video_vo_uses_kitty_placement(vo):
        return False
    if _KITTY_SHM_CACHE is not None and not force:
        return _KITTY_SHM_CACHE
    probed = _probe_kitty_shm_once()
    _KITTY_SHM_CACHE = probed
    return probed


def _probe_kitty_shm_once() -> bool:
    """Run one kitty shared-memory capability probe against the tty."""

    try:
        from multiprocessing import shared_memory

        shm = shared_memory.SharedMemory(create=True, size=1024)
    except Exception:
        return False
    try:
        name_b64 = base64.b64encode(shm.name.encode("ascii")).decode("ascii")
        query = f"\x1b_Gi=31337,a=q,t=s,s=1,v=1,f=24;{name_b64}\x1b\\"
        reply = _kitty_shm_query_exchange(query, timeout=0.15)
        return reply is not None and "OK" in reply
    except Exception:
        return False
    finally:
        try:
            shm.close()
        except Exception:
            pass
        try:
            shm.unlink()
        except Exception:
            pass


def _kitty_shm_query_exchange(query: str, *, timeout: float) -> str | None:
    """Write a kitty query and read the reply within *timeout* seconds."""

    try:
        fd_in = sys.stdin.fileno()
        fd_out = sys.stdout.fileno()
    except (OSError, ValueError):
        return None
    try:
        old = termios.tcgetattr(fd_in)
    except (OSError, termios.error):
        return None
    try:
        tty.setraw(fd_in)
        os.write(fd_out, query.encode("utf-8", errors="ignore"))
        ready, _, _ = select.select([fd_in], [], [], timeout)
        if not ready:
            return None
        chunks: list[bytes] = []
        while True:
            ready, _, _ = select.select([fd_in], [], [], 0.02)
            if not ready:
                break
            try:
                chunk = os.read(fd_in, 4096)
            except OSError:
                break
            if not chunk:
                break
            chunks.append(chunk)
            text = b"".join(chunks).decode("utf-8", errors="ignore")
            if "OK" in text or "\x1b\\" in text or "\x07" in text:
                break
        return b"".join(chunks).decode("utf-8", errors="ignore") or None
    except (OSError, ValueError, termios.error):
        return None
    finally:
        try:
            termios.tcsetattr(fd_in, termios.TCSADRAIN, old)
        except (OSError, termios.error):
            pass


def artifact_video_motion_command(
    path: str | Path,
    image_area: ArtifactFileImageArea,
    config: ArtifactVideoPlaybackConfig | None = None,
    *,
    at_seconds: float = 0.0,
    shm_available: bool | None = None,
) -> list[str]:
    """Build the in-pane mpv motion command without touching player defaults.

    ``sase artifact open`` keeps using :func:`artifact_video_player_command`;
    this builder is the inspect view's ``space`` path: ``--no-config`` with the
    ``sw-fast`` profile, ``--start`` at the scrub timestamp, ``--audio=no``
    for the silent preview, kitty placement flags for a kitty ``vo``, and the
    probed ``--vo-kitty-use-shm`` flag. ``extra_mpv_args`` stay last.
    """

    expanded = Path(path).expanduser().resolve(strict=False)
    video_config = config or ArtifactVideoPlaybackConfig()
    vo = video_config.vo.strip() or "kitty"
    try:
        at = max(0.0, float(at_seconds))
    except (TypeError, ValueError):
        at = 0.0
    command = [
        "mpv",
        "--no-config",
        "--profile=sw-fast",
        f"--vo={vo}",
    ]
    if video_vo_uses_kitty_placement(vo):
        command.extend(
            [
                "--vo-kitty-alt-screen=no",
                "--vo-kitty-config-clear=no",
                f"--vo-kitty-left={max(0, image_area.left)}",
                f"--vo-kitty-top={max(0, image_area.top)}",
                f"--vo-kitty-cols={max(1, image_area.columns)}",
                f"--vo-kitty-rows={max(1, image_area.rows)}",
            ]
        )
        use_shm = (
            _kitty_shm_available(vo) if shm_available is None else bool(shm_available)
        )
        if use_shm:
            command.append("--vo-kitty-use-shm=yes")
    command.append(f"--start={at:.3f}")
    if not video_config.audio:
        command.append("--audio=no")
    if video_config.loop:
        command.append("--loop-file=inf")
    command.extend(video_config.extra_mpv_args)
    command.extend(["--", str(expanded)])
    return command


def build_native_open_command(
    path: str | Path,
    config: ArtifactVideoPlaybackConfig | None = None,
    *,
    platform: str | None = None,
    display: str | None = None,
    wayland_display: str | None = None,
    ssh_connection: str | None = None,
) -> tuple[list[str] | None, str | None]:
    """Return the native ``o``-key argv for *path*, or a notice when none fits.

    A configured ``open_command`` wins: ``{path}`` is substituted when present
    and the path is appended otherwise. Without it, macOS uses ``open`` and
    Linux uses ``xdg-open`` only with a local graphical session. The second
    tuple item is the user-facing notice when no player is available.
    """

    expanded = str(Path(path).expanduser().resolve(strict=False))
    video_config = config or ArtifactVideoPlaybackConfig()
    if video_config.open_command:
        template = [str(item) for item in video_config.open_command]
        if "{path}" in template:
            argv = [expanded if item == "{path}" else item for item in template]
        else:
            argv = [*template, expanded]
        return (argv, None)
    current = sys.platform if platform is None else platform
    if current == "darwin":
        return (["open", expanded], None)
    env_display = os.environ.get("DISPLAY") if display is None else display
    env_wayland = (
        os.environ.get("WAYLAND_DISPLAY")
        if wayland_display is None
        else wayland_display
    )
    env_ssh = (
        os.environ.get("SSH_CONNECTION") if ssh_connection is None else ssh_connection
    )
    if current.startswith("linux") and (env_display or env_wayland) and not env_ssh:
        return (["xdg-open", expanded], None)
    return (
        None,
        "no native player available here — set ace.artifact_file_viewer.video.open_command",
    )


__all__ = [
    "artifact_video_motion_command",
    "build_native_open_command",
    "motion_playback_block_reason",
    "normalize_video_backend",
]
