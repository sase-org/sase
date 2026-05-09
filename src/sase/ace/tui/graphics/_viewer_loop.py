"""Interactive terminal loops for displaying rendered artifact pages."""

from __future__ import annotations

import os
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

from ._viewer_render import render_artifact_pages
from ._viewer_types import (
    ArtifactImageArea,
    ArtifactRenderResult,
    ArtifactViewerWarning,
    ArtifactViewSpec,
)


@dataclass(frozen=True)
class _PageLoopResult:
    """Terminal page loop subprocess status."""

    returncode: int = 0
    warnings: tuple[ArtifactViewerWarning, ...] = ()


_ARTIFACT_VIEWER_RESERVED_ROWS = 7
_ARTIFACT_VIEWER_HEADER_ROWS = 5
_ARTIFACT_VIEWER_RESERVED_COLUMNS = 2
_PAGE_LOOP_RESERVED_ROWS = 2
_MIN_IMAGE_COLUMNS = 20
_MIN_IMAGE_ROWS = 5
_FOOTER_RESET = "\x1b[0m"
_FOOTER_COLOR = "\x1b[38;2;215;175;95m"


def page_index_after_key(current_index: int, key: str, page_count: int) -> int | None:
    """Return the next page index, or ``None`` when the loop should quit."""

    normalized = key.lower()
    if normalized == "q":
        return None
    if normalized == "r":
        return current_index
    if page_count <= 1:
        return current_index
    if normalized == "n":
        return (current_index + 1) % page_count
    if normalized == "p":
        return (current_index - 1) % page_count
    return current_index


def page_loop_available_keys(
    index: int,
    page_count: int,
    *,
    artifact_index: int = 0,
    artifact_count: int = 1,
) -> tuple[str, ...]:
    """Return page-loop keys available for the current page."""

    keys: list[str] = []
    if page_count > 1:
        keys.append("n")
        keys.append("p")
    if artifact_index < artifact_count - 1:
        keys.append("N")
    if artifact_index > 0:
        keys.append("P")
    if page_count > 0:
        keys.append("r")
    keys.append("q")
    return tuple(keys)


def run_artifact_page_loop(
    pages: Sequence[Path],
    *,
    read_key: Callable[[], str] | None = None,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]]
    | None = None,
    image_area: ArtifactImageArea | None = None,
) -> _PageLoopResult:
    """Display rendered pages with ``kitten icat`` and a small key loop."""

    if not pages:
        return _PageLoopResult(returncode=1)

    read = read_key or _read_single_key
    run = run_command or _run_command
    index = 0
    while True:
        current_area = image_area or artifact_image_area(
            reserved_rows=_PAGE_LOOP_RESERVED_ROWS,
            top_rows=0,
        )
        _clear_terminal(run)
        result = run(kitten_icat_command(pages[index], current_area))
        if result.returncode != 0:
            return _PageLoopResult(returncode=result.returncode)
        _move_cursor_below_image(current_area)
        print_page_prompt(index=index, page_count=len(pages))
        available_keys = page_loop_available_keys(index, len(pages))
        while (key := read()) not in available_keys:
            pass
        next_index = page_index_after_key(index, key, len(pages))
        print()
        if next_index is None:
            _clear_terminal(run)
            return _PageLoopResult()
        index = next_index


def run_artifact_sequence_loop(
    artifacts: Sequence[ArtifactViewSpec],
    *,
    cache_root: str | Path,
    read_key: Callable[[], str] | None = None,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]]
    | None = None,
    image_area: ArtifactImageArea | None = None,
) -> _PageLoopResult:
    """Display an artifact sequence with page and document navigation."""

    specs = tuple(artifacts)
    if not specs:
        return _PageLoopResult(returncode=1)

    read = read_key or _read_single_key
    run = run_command or _run_command
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
    while True:
        current_area = image_area or artifact_image_area()
        rendered = pages_for(artifact_index, current_area)
        if rendered.warnings:
            return _PageLoopResult(returncode=1, warnings=rendered.warnings)
        pages = rendered.pages
        if not pages:
            return _PageLoopResult(returncode=1)

        _clear_terminal(run)
        _print_artifact_header(
            specs[artifact_index],
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
        )
        available_keys = page_loop_available_keys(
            page_index,
            len(pages),
            artifact_index=artifact_index,
            artifact_count=len(specs),
        )
        while (key := read()) not in available_keys:
            pass
        print()
        if key == "q":
            _clear_terminal(run)
            return _PageLoopResult()
        if key in {"n", "p", "r"}:
            next_page_index = page_index_after_key(page_index, key, len(pages))
            if next_page_index is None:
                _clear_terminal(run)
                return _PageLoopResult()
            page_index = next_page_index
        elif key == "N":
            artifact_index = min(artifact_index + 1, len(specs) - 1)
            page_index = 0
        elif key == "P":
            artifact_index = max(artifact_index - 1, 0)
            page_index = 0


def _run_command(cmd: Sequence[str]) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(list(cmd), check=False)


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
        )
    )


def print_page_prompt(
    *,
    index: int,
    page_count: int,
    artifact_index: int = 0,
    artifact_count: int = 1,
    show_position: bool = True,
) -> None:
    labels = {
        "n": "n: next page",
        "p": "p: previous page",
        "N": "N: next artifact",
        "P": "P: previous artifact",
        "r": "r: refresh",
        "q": "q: quit",
    }
    actions = "  ".join(
        labels[key]
        for key in page_loop_available_keys(
            index,
            page_count,
            artifact_index=artifact_index,
            artifact_count=artifact_count,
        )
    )
    prompt = actions
    if show_position:
        prompt = f"Page {index + 1}/{page_count}  {prompt}"
    if show_position and artifact_count > 1:
        prompt = f"Artifact {artifact_index + 1}/{artifact_count}  {prompt}"
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
