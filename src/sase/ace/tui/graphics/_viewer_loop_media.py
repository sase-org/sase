"""Text and video display helpers for artifact viewer loops."""

from __future__ import annotations

import base64
import json
import os
import select
import shlex
import shutil
import subprocess
import sys
import termios
import tty
from collections.abc import Callable, Sequence
from dataclasses import MISSING, asdict, fields
from pathlib import Path
from typing import Any

from ._viewer_loop_terminal import (
    clear_terminal,
    move_cursor_below_image,
    print_artifact_header,
)
from ._viewer_loop_types import (
    VIDEO_PLAYBACK_BACKENDS,
    ArtifactVideoPlaybackConfig,
    TextDisplayResult,
    VideoDisplayResult,
)
from ._viewer_render import validate_artifact_file_viewer_dependencies
from ._viewer_types import (
    ArtifactFileImageArea,
    ArtifactFileViewerWarning,
    ArtifactFileViewSpec,
)

ARTIFACT_VIEWER_VIDEO_CONFIG_ENV = "SASE_ARTIFACT_VIEWER_VIDEO_CONFIG"
_VIDEO_CONFIG_SNAPSHOT_VERSION = 1


def artifact_text_viewer_command(path: str | Path) -> list[str]:
    """Build the terminal command for displaying a raw artifact file."""

    expanded = Path(path).expanduser().resolve(strict=False)
    return [sys.executable, "-m", "sase", "pager", "--", str(expanded)]


def artifact_video_player_command(
    path: str | Path,
    image_area: ArtifactFileImageArea,
    config: ArtifactVideoPlaybackConfig | None = None,
) -> list[str]:
    """Build the bounded ``mpv`` command for a terminal video artifact."""

    expanded = Path(path).expanduser().resolve(strict=False)
    video_config = config or ArtifactVideoPlaybackConfig()
    vo = video_config.vo.strip() or "kitty"
    command = [
        "mpv",
        "--no-config",
        f"--vo={vo}",
        "--keep-open=yes",
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
    if not video_config.audio:
        command.append("--mute=yes")
    if video_config.loop:
        command.append("--loop-file=inf")
    command.extend(video_config.extra_mpv_args)
    command.extend(["--", str(expanded)])
    return command


def serialize_video_playback_config(config: ArtifactVideoPlaybackConfig) -> str:
    """Serialize *config* to the pane-child env snapshot JSON."""

    return json.dumps(
        {"version": _VIDEO_CONFIG_SNAPSHOT_VERSION, **asdict(config)},
        separators=(",", ":"),
    )


def parse_video_playback_config_env(
    raw: str | None,
) -> ArtifactVideoPlaybackConfig | None:
    """Parse a snapshot JSON object, or ``None`` when it cannot be used."""

    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(data, dict)
        or data.get("version") != _VIDEO_CONFIG_SNAPSHOT_VERSION
    ):
        return None
    kwargs: dict[str, Any] = {}
    for field in fields(ArtifactVideoPlaybackConfig):
        if field.name not in data:
            continue
        value = data[field.name]
        default = field.default
        if default is MISSING and field.default_factory is not MISSING:
            default = field.default_factory()
        if isinstance(default, bool):
            if not isinstance(value, bool):
                return None
            kwargs[field.name] = value
        elif isinstance(default, str):
            if not isinstance(value, str):
                return None
            kwargs[field.name] = value
        elif isinstance(default, tuple):
            if not isinstance(value, list | tuple):
                return None
            kwargs[field.name] = tuple(str(item) for item in value)
        else:
            kwargs[field.name] = value
    try:
        parsed = ArtifactVideoPlaybackConfig(**kwargs)
    except TypeError:
        return None
    if parsed.backend not in VIDEO_PLAYBACK_BACKENDS:
        return None
    return parsed


def load_merged_artifact_video_playback_config() -> ArtifactVideoPlaybackConfig:
    """Load terminal video playback settings from trust-evaluated merged config.

    Ignores ``SASE_ARTIFACT_VIEWER_VIDEO_CONFIG`` so a parent never re-emits a
    nested or stale child snapshot.
    """

    try:
        from sase.config import load_merged_config

        merged = load_merged_config()
    except Exception:
        return ArtifactVideoPlaybackConfig()

    if not isinstance(merged, dict):
        return ArtifactVideoPlaybackConfig()
    ace = merged.get("ace", {})
    if not isinstance(ace, dict):
        return ArtifactVideoPlaybackConfig()
    artifact_file_viewer = ace.get("artifact_file_viewer", {})
    if not isinstance(artifact_file_viewer, dict):
        return ArtifactVideoPlaybackConfig()
    raw_video = artifact_file_viewer.get("video", {})
    if not isinstance(raw_video, dict):
        return ArtifactVideoPlaybackConfig()

    return ArtifactVideoPlaybackConfig(
        audio=_coerce_bool(raw_video.get("audio"), default=False),
        backend=_coerce_backend(raw_video.get("backend")),
        loop=_coerce_bool(raw_video.get("loop"), default=False),
        vo=_coerce_str(raw_video.get("vo"), default="kitty"),
        extra_mpv_args=_coerce_mpv_args(raw_video.get("extra_mpv_args")),
        open_command=_coerce_open_command(raw_video.get("open_command")),
    )


