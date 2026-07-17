"""Terminal primitives for artifact viewer loops."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import termios
import tty
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from ._viewer_types import (
    ArtifactFileImageArea,
    ArtifactFileViewerResult,
    ArtifactFileViewerWarning,
    ArtifactFileViewSpec,
)

_ARTIFACT_VIEWER_RESERVED_ROWS = 7
_ARTIFACT_VIEWER_HEADER_ROWS = 5
_ARTIFACT_VIEWER_RESERVED_COLUMNS = 2
_PAGE_LOOP_RESERVED_ROWS = 2
_MIN_IMAGE_COLUMNS = 20
_MIN_IMAGE_ROWS = 5
_RETURN_TO_ACE_KEY = "\t"
_FOOTER_RESET = "\x1b[0m"
_FOOTER_COLOR = "\x1b[38;2;215;175;95m"


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


def run_command(cmd: Sequence[str]) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(list(cmd), check=False)


def select_tmux_pane(pane_id: str) -> ArtifactFileViewerResult:
    from ._viewer_launch import select_tmux_pane

    return select_tmux_pane(pane_id)


def toggle_tmux_zoom() -> ArtifactFileViewerResult:
    from ._viewer_launch import toggle_artifact_file_tmux_pane_zoom

    return toggle_artifact_file_tmux_pane_zoom()


def tmux_zoom_available() -> bool:
    return bool(os.environ.get("TMUX") or os.environ.get("TMUX_PANE"))


def artifact_image_area(
    terminal_size: os.terminal_size | tuple[int, int] | None = None,
    *,
    reserved_rows: int = _ARTIFACT_VIEWER_RESERVED_ROWS,
    reserved_columns: int = _ARTIFACT_VIEWER_RESERVED_COLUMNS,
    top_rows: int = _ARTIFACT_VIEWER_HEADER_ROWS,
) -> ArtifactFileImageArea:
    """Return the terminal cell area available for artifact image display."""

    size = terminal_size or shutil.get_terminal_size(fallback=(80, 24))
    lines = int(size[1])
    columns = max(_MIN_IMAGE_COLUMNS, int(size[0]) - max(0, reserved_columns))
    rows = max(_MIN_IMAGE_ROWS, lines - reserved_rows)
    top = min(max(0, top_rows), max(0, lines - rows))
    return ArtifactFileImageArea(columns=columns, rows=rows, top=top)


def kitten_icat_command(page: Path, image_area: ArtifactFileImageArea) -> list[str]:
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


def clear_terminal(
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]],
) -> None:
    run_command(["clear"])


def move_cursor_below_image(image_area: ArtifactFileImageArea) -> None:
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
    spec: ArtifactFileViewSpec,
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


def print_artifact_header(
    spec: ArtifactFileViewSpec,
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


def print_artifact_warning(warning: ArtifactFileViewerWarning) -> None:
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


def read_single_key() -> str:
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return os.read(fd, 1).decode(errors="ignore")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
