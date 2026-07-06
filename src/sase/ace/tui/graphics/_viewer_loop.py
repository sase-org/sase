"""Interactive terminal loops for displaying rendered artifact pages."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import termios
import tty
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from ._viewer_render import (
    artifact_view_mode,
    render_artifact_pages,
    validate_artifact_viewer_dependencies,
)
from ._viewer_types import (
    ArtifactImageArea,
    ArtifactRenderResult,
    ArtifactViewerResult,
    ArtifactViewerWarning,
    ArtifactViewSpec,
)


@dataclass(frozen=True)
class _PageLoopResult:
    """Terminal page loop subprocess status."""

    returncode: int = 0
    warnings: tuple[ArtifactViewerWarning, ...] = ()


@dataclass(frozen=True)
class _TextDisplayResult:
    """Terminal text viewer subprocess status."""

    command: tuple[str, ...] = ()
    returncode: int = 0
    warnings: tuple[ArtifactViewerWarning, ...] = ()


@dataclass(frozen=True)
class ArtifactVideoPlaybackConfig:
    """Runtime settings for terminal video artifact playback."""

    audio: bool = False
    loop: bool = False
    vo: str = "kitty"
    extra_mpv_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class _VideoDisplayResult:
    """Terminal video player subprocess status."""

    command: tuple[str, ...] = ()
    returncode: int = 0
    warnings: tuple[ArtifactViewerWarning, ...] = ()


_ARTIFACT_VIEWER_RESERVED_ROWS = 7
_ARTIFACT_VIEWER_HEADER_ROWS = 5
_ARTIFACT_VIEWER_RESERVED_COLUMNS = 2
_PAGE_LOOP_RESERVED_ROWS = 2
_MIN_IMAGE_COLUMNS = 20
_MIN_IMAGE_ROWS = 5
_RETURN_TO_ACE_KEY = "\t"
_FOOTER_RESET = "\x1b[0m"
_FOOTER_COLOR = "\x1b[38;2;215;175;95m"


def artifact_text_viewer_command(path: str | Path) -> list[str]:
    """Build the terminal command for displaying a raw artifact file."""

    expanded = Path(path).expanduser().resolve(strict=False)
    if shutil.which("bat") is not None:
        return [
            "bat",
            "--paging=always",
            "--color=always",
            "--decorations=always",
            "--",
            str(expanded),
        ]
    return ["cat", str(expanded)]


def artifact_video_player_command(
    path: str | Path,
    image_area: ArtifactImageArea,
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
    if _video_vo_uses_kitty_placement(vo):
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


def load_artifact_video_playback_config() -> ArtifactVideoPlaybackConfig:
    """Load terminal video playback settings from merged SASE config."""

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
    artifact_viewer = ace.get("artifact_viewer", {})
    if not isinstance(artifact_viewer, dict):
        return ArtifactVideoPlaybackConfig()
    raw_video = artifact_viewer.get("video", {})
    if not isinstance(raw_video, dict):
        return ArtifactVideoPlaybackConfig()

    return ArtifactVideoPlaybackConfig(
        audio=_coerce_bool(raw_video.get("audio"), default=False),
        loop=_coerce_bool(raw_video.get("loop"), default=False),
        vo=_coerce_str(raw_video.get("vo"), default="kitty"),
        extra_mpv_args=_coerce_mpv_args(raw_video.get("extra_mpv_args")),
    )


def _video_vo_uses_kitty_placement(vo: str) -> bool:
    return vo.split(",", 1)[0].strip() == "kitty"


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


def run_artifact_text_viewer(
    artifact: ArtifactViewSpec,
    *,
    read_key: Callable[[], str] | None = None,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]]
    | None = None,
    return_pane_id: str | None = None,
    select_pane: Callable[[str], ArtifactViewerResult] | None = None,
) -> _PageLoopResult:
    """Display one raw artifact file with ``bat`` or ``cat``."""

    read = read_key or _read_single_key
    run = run_command or _run_command
    select = select_pane or _select_tmux_pane
    displayed = _display_text_artifact(artifact, run)
    if displayed.warnings:
        return _PageLoopResult(returncode=1, warnings=displayed.warnings)
    if displayed.returncode != 0:
        return _PageLoopResult(returncode=displayed.returncode)
    if not _text_viewer_command_needs_quit_key(displayed.command):
        return _PageLoopResult()

    print_text_prompt(return_pane_available=bool(return_pane_id))
    while True:
        key = read()
        if key == _RETURN_TO_ACE_KEY and return_pane_id:
            select(return_pane_id)
            continue
        if key.lower() == "q":
            _clear_terminal(run)
            return _PageLoopResult()


def page_index_after_key(current_index: int, key: str, page_count: int) -> int | None:
    """Return the next page index, or ``None`` when the loop should quit."""

    normalized = key.lower()
    if normalized == "q":
        return None
    if normalized in {"r", "z"}:
        return current_index
    if page_count <= 1:
        return current_index
    if normalized == "j":
        return (current_index + 1) % page_count
    if normalized == "k":
        return (current_index - 1) % page_count
    return current_index


def page_loop_available_keys(
    index: int,
    page_count: int,
    *,
    artifact_index: int = 0,
    artifact_count: int = 1,
    return_pane_available: bool = False,
    tmux_zoom_available: bool = False,
) -> tuple[str, ...]:
    """Return page-loop keys available for the current page."""

    keys: list[str] = []
    if return_pane_available:
        keys.append(_RETURN_TO_ACE_KEY)
    if page_count > 1:
        keys.append("j")
        keys.append("k")
    if artifact_index < artifact_count - 1:
        keys.append("n")
    if artifact_index > 0:
        keys.append("p")
    if page_count > 0:
        keys.append("r")
        if tmux_zoom_available:
            keys.append("z")
    keys.append("q")
    return tuple(keys)


def run_artifact_page_loop(
    pages: Sequence[Path],
    *,
    read_key: Callable[[], str] | None = None,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]]
    | None = None,
    image_area: ArtifactImageArea | None = None,
    return_pane_id: str | None = None,
    select_pane: Callable[[str], ArtifactViewerResult] | None = None,
    tmux_zoom_available: bool | None = None,
    toggle_zoom: Callable[[], ArtifactViewerResult] | None = None,
) -> _PageLoopResult:
    """Display rendered pages with ``kitten icat`` and a small key loop."""

    if not pages:
        return _PageLoopResult(returncode=1)

    read = read_key or _read_single_key
    run = run_command or _run_command
    select = select_pane or _select_tmux_pane
    zoom = toggle_zoom or _toggle_tmux_zoom
    index = 0
    needs_render = True
    return_pane_available = bool(return_pane_id)
    zoom_available = (
        _tmux_zoom_available() if tmux_zoom_available is None else tmux_zoom_available
    )
    while True:
        current_area = image_area or artifact_image_area(
            reserved_rows=_PAGE_LOOP_RESERVED_ROWS,
            top_rows=0,
        )
        if needs_render:
            _clear_terminal(run)
            result = run(kitten_icat_command(pages[index], current_area))
            if result.returncode != 0:
                return _PageLoopResult(returncode=result.returncode)
            _move_cursor_below_image(current_area)
            print_page_prompt(
                index=index,
                page_count=len(pages),
                return_pane_available=return_pane_available,
                tmux_zoom_available=zoom_available,
            )
            needs_render = False
        available_keys = page_loop_available_keys(
            index,
            len(pages),
            return_pane_available=return_pane_available,
            tmux_zoom_available=zoom_available,
        )
        while (key := read()) not in available_keys:
            pass
        if key == _RETURN_TO_ACE_KEY and return_pane_id:
            select(return_pane_id)
            continue
        print()
        if key == "z":
            zoom_result = zoom()
            if not zoom_result.ok:
                return _PageLoopResult(returncode=1, warnings=zoom_result.warnings)
            needs_render = True
            continue
        next_index = page_index_after_key(index, key, len(pages))
        if next_index is None:
            _clear_terminal(run)
            return _PageLoopResult()
        index = next_index
        needs_render = True


def run_artifact_sequence_loop(
    artifacts: Sequence[ArtifactViewSpec],
    *,
    cache_root: str | Path,
    read_key: Callable[[], str] | None = None,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]]
    | None = None,
    image_area: ArtifactImageArea | None = None,
    return_pane_id: str | None = None,
    select_pane: Callable[[str], ArtifactViewerResult] | None = None,
    tmux_zoom_available: bool | None = None,
    toggle_zoom: Callable[[], ArtifactViewerResult] | None = None,
    video_config: ArtifactVideoPlaybackConfig | None = None,
) -> _PageLoopResult:
    """Display an artifact sequence with page and document navigation."""

    specs = tuple(artifacts)
    if not specs:
        return _PageLoopResult(returncode=1)

    read = read_key or _read_single_key
    run = run_command or _run_command
    select = select_pane or _select_tmux_pane
    zoom = toggle_zoom or _toggle_tmux_zoom
    root = Path(cache_root).expanduser()
    page_cache: dict[tuple[int, int, int], tuple[Path, ...]] = {}

    def pages_for(index: int, area: ArtifactImageArea) -> ArtifactRenderResult:
        cache_key = (index, area.columns, area.rows)
        if cache_key in page_cache:
            return ArtifactRenderResult(page_cache[cache_key])
        spec = specs[index]
        rendered = render_artifact_pages(
            spec.path,
            kind=spec.kind,
            cache_dir=root / f"artifact-{index}",
            image_area=area,
        )
        if not rendered.warnings:
            page_cache[cache_key] = rendered.pages
        return rendered

    artifact_index = 0
    page_index = 0
    needs_render = True
    return_pane_available = bool(return_pane_id)
    zoom_available = (
        _tmux_zoom_available() if tmux_zoom_available is None else tmux_zoom_available
    )
    pages: tuple[Path, ...] = ()
    current_mode = artifact_view_mode(
        specs[artifact_index].path,
        kind=specs[artifact_index].kind,
    )
    resolved_video_config = video_config
    while True:
        current_area = image_area or artifact_image_area()
        if needs_render:
            spec = specs[artifact_index]
            current_mode = artifact_view_mode(spec.path, kind=spec.kind)
            if current_mode is None:
                warning = ArtifactViewerWarning(
                    "unsupported_artifact_kind",
                    "Unsupported artifact type",
                )
                return _PageLoopResult(returncode=1, warnings=(warning,))
            if current_mode == "text":
                page_index = 0
                pages = ()
                displayed = _display_text_artifact(
                    spec,
                    run,
                    artifact_index=artifact_index,
                    artifact_count=len(specs),
                )
                if displayed.warnings:
                    return _PageLoopResult(
                        returncode=1,
                        warnings=displayed.warnings,
                    )
                if displayed.returncode != 0:
                    return _PageLoopResult(returncode=displayed.returncode)
                print_page_prompt(
                    index=0,
                    page_count=1,
                    artifact_index=artifact_index,
                    artifact_count=len(specs),
                    show_position=False,
                    return_pane_available=return_pane_available,
                )
            elif current_mode == "video":
                page_index = 0
                pages = ()
                if resolved_video_config is None:
                    resolved_video_config = load_artifact_video_playback_config()
                video_displayed = _display_video_artifact(
                    spec,
                    current_area,
                    run,
                    video_config=resolved_video_config,
                    artifact_index=artifact_index,
                    artifact_count=len(specs),
                )
                if video_displayed.warnings:
                    return _PageLoopResult(
                        returncode=1,
                        warnings=video_displayed.warnings,
                    )
                if video_displayed.returncode != 0:
                    _print_artifact_warning(
                        ArtifactViewerWarning(
                            "mpv_failed",
                            f"mpv failed with exit code {video_displayed.returncode}",
                            tool="mpv",
                        )
                    )
                print_page_prompt(
                    index=0,
                    page_count=1,
                    artifact_index=artifact_index,
                    artifact_count=len(specs),
                    show_position=False,
                    return_pane_available=return_pane_available,
                    tmux_zoom_available=zoom_available,
                )
            else:
                rendered = pages_for(artifact_index, current_area)
                if rendered.warnings:
                    return _PageLoopResult(returncode=1, warnings=rendered.warnings)
                pages = rendered.pages
                if not pages:
                    return _PageLoopResult(returncode=1)

                _clear_terminal(run)
                _print_artifact_header(
                    spec,
                    page_index=page_index,
                    page_count=len(pages),
                    artifact_index=artifact_index,
                    artifact_count=len(specs),
                )
                result = run(kitten_icat_command(pages[page_index], current_area))
                if result.returncode != 0:
                    return _PageLoopResult(returncode=result.returncode)
                _move_cursor_below_image(current_area)
                print_page_prompt(
                    index=page_index,
                    page_count=len(pages),
                    artifact_index=artifact_index,
                    artifact_count=len(specs),
                    show_position=False,
                    return_pane_available=return_pane_available,
                    tmux_zoom_available=zoom_available,
                )
            needs_render = False
        is_text_mode = current_mode == "text"
        is_video_mode = current_mode == "video"
        page_key_index = 0 if is_text_mode or is_video_mode else page_index
        page_key_count = 1 if is_text_mode or is_video_mode else len(pages)
        available_keys = page_loop_available_keys(
            page_key_index,
            page_key_count,
            artifact_index=artifact_index,
            artifact_count=len(specs),
            return_pane_available=return_pane_available,
            tmux_zoom_available=False if is_text_mode else zoom_available,
        )
        while (key := read()) not in available_keys:
            pass
        if key == "q":
            _clear_terminal(run)
            return _PageLoopResult()
        if key == _RETURN_TO_ACE_KEY and return_pane_id:
            select(return_pane_id)
            continue
        print()
        needs_render = True
        if key == "z" and not is_text_mode:
            zoom_result = zoom()
            if not zoom_result.ok:
                return _PageLoopResult(returncode=1, warnings=zoom_result.warnings)
        elif key in {"j", "k", "r"}:
            if is_text_mode or is_video_mode:
                page_index = 0
                continue
            next_page_index = page_index_after_key(page_index, key, len(pages))
            if next_page_index is None:
                _clear_terminal(run)
                return _PageLoopResult()
            page_index = next_page_index
        elif key == "n":
            artifact_index = min(artifact_index + 1, len(specs) - 1)
            page_index = 0
        elif key == "p":
            artifact_index = max(artifact_index - 1, 0)
            page_index = 0


def _run_command(cmd: Sequence[str]) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(list(cmd), check=False)


def _select_tmux_pane(pane_id: str) -> ArtifactViewerResult:
    from ._viewer_launch import select_tmux_pane

    return select_tmux_pane(pane_id)


def _toggle_tmux_zoom() -> ArtifactViewerResult:
    from ._viewer_launch import toggle_artifact_tmux_pane_zoom

    return toggle_artifact_tmux_pane_zoom()


def _tmux_zoom_available() -> bool:
    return bool(os.environ.get("TMUX") or os.environ.get("TMUX_PANE"))


def artifact_image_area(
    terminal_size: os.terminal_size | tuple[int, int] | None = None,
    *,
    reserved_rows: int = _ARTIFACT_VIEWER_RESERVED_ROWS,
    reserved_columns: int = _ARTIFACT_VIEWER_RESERVED_COLUMNS,
    top_rows: int = _ARTIFACT_VIEWER_HEADER_ROWS,
) -> ArtifactImageArea:
    """Return the terminal cell area available for artifact image display."""

    size = terminal_size or shutil.get_terminal_size(fallback=(80, 24))
    lines = int(size[1])
    columns = max(_MIN_IMAGE_COLUMNS, int(size[0]) - max(0, reserved_columns))
    rows = max(_MIN_IMAGE_ROWS, lines - reserved_rows)
    top = min(max(0, top_rows), max(0, lines - rows))
    return ArtifactImageArea(columns=columns, rows=rows, top=top)


def kitten_icat_command(page: Path, image_area: ArtifactImageArea) -> list[str]:
    """Build a bounded ``kitten icat`` command for the current viewer area."""

    return [
        "kitten",
        "icat",
        "--scale-up",
        "--align",
        "left",
        "--place",
        f"{image_area.columns}x{image_area.rows}@{image_area.left}x{image_area.top}",
        str(page),
    ]


def _display_text_artifact(
    spec: ArtifactViewSpec,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]],
    *,
    artifact_index: int = 0,
    artifact_count: int = 1,
) -> _TextDisplayResult:
    path = Path(spec.path).expanduser().resolve(strict=False)
    if not path.exists():
        warning = ArtifactViewerWarning(
            "artifact_not_found",
            "Artifact file not found",
        )
        return _TextDisplayResult(warnings=(warning,))
    if not path.is_file():
        warning = ArtifactViewerWarning(
            "artifact_not_file",
            "Artifact path is not a file",
        )
        return _TextDisplayResult(warnings=(warning,))

    _clear_terminal(run_command)
    _print_artifact_header(
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
        warning = ArtifactViewerWarning(
            "text_viewer_failed",
            f"{tool or 'text viewer'} failed with exit code {result.returncode}",
            tool=tool,
        )
        return _TextDisplayResult(
            command=command,
            returncode=result.returncode,
            warnings=(warning,),
        )
    return _TextDisplayResult(command=command, returncode=result.returncode)


def _display_video_artifact(
    spec: ArtifactViewSpec,
    image_area: ArtifactImageArea,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]],
    *,
    video_config: ArtifactVideoPlaybackConfig,
    artifact_index: int = 0,
    artifact_count: int = 1,
) -> _VideoDisplayResult:
    path = Path(spec.path).expanduser().resolve(strict=False)
    if not path.exists():
        warning = ArtifactViewerWarning(
            "artifact_not_found",
            "Artifact file not found",
        )
        return _VideoDisplayResult(warnings=(warning,))
    if not path.is_file():
        warning = ArtifactViewerWarning(
            "artifact_not_file",
            "Artifact path is not a file",
        )
        return _VideoDisplayResult(warnings=(warning,))

    warnings = validate_artifact_viewer_dependencies("video")
    if warnings:
        return _VideoDisplayResult(warnings=warnings)

    _clear_terminal(run_command)
    _print_artifact_header(
        spec,
        page_index=0,
        page_count=1,
        artifact_index=artifact_index,
        artifact_count=artifact_count,
        media_label="▶ Video",
    )
    _move_cursor_below_image(image_area)
    command = tuple(artifact_video_player_command(path, image_area, video_config))
    result = run_command(command)
    _move_cursor_below_image(image_area)
    return _VideoDisplayResult(command=command, returncode=result.returncode)


def _text_viewer_command_needs_quit_key(command: Sequence[str]) -> bool:
    return bool(command) and Path(command[0]).name == "cat"


def _clear_terminal(
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]],
) -> None:
    run_command(["clear"])


def _move_cursor_below_image(image_area: ArtifactImageArea) -> None:
    """Move the terminal cursor so the prompt prints below a placed image."""

    row = max(1, image_area.top + image_area.rows)
    column = max(1, image_area.left + 1)
    sys.stdout.write(f"\x1b[{row};{column}H")
    sys.stdout.flush()


def format_artifact_header_path(path: str | Path) -> str:
    expanded = Path(path).expanduser()
    try:
        return str(expanded.resolve(strict=False))
    except OSError:
        return str(expanded)


def artifact_header_panel(
    spec: ArtifactViewSpec,
    *,
    page_index: int,
    page_count: int,
    artifact_index: int = 0,
    artifact_count: int = 1,
    media_label: str | None = None,
) -> Panel:
    metadata = Text()
    if artifact_count > 1:
        metadata.append(
            f"Artifact {artifact_index + 1}/{artifact_count}",
            style="gold1",
        )
    if page_count > 1:
        if metadata:
            metadata.append("  ")
        metadata.append(f"Page {page_index + 1}/{page_count}", style="gold1")
    if media_label:
        if metadata:
            metadata.append("  ")
        metadata.append(media_label, style="gold1")

    body = Text()
    if metadata:
        body.append_text(metadata)
        body.append("\n")
    artifact_name = Path(spec.path).expanduser().name
    formatted_path = format_artifact_header_path(spec.path)
    if artifact_name:
        body.append(artifact_name, style="bold cyan")
        if formatted_path != artifact_name:
            body.append("\n")
    body.append(formatted_path, style="cyan")

    return Panel(
        body,
        title=Text("Viewing artifact", style="bold gold1"),
        border_style="gold1",
        padding=(0, 1),
        expand=True,
    )


def _print_artifact_header(
    spec: ArtifactViewSpec,
    *,
    page_index: int,
    page_count: int,
    artifact_index: int = 0,
    artifact_count: int = 1,
    media_label: str | None = None,
    console: Console | None = None,
) -> None:
    target = console or Console()
    target.print(
        artifact_header_panel(
            spec,
            page_index=page_index,
            page_count=page_count,
            artifact_index=artifact_index,
            artifact_count=artifact_count,
            media_label=media_label,
        )
    )


def _print_artifact_warning(warning: ArtifactViewerWarning) -> None:
    Console().print(Panel(warning.message, style="bold yellow", expand=False))


def print_page_prompt(
    *,
    index: int,
    page_count: int,
    artifact_index: int = 0,
    artifact_count: int = 1,
    show_position: bool = True,
    return_pane_available: bool = False,
    tmux_zoom_available: bool = False,
) -> None:
    labels = {
        "j": "j: next page",
        "k": "k: previous page",
        "n": "n: next artifact",
        "p": "p: previous artifact",
        _RETURN_TO_ACE_KEY: "<tab>: focus SASE TUI",
        "r": "r: refresh",
        "z": "z: zoom",
        "q": "q: quit",
    }
    actions = "  ".join(
        labels[key]
        for key in page_loop_available_keys(
            index,
            page_count,
            artifact_index=artifact_index,
            artifact_count=artifact_count,
            return_pane_available=return_pane_available,
            tmux_zoom_available=tmux_zoom_available,
        )
    )
    prompt = actions
    if show_position:
        prompt = f"Page {index + 1}/{page_count}  {prompt}"
    if show_position and artifact_count > 1:
        prompt = f"Artifact {artifact_index + 1}/{artifact_count}  {prompt}"
    sys.stdout.write(f"{_FOOTER_RESET}\n{_FOOTER_COLOR}{prompt}{_FOOTER_RESET}")
    sys.stdout.flush()


def print_text_prompt(*, return_pane_available: bool = False) -> None:
    labels = []
    if return_pane_available:
        labels.append("<tab>: focus SASE TUI")
    labels.append("q: quit")
    prompt = "  ".join(labels)
    sys.stdout.write(f"{_FOOTER_RESET}\n{_FOOTER_COLOR}{prompt}{_FOOTER_RESET}")
    sys.stdout.flush()


def _read_single_key() -> str:
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return os.read(fd, 1).decode(errors="ignore")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
