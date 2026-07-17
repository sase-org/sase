"""Single-artifact terminal loops for artifact viewer pages."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ._viewer_loop_media import (
    display_text_artifact,
    text_viewer_command_needs_quit_key,
)
from ._viewer_loop_terminal import (
    _PAGE_LOOP_RESERVED_ROWS,
    _RETURN_TO_ACE_KEY,
    artifact_image_area,
    clear_terminal,
    kitten_icat_command,
    move_cursor_below_image,
    page_index_after_key,
    page_loop_available_keys,
    print_page_prompt,
    print_text_prompt,
    read_single_key,
    run_command as default_run_command,
    select_tmux_pane,
    tmux_zoom_available as tmux_zoom_is_available,
    toggle_tmux_zoom,
)
from ._viewer_loop_types import PageLoopResult
from ._viewer_types import (
    ArtifactFileImageArea,
    ArtifactFileViewerResult,
    ArtifactFileViewSpec,
)


def run_artifact_text_viewer(
    artifact: ArtifactFileViewSpec,
    *,
    read_key: Callable[[], str] | None = None,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]]
    | None = None,
    return_pane_id: str | None = None,
    select_pane: Callable[[str], ArtifactFileViewerResult] | None = None,
) -> PageLoopResult:
    """Display one raw artifact file with ``bat`` or ``cat``."""

    read = read_key or read_single_key
    run = run_command or default_run_command
    select = select_pane or select_tmux_pane
    displayed = display_text_artifact(artifact, run)
    if displayed.warnings:
        return PageLoopResult(returncode=1, warnings=displayed.warnings)
    if displayed.returncode != 0:
        return PageLoopResult(returncode=displayed.returncode)
    if not text_viewer_command_needs_quit_key(displayed.command):
        return PageLoopResult()

    print_text_prompt(return_pane_available=bool(return_pane_id))
    while True:
        key = read()
        if key == _RETURN_TO_ACE_KEY and return_pane_id:
            select(return_pane_id)
            continue
        if key.lower() == "q":
            clear_terminal(run)
            return PageLoopResult()


def run_artifact_page_loop(
    pages: Sequence[Path],
    *,
    read_key: Callable[[], str] | None = None,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]]
    | None = None,
    image_area: ArtifactFileImageArea | None = None,
    return_pane_id: str | None = None,
    select_pane: Callable[[str], ArtifactFileViewerResult] | None = None,
    tmux_zoom_available: bool | None = None,
    toggle_zoom: Callable[[], ArtifactFileViewerResult] | None = None,
) -> PageLoopResult:
    """Display rendered pages with ``kitten icat`` and a small key loop."""

    if not pages:
        return PageLoopResult(returncode=1)

    read = read_key or read_single_key
    run = run_command or default_run_command
    select = select_pane or select_tmux_pane
    zoom = toggle_zoom or toggle_tmux_zoom
    index = 0
    needs_render = True
    return_pane_available = bool(return_pane_id)
    zoom_available = (
        tmux_zoom_is_available() if tmux_zoom_available is None else tmux_zoom_available
    )
    while True:
        current_area = image_area or artifact_image_area(
            reserved_rows=_PAGE_LOOP_RESERVED_ROWS,
            top_rows=0,
        )
        if needs_render:
            clear_terminal(run)
            result = run(kitten_icat_command(pages[index], current_area))
            if result.returncode != 0:
                return PageLoopResult(returncode=result.returncode)
            move_cursor_below_image(current_area)
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
                return PageLoopResult(returncode=1, warnings=zoom_result.warnings)
            needs_render = True
            continue
        next_index = page_index_after_key(index, key, len(pages))
        if next_index is None:
            clear_terminal(run)
            return PageLoopResult()
        index = next_index
        needs_render = True
