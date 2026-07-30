"""Formatting and path helpers for the artifact-file selection modal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.text import Text

from sase.ace.tui.graphics import is_supported_video_path

from ..models.artifact_file_clipboard import (
    ArtifactFilePathCopy,
    artifact_file_clipboard_workspace_dir,
    artifact_file_preferred_path_text,
    artifact_file_resolved_stored_path,
)

_SELECTOR_KEYS = "1234567890abcdefghijklmnopqrstuvwxyz"
_RESERVED_KEYS = {"j", "k", "m", "q", "y", "Y", "z"}
_MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd"}
_MAX_LABEL_LEN = 54
_MAX_AGENT_LABEL_LEN = 28
_MAX_KIND_LEN = 18
_MAX_PATH_LEN = 72


def artifact_file_selector_keys(count: int) -> list[str]:
    keys = [key for key in _SELECTOR_KEYS if key not in _RESERVED_KEYS]
    return keys[:count]


def _short_text(value: object, *, max_len: int, from_end: bool = False) -> str:
    text = str(value or "")
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    if from_end:
        return "..." + text[-(max_len - 3) :]
    return text[: max_len - 3] + "..."


def artifact_file_path(artifact_file: Any) -> str:
    return str(getattr(artifact_file, "path", "") or "")


def _artifact_file_display_path(artifact_file: Any) -> str:
    return artifact_file_preferred_path_text(artifact_file)[0]


def _artifact_file_workspace_dir(artifact_file: Any) -> str | None:
    workspace_dir = getattr(artifact_file, "workspace_dir", None)
    return workspace_dir if isinstance(workspace_dir, str) and workspace_dir else None


def artifact_file_resolved_display_path(artifact_file: Any) -> Path | None:
    path_text = _artifact_file_display_path(artifact_file)
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        workspace_dir = artifact_file_clipboard_workspace_dir(artifact_file)
        if workspace_dir:
            path = Path(workspace_dir).expanduser() / path
    return path


def _is_markdown_path(path: Path) -> bool:
    return path.suffix.lower() in _MARKDOWN_SUFFIXES


def artifact_file_is_markdown(artifact_file: Any) -> bool:
    path = _artifact_file_display_path(artifact_file)
    return bool(path and _is_markdown_path(Path(path)))


def artifact_file_reference(artifact_file: Any, *, prompt_form: bool) -> str:
    artifact_id = str(getattr(artifact_file, "id", "") or "")
    if not artifact_id:
        raise ValueError("artifact file has no durable reference")
    prefix = "@" if prompt_form else ""
    return f"{prefix}file:{artifact_id}"


def _artifact_file_kind(artifact_file: Any) -> str:
    if is_supported_video_path(_artifact_file_display_path(artifact_file)):
        return "video"
    return _short_text(
        getattr(artifact_file, "kind", "file") or "file", max_len=_MAX_KIND_LEN
    )


def artifact_file_label(artifact_file: Any, *, max_len: int = _MAX_LABEL_LEN) -> str:
    path = artifact_file_path(artifact_file)
    fallback = Path(path).name if path else _artifact_file_kind(artifact_file)
    return _short_text(
        getattr(artifact_file, "label", None) or fallback,
        max_len=max_len,
    )


def _display_path(path: str, *, workspace_dir: str | None = None) -> str:
    if not path:
        return "(no path)"
    expanded = Path(path).expanduser()
    if workspace_dir:
        try:
            relative = expanded.resolve(strict=False).relative_to(
                Path(workspace_dir).expanduser().resolve(strict=False)
            )
        except (OSError, ValueError):
            pass
        else:
            return relative.as_posix() or "."
    return _home_relative_path(expanded)


def _home_relative_path(path: Path) -> str:
    try:
        relative = path.resolve(strict=False).relative_to(
            Path.home().expanduser().resolve(strict=False)
        )
    except (OSError, ValueError):
        return str(path)
    text = relative.as_posix()
    return "~" if not text else f"~/{text}"


def artifact_file_stored_clipboard_path(
    artifact_file: Any,
) -> ArtifactFilePathCopy | None:
    path = artifact_file_resolved_stored_path(artifact_file)
    if path is None:
        return None
    return ArtifactFilePathCopy(_home_relative_path(path), "stored")


def _short_path(
    path: str,
    *,
    max_len: int = _MAX_PATH_LEN,
    workspace_dir: str | None = None,
) -> str:
    return _short_text(
        _display_path(path, workspace_dir=workspace_dir),
        max_len=max_len,
        from_end=True,
    )


def artifact_file_option_text(
    selector: str | None,
    artifact_file: Any,
    *,
    marked: bool = False,
    agent_label: str | None = None,
) -> Text:
    text = Text()
    if selector is None:
        text.append("   ", style="dim")
    else:
        text.append(f"{selector}  ", style="bold #D7AF5F")
    marker = "[x] " if marked else "    "
    marker_style = "bold #A6E3A1" if marked else "dim"
    text.append(marker, style=marker_style)
    label_budget = _MAX_LABEL_LEN
    if agent_label:
        prefix = _short_text(agent_label, max_len=_MAX_AGENT_LABEL_LEN)
        text.append(prefix, style="bold #87D7FF")
        text.append("  ·  ", style="dim")
        label_budget = max(16, _MAX_LABEL_LEN - len(prefix) - 5)
    text.append(artifact_file_label(artifact_file, max_len=label_budget))
    text.append(f"  [{_artifact_file_kind(artifact_file)}]", style="dim #87D7FF")
    text.append("\n")
    display_path = _short_path(
        _artifact_file_display_path(artifact_file),
        workspace_dir=_artifact_file_workspace_dir(artifact_file),
    )
    text.append(f"   {display_path}", style="dim")
    return text
