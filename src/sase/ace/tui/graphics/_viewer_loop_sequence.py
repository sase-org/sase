"""Multi-artifact terminal loop for artifact viewer pages."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ._viewer_loop_media import (
    display_text_artifact,
    display_video_artifact,
    load_artifact_video_playback_config,
)
from ._viewer_loop_terminal import (
    _RETURN_TO_ACE_KEY,
    artifact_image_area,
    clear_terminal,
    kitten_icat_command,
    move_cursor_below_image,
    page_index_after_key,
    page_loop_available_keys,
    print_artifact_header,
    print_artifact_warning,
    print_page_prompt,
    read_single_key,
    run_command as default_run_command,
    select_tmux_pane,
    tmux_zoom_available as tmux_zoom_is_available,
    toggle_tmux_zoom,
)
from ._viewer_loop_types import ArtifactVideoPlaybackConfig, PageLoopResult
from ._viewer_render import artifact_file_view_mode, render_artifact_file_pages
from ._viewer_types import (
    ArtifactFileImageArea,
    ArtifactRenderResult,
    ArtifactFileViewerResult,
    ArtifactFileViewerWarning,
    ArtifactFileViewSpec,
)


def run_artifact_sequence_loop(
    artifacts: Sequence[ArtifactFileViewSpec],
    *,
    cache_root: str | Path,
    read_key: Callable[[], str] | None = None,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]]
    | None = None,
    image_area: ArtifactFileImageArea | None = None,
    return_pane_id: str | None = None,
    select_pane: Callable[[str], ArtifactFileViewerResult] | None = None,
    tmux_zoom_available: bool | None = None,
    toggle_zoom: Callable[[], ArtifactFileViewerResult] | None = None,
    video_config: ArtifactVideoPlaybackConfig | None = None,
    render_pages: Callable[..., ArtifactRenderResult] = render_artifact_file_pages,
) -> PageLoopResult:
    """Display an artifact sequence with page and document navigation."""

    specs = tuple(artifacts)
    if not specs:
        return PageLoopResult(returncode=1)

    read = read_key or read_single_key
    run = run_command or default_run_command
    select = select_pane or select_tmux_pane
    zoom = toggle_zoom or toggle_tmux_zoom
    root = Path(cache_root).expanduser()
    page_cache: dict[tuple[int, int, int], tuple[Path, ...]] = {}

    def pages_for(index: int, area: ArtifactFileImageArea) -> ArtifactRenderResult:
        cache_key = (index, area.columns, area.rows)
        if cache_key in page_cache:
            return ArtifactRenderResult(page_cache[cache_key])
        spec = specs[index]
        rendered = render_pages(
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
        tmux_zoom_is_available() if tmux_zoom_available is None else tmux_zoom_available
    )
    pages: tuple[Path, ...] = ()
    current_mode = artifact_file_view_mode(
        specs[artifact_index].path,
        kind=specs[artifact_index].kind,
    )
    resolved_video_config = video_config
    while True:
        current_area = image_area or artifact_image_area()
        if needs_render:
            spec = specs[artifact_index]
            current_mode = artifact_file_view_mode(spec.path, kind=spec.kind)
            if current_mode is None:
                warning = ArtifactFileViewerWarning(
                    "unsupported_artifact_kind",
                    "Unsupported artifact type",
                )
                return PageLoopResult(returncode=1, warnings=(warning,))
            if current_mode == "text":
                page_index = 0
                pages = ()
                displayed = display_text_artifact(
                    spec,
                    run,
                    artifact_index=artifact_index,
                    artifact_count=len(specs),
                )
                if displayed.warnings:
                    return PageLoopResult(
                        returncode=1,
                        warnings=displayed.warnings,
                    )
                if displayed.returncode != 0:
                    return PageLoopResult(returncode=displayed.returncode)
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
                video_displayed = display_video_artifact(
                    spec,
                    current_area,
                    run,
                    video_config=resolved_video_config,
                    artifact_index=artifact_index,
                    artifact_count=len(specs),
                )
                if video_displayed.warnings:
                    return PageLoopResult(
                        returncode=1,
                        warnings=video_displayed.warnings,
                    )
                if video_displayed.returncode != 0:
                    print_artifact_warning(
                        ArtifactFileViewerWarning(
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
                    return PageLoopResult(returncode=1, warnings=rendered.warnings)
                pages = rendered.pages
                if not pages:
                    return PageLoopResult(returncode=1)

                clear_terminal(run)
                print_artifact_header(
                    spec,
                    page_index=page_index,
                    page_count=len(pages),
                    artifact_index=artifact_index,
                    artifact_count=len(specs),
                )
                result = run(kitten_icat_command(pages[page_index], current_area))
                if result.returncode != 0:
                    return PageLoopResult(returncode=result.returncode)
                move_cursor_below_image(current_area)
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
            clear_terminal(run)
            return PageLoopResult()
        if key == _RETURN_TO_ACE_KEY and return_pane_id:
            select(return_pane_id)
            continue
        print()
        needs_render = True
        if key == "z" and not is_text_mode:
            zoom_result = zoom()
            if not zoom_result.ok:
                return PageLoopResult(returncode=1, warnings=zoom_result.warnings)
        elif key in {"j", "k", "r"}:
            if is_text_mode or is_video_mode:
                page_index = 0
                continue
            next_page_index = page_index_after_key(page_index, key, len(pages))
            if next_page_index is None:
                clear_terminal(run)
                return PageLoopResult()
            page_index = next_page_index
        elif key == "n":
            artifact_index = min(artifact_index + 1, len(specs) - 1)
            page_index = 0
        elif key == "p":
            artifact_index = max(artifact_index - 1, 0)
            page_index = 0
