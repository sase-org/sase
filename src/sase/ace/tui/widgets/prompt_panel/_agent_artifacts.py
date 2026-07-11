"""Agent-specific ARTIFACTS helpers for the prompt panel header."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text

from ...models.agent import Agent

if TYPE_CHECKING:
    from ._agent_display_state import HeaderHintState

_COLOR_HEADER = "bold #87D7FF"
_COLOR_PATH = "#87AFFF"
_COLOR_BASENAME = "bold #87AFFF"
_COLOR_PATH_MISSING = "dim #87AFFF"
_COLOR_BASENAME_MISSING = "dim #87AFFF"
_COLOR_MISSING_SUFFIX = "dim italic #FF8787"
_ICON_BY_VIEW_MODE = {
    "image": ("▨", "bold #5FD7AF"),
    "video": ("▶", "bold #FF875F"),
    "pdf": ("▤", "bold #D7D7AF"),
    "markdown": ("▤", "bold #D7D7AF"),
    "text": ("•", "bold #FFD787"),
}
_FALLBACK_ARTIFACT_ICON = _ICON_BY_VIEW_MODE["text"]


@dataclass(frozen=True)
class AgentArtifactPath:
    display_path: str
    actual_path: str
    exists: bool = True
    view_mode: str = "text"


def append_agent_artifacts_section(
    text: Text,
    *,
    artifact_paths: list[AgentArtifactPath] | None = None,
    hint_state: HeaderHintState | None = None,
) -> None:
    """Append the selected agent's artifact path list when available."""
    artifacts = artifact_paths or []
    if not artifacts:
        return

    text.append("Artifacts:\n", style=_COLOR_HEADER)
    for artifact in artifacts:
        icon, icon_style = _artifact_icon(artifact.view_mode, exists=artifact.exists)
        text.append("  ")
        text.append(icon, style=icon_style)
        text.append(" ")
        if hint_state is not None:
            text.append(f"[{hint_state.hint_counter}] ", style="bold #FFFF00")
            hint_state.hint_mappings[hint_state.hint_counter] = artifact.actual_path
            hint_state.hint_counter += 1
        _append_path(text, artifact.display_path, exists=artifact.exists)
        if not artifact.exists:
            text.append(" (missing)", style=_COLOR_MISSING_SUFFIX)
        text.append("\n")


def agent_artifact_paths(agent: Agent) -> list[AgentArtifactPath]:
    artifacts_dir = agent.get_artifacts_dir()
    if artifacts_dir is None:
        return []

    from sase.ace.tui.graphics import artifact_view_mode
    from sase.core.agent_artifact_facade import list_agent_artifacts

    try:
        artifacts = list_agent_artifacts(artifacts_dir)
    except Exception:
        return []
    display_items: list[tuple[str, str | None, str | None, str]] = [
        (
            artifact.path,
            # Persisted default artifacts live in the global store under an
            # opaque digest-suffixed name. Their ``source_path`` records the
            # original workspace location, which is what users recognise — use
            # it for the display label. Explicit artifacts keep their stored
            # path so the panel surfaces where the artifact was filed.
            artifact.source_path if not artifact.explicit else None,
            artifact.workspace_dir,
            artifact_view_mode(artifact.path, kind=artifact.kind) or "text",
        )
        for artifact in artifacts
        if artifact.path and artifact.kind not in {"chat", "pdf"}
    ]

    # Aggregate follow-up prompt artifacts from child feedback agents onto
    # the parent so users can locate "what feedback was sent" from the same
    # ARTIFACTS list that already shows other parent-level artifacts.
    for child in agent.followup_agents:
        child_dir = child.get_artifacts_dir()
        if not child_dir:
            continue
        try:
            child_artifacts = list_agent_artifacts(child_dir)
        except Exception:
            continue
        for artifact in child_artifacts:
            if not artifact.path:
                continue
            basename = os.path.basename(artifact.path)
            if not (
                basename.startswith("followup_prompt") and basename.endswith(".md")
            ):
                continue
            display_items.append(
                (artifact.path, None, artifact.workspace_dir, "markdown")
            )

    return _dedupe_paths(display_items, agent.workspace_dir)


def _dedupe_paths(
    paths: list[tuple[str, str | None, str | None, str]],
    fallback_workspace_dir: str | None,
) -> list[AgentArtifactPath]:
    by_actual_path: dict[str, AgentArtifactPath] = {}
    for path, display_source, artifact_workspace_dir, view_mode in paths:
        workspace_dir = artifact_workspace_dir or fallback_workspace_dir
        actual_path = _resolve_actual_path(path, workspace_dir)
        display_path = _display_path(
            display_source or actual_path,
            workspace_dir,
        )
        by_actual_path.setdefault(
            actual_path,
            AgentArtifactPath(
                display_path=display_path,
                actual_path=actual_path,
                exists=os.path.exists(actual_path),
                view_mode=view_mode,
            ),
        )
    return list(by_actual_path.values())


def _artifact_icon(view_mode: str, *, exists: bool) -> tuple[str, str]:
    icon, style = _ICON_BY_VIEW_MODE.get(view_mode, _FALLBACK_ARTIFACT_ICON)
    if not exists:
        style = f"dim {style}"
    return icon, style


def _append_path(text: Text, path: str, *, exists: bool = True) -> None:
    """Append a path with the DELTAS-style bold basename treatment."""
    path_style = _COLOR_PATH if exists else _COLOR_PATH_MISSING
    basename_style = _COLOR_BASENAME if exists else _COLOR_BASENAME_MISSING
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