def load_artifact_video_playback_config() -> ArtifactVideoPlaybackConfig:
    """Load video playback settings from the env snapshot, then merged config."""

    parsed = parse_video_playback_config_env(
        os.environ.get(ARTIFACT_VIEWER_VIDEO_CONFIG_ENV)
    )
    if parsed is not None:
        return parsed
    return load_merged_artifact_video_playback_config()


def video_vo_uses_kitty_placement(vo: str) -> bool:
    """Return whether an mpv ``vo`` value places frames with kitty graphics."""

    return vo.split(",", 1)[0].strip() == "kitty"


def video_still_preview_required(config: ArtifactVideoPlaybackConfig) -> bool:
    """Return whether a video must render as a still instead of mpv playback."""

    from ._viewer_tmux_common import is_tmux_session

    return is_tmux_session() and video_vo_uses_kitty_placement(config.vo)


def _coerce_bool(value: object, *, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _coerce_str(value: object, *, default: str) -> str:
    if not isinstance(value, str):
        return default
    stripped = value.strip()
    return stripped or default


def _coerce_mpv_args(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            return tuple(shlex.split(value))
        except ValueError:
            return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if item is not None)
    return ()


def _coerce_backend(value: object) -> str:
    """Coerce the motion backend, falling back to ``auto`` when unknown."""

    if isinstance(value, str) and value.strip() in VIDEO_PLAYBACK_BACKENDS:
        return value.strip()
    return "auto"


def _coerce_open_command(value: object) -> tuple[str, ...]:
    """Coerce ``open_command`` from an argv list or shlex string."""

    if value is None:
        return ()
    if isinstance(value, str):
        if not value.strip():
            return ()
        try:
            return tuple(shlex.split(value))
        except ValueError:
            return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if item is not None)
    return ()


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


def motion_playback_allowed(
    config: ArtifactVideoPlaybackConfig,
    *,
    mpv_available: bool | None = None,
) -> bool:
    """Return whether in-pane motion may run for *config*."""

    return motion_playback_block_reason(config, mpv_available=mpv_available) is None


_KITTY_SHM_CACHE: bool | None = None


def reset_kitty_shm_cache() -> None:
    """Clear the cached kitty shared-memory probe result (tests only)."""

    global _KITTY_SHM_CACHE
    _KITTY_SHM_CACHE = None


def kitty_shm_available(
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
            kitty_shm_available(vo) if shm_available is None else bool(shm_available)
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


def display_text_artifact(
    spec: ArtifactFileViewSpec,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]],
    *,
    artifact_index: int = 0,
    artifact_count: int = 1,
) -> TextDisplayResult:
    path = Path(spec.path).expanduser().resolve(strict=False)
    if not path.exists():
        warning = ArtifactFileViewerWarning(
            "artifact_not_found",
            "Artifact file not found",
        )
        return TextDisplayResult(warnings=(warning,))
    if not path.is_file():
        warning = ArtifactFileViewerWarning(
            "artifact_not_file",
            "Artifact path is not a file",
        )
        return TextDisplayResult(warnings=(warning,))

    clear_terminal()
    print_artifact_header(
        spec,
        page_index=0,
        page_count=1,
        artifact_index=artifact_index,
        artifact_count=artifact_count,
    )
    command = tuple(artifact_text_viewer_command(path))
    result = run_command(command)
    if result.returncode != 0:
        tool = Path(command[0]).name if command else None
        warning = ArtifactFileViewerWarning(
            "text_viewer_failed",
            f"{tool or 'text viewer'} failed with exit code {result.returncode}",
            tool=tool,
        )
        return TextDisplayResult(
            command=command,
            returncode=result.returncode,
            warnings=(warning,),
        )
    return TextDisplayResult(command=command, returncode=result.returncode)


def display_video_artifact(
    spec: ArtifactFileViewSpec,
    image_area: ArtifactFileImageArea,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]],
    *,
    video_config: ArtifactVideoPlaybackConfig,
    artifact_index: int = 0,
    artifact_count: int = 1,
    cache_root: str | Path | None = None,
) -> VideoDisplayResult:
    path = Path(spec.path).expanduser().resolve(strict=False)
    if not path.exists():
        warning = ArtifactFileViewerWarning(
            "artifact_not_found",
            "Artifact file not found",
        )
        return VideoDisplayResult(warnings=(warning,))
    if not path.is_file():
        warning = ArtifactFileViewerWarning(
            "artifact_not_file",
            "Artifact path is not a file",
        )
        return VideoDisplayResult(warnings=(warning,))

    if video_still_preview_required(video_config):
        # Deferred: the still/ffprobe module stays off the TUI import path.
        from ._viewer_video_media import display_video_still_artifact

        return display_video_still_artifact(
            spec,
            image_area,
            run_command,
            cache_root=cache_root,
            artifact_index=artifact_index,
            artifact_count=artifact_count,
        )

    warnings = validate_artifact_file_viewer_dependencies("video")
    if warnings:
        return VideoDisplayResult(warnings=warnings)

    clear_terminal()
    print_artifact_header(
        spec,
        page_index=0,
        page_count=1,
        artifact_index=artifact_index,
        artifact_count=artifact_count,
        media_label="\u25b6 Video",
    )
    move_cursor_below_image(image_area)
    command = tuple(artifact_video_player_command(path, image_area, video_config))
    result = run_command(command)
    move_cursor_below_image(image_area)
    return VideoDisplayResult(command=command, returncode=result.returncode)


def text_viewer_command_needs_quit_key(command: Sequence[str]) -> bool:
    return False
