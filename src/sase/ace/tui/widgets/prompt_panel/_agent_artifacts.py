"""Agent-specific ARTIFACTS helpers for the prompt panel header."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.text import Text

from ...models.agent import Agent

if TYPE_CHECKING:
    from ._agent_display_parts import HeaderHintState

_COLOR_HEADER = "bold #87D7FF"
_COLOR_PATH = "#87AFFF"
_COLOR_BASENAME = "bold #87AFFF"
_GLYPH_STYLE = "bold #FFD787"


@dataclass(frozen=True)
class _ArtifactPath:
    display_path: str
    actual_path: str


def append_agent_artifacts_section(
    text: Text,
    agent: Agent,
    *,
    hint_state: HeaderHintState | None = None,
) -> None:
    """Append the selected agent's ARTIFACTS path list when available."""
    artifacts = _agent_artifact_paths(agent)
    if not artifacts:
        return

    text.append("ARTIFACTS:\n", style=_COLOR_HEADER)
    for artifact in artifacts:
        text.append("  ~ ", style=_GLYPH_STYLE)
        if hint_state is not None:
            text.append(f"[{hint_state.hint_counter}] ", style="bold #FFFF00")
            hint_state.hint_mappings[hint_state.hint_counter] = artifact.actual_path
            hint_state.hint_counter += 1
        _append_path(text, artifact.display_path)
        text.append("\n")


def _agent_artifact_paths(agent: Agent) -> list[_ArtifactPath]:
    artifacts_dir = agent.get_artifacts_dir()
    if artifacts_dir is None:
        return []

    artifacts_path = Path(artifacts_dir).expanduser()
    done = _read_json_object(artifacts_path / "done.json")
    meta = _read_json_object(artifacts_path / "agent_meta.json")
    plan_marker = _read_json_object(artifacts_path / "plan_path.json")
    workspace_dir = _first_str(
        agent.workspace_dir, meta.get("workspace_dir"), done.get("workspace_dir")
    )

    candidates: list[str] = []
    plan_path = _selected_plan_path(done, meta, plan_marker)
    if plan_path:
        candidates.append(plan_path)

    candidates.extend(_explicit_artifact_paths(artifacts_path))
    return _dedupe_and_sort_paths(candidates, workspace_dir)


def _selected_plan_path(
    done: dict[str, Any],
    meta: dict[str, Any],
    plan_marker: dict[str, Any],
) -> str | None:
    archived_plan_path = _first_str(
        plan_marker.get("plan_path"),
        meta.get("plan_path"),
        done.get("plan_path"),
    )
    sdd_plan_path = _first_str(meta.get("sdd_plan_path"), done.get("sdd_plan_path"))
    plan_committed = _first_bool(meta.get("plan_committed"), done.get("plan_committed"))

    if plan_committed is True:
        return sdd_plan_path or archived_plan_path
    if plan_committed is False:
        return archived_plan_path or sdd_plan_path

    # Historical artifacts predate plan_committed. Prefer the archived plan
    # unless the SDD path is the only path, the same path, or clearly the only
    # existing candidate.
    if not archived_plan_path:
        return sdd_plan_path
    if not sdd_plan_path:
        return archived_plan_path
    if _same_resolved_path(archived_plan_path, sdd_plan_path):
        return sdd_plan_path
    if not _path_exists(archived_plan_path) and _path_exists(sdd_plan_path):
        return sdd_plan_path
    return archived_plan_path


def _explicit_artifact_paths(artifacts_dir: Path) -> list[str]:
    from sase.core.agent_artifact_facade import list_explicit_agent_artifacts

    try:
        artifacts = list_explicit_agent_artifacts(artifacts_dir)
    except Exception:
        return []
    return [artifact.path for artifact in artifacts if artifact.path]


def _dedupe_and_sort_paths(
    paths: list[str],
    workspace_dir: str | None,
) -> list[_ArtifactPath]:
    by_actual_path: dict[str, _ArtifactPath] = {}
    for path in paths:
        actual_path = _resolve_actual_path(path, workspace_dir)
        by_actual_path.setdefault(
            actual_path,
            _ArtifactPath(
                display_path=_display_path(actual_path, workspace_dir),
                actual_path=actual_path,
            ),
        )
    return [by_actual_path[key] for key in sorted(by_actual_path)]


def _append_path(text: Text, path: str) -> None:
    """Append a path with the DELTAS-style bold basename treatment."""
    dirname, basename = os.path.split(path)
    if dirname:
        text.append(dirname + "/", style=_COLOR_PATH)
    text.append(basename or path, style=_COLOR_BASENAME)


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


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _first_str(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _first_bool(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered == "true":
                return True
            if lowered == "false":
                return False
    return None


def _same_resolved_path(left: str, right: str) -> bool:
    return Path(left).expanduser().resolve(strict=False) == Path(
        right
    ).expanduser().resolve(strict=False)


def _path_exists(path: str) -> bool:
    try:
        return Path(path).expanduser().exists()
    except OSError:
        return False
