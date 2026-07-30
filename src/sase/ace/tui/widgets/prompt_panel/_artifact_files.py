"""Agent-specific artifact-file helpers for the prompt panel header."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text

from ...models.agent import Agent
from ._agent_context_common import (
    COLOR_ARTIFACT_FILE_BASENAME,
    COLOR_ARTIFACT_FILE_PATH,
    COLOR_ARTIFACTS_SUBHEADER,
)

if TYPE_CHECKING:
    from ._agent_display_state import HeaderHintState

_COLOR_PATH_MISSING = "dim #87AFFF"
_COLOR_BASENAME_MISSING = "dim #87AFFF"
_COLOR_MISSING_SUFFIX = "dim italic #FF8787"
_ICON_BY_VIEW_MODE = {
    "image": "▨",
    "video": "▶",
    "pdf": "▤",
    "markdown": "▤",
    "text": "•",
}
_FALLBACK_ARTIFACT_ICON = _ICON_BY_VIEW_MODE["text"]


@dataclass(frozen=True)
class ArtifactFilePath:
    display_path: str
    actual_path: str
    exists: bool = True
    view_mode: str = "text"
    materializable: bool = False


def append_artifact_file_paths(
    text: Text,
    *,
    artifact_file_paths: list[ArtifactFilePath] | None = None,
    hint_state: HeaderHintState | None = None,
    indent: str = "",
) -> None:
    """Append the selected agent's artifact-file path rows when available."""
    artifact_files = artifact_file_paths or []
    for artifact_file in artifact_files:
        available = artifact_file.exists or artifact_file.materializable
        icon, icon_style = _artifact_file_icon(
            artifact_file.view_mode, exists=available
        )
        text.append(indent)
        text.append(icon, style=icon_style)
        text.append(" ")
        if hint_state is not None and artifact_file.exists:
            text.append(f"[{hint_state.hint_counter}] ", style="bold #FFFF00")
            hint_state.hint_mappings[hint_state.hint_counter] = (
                artifact_file.actual_path
            )
            hint_state.hint_counter += 1
        append_artifact_file_path(
            text,
            artifact_file.display_path,
            exists=available,
        )
        if not artifact_file.exists:
            suffix = " (VCS-backed)" if artifact_file.materializable else " (missing)"
            text.append(suffix, style=_COLOR_MISSING_SUFFIX)
        text.append("\n")


def artifact_file_paths(agent: Agent) -> list[ArtifactFilePath]:
    artifacts_dir = agent.get_artifacts_dir()
    if artifacts_dir is None:
        return []

    from sase.ace.tui.graphics import artifact_file_view_mode
    from sase.core.artifact_file_facade import list_artifact_files

    try:
        artifact_files = list_artifact_files(artifacts_dir)
    except Exception:
        return []
    display_items: list[tuple[str, str | None, str | None, str, bool]] = [
        (
            artifact_file.path
            or artifact_file.source_path
            or artifact_file.vcs_relpath
            or artifact_file.label,
            # Persisted default artifact files live in the global store under an
            # opaque digest-suffixed name. Their ``source_path`` records the
            # original workspace location, which is what users recognise — use
            # it for the display label. Explicit artifact files keep their stored
            # path so the panel surfaces where the file was registered.
            artifact_file.source_path if not artifact_file.explicit else None,
            artifact_file.workspace_dir,
            artifact_file_view_mode(
                artifact_file.path
                or artifact_file.vcs_relpath
                or artifact_file.source_path
                or "",
                kind=artifact_file.kind,
            )
            or "text",
            artifact_file.is_vcs_backed,
        )
        for artifact_file in artifact_files
        if artifact_file.kind not in {"chat", "pdf"}
    ]

    # Aggregate follow-up prompt artifact files from child feedback agents onto
    # the parent so users can locate "what feedback was sent" from the same
    # ARTIFACTS list that already shows other parent-level artifacts.
    for child in agent.followup_agents:
        child_dir = child.get_artifacts_dir()
        if not child_dir:
            continue
        try:
            child_artifact_files = list_artifact_files(child_dir)
        except Exception:
            continue
        for artifact_file in child_artifact_files:
            if not artifact_file.path:
                continue
            basename = os.path.basename(artifact_file.path)
            if not (
                basename.startswith("followup_prompt") and basename.endswith(".md")
            ):
                continue
            display_items.append(
                (
                    artifact_file.path,
                    None,
                    artifact_file.workspace_dir,
                    "markdown",
                    False,
                )
            )

    return _dedupe_paths(display_items, agent.workspace_dir)


def _dedupe_paths(
    paths: list[tuple[str, str | None, str | None, str, bool]],
    fallback_workspace_dir: str | None,
) -> list[ArtifactFilePath]:
    by_actual_path: dict[str, ArtifactFilePath] = {}
    for (
        path,
        display_source,
        artifact_workspace_dir,
        view_mode,
        materializable,
    ) in paths:
        workspace_dir = artifact_workspace_dir or fallback_workspace_dir
        actual_path = _resolve_actual_path(path, workspace_dir)
        display_path = _display_path(
            display_source or actual_path,
            workspace_dir,
        )
        by_actual_path.setdefault(
            actual_path,
            ArtifactFilePath(
                display_path=display_path,
                actual_path=actual_path,
                exists=False if materializable else os.path.exists(actual_path),
                view_mode=view_mode,
                materializable=materializable,
            ),
        )
    return list(by_actual_path.values())


def _artifact_file_icon(view_mode: str, *, exists: bool) -> tuple[str, str]:
    icon = _ICON_BY_VIEW_MODE.get(view_mode, _FALLBACK_ARTIFACT_ICON)
    style = COLOR_ARTIFACTS_SUBHEADER
    if not exists:
        style = f"dim {style}"
    return icon, style


def append_artifact_file_path(text: Text, path: str, *, exists: bool = True) -> None:
    """Append a path with the DELTAS-style bold basename treatment."""
    path_style = COLOR_ARTIFACT_FILE_PATH if exists else _COLOR_PATH_MISSING
    basename_style = COLOR_ARTIFACT_FILE_BASENAME if exists else _COLOR_BASENAME_MISSING
    dirname, basename = os.path.split(path)
    if dirname:
        text.append(dirname + "/", style=path_style)
    text.append(basename or path, style=basename_style)


def _display_path(path: str, workspace_dir: str | None) -> str:
    actual = Path(path).expanduser().resolve(strict=False)
    if workspace_dir:
        workspace = Path(workspace_dir).expanduser().resolve(strict=False)
        try:
            return actual.relative_to(workspace).as_posix()
        except ValueError:
            pass
    home = Path.home().expanduser().resolve(strict=False)
    try:
        return "~/" + actual.relative_to(home).as_posix()
    except ValueError:
        return str(actual)


def _resolve_actual_path(path: str, workspace_dir: str | None) -> str:
    expanded = Path(path).expanduser()
    if expanded.is_absolute():
        return str(expanded.resolve(strict=False))
    if workspace_dir:
        return str((Path(workspace_dir).expanduser() / expanded).resolve(strict=False))
    return str(expanded.resolve(strict=False))
