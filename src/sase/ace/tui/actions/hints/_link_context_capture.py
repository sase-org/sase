"""Stable agent/patch inputs for off-thread pager link-context construction."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Literal

from sase.core.patch import get_workspace_directory_for_patch
from sase.pager.link_context import (
    LinkResolutionContext,
    agent_link_context,
    default_link_context,
    workspace_link_context,
)

_CapturedSource = Literal["agent", "patch", "default"]


@dataclass(frozen=True)
class CapturedLinkContext:
    """Primitive agent/patch fields captured on the UI thread."""

    source: _CapturedSource
    workspace_num: int | None = None
    project_file: str | None = None
    workspace_dir: str | None = None
    project_basename: str | None = None


def link_context_from_capture(captured: CapturedLinkContext) -> LinkResolutionContext:
    """Build the ordered pager context from a UI-thread snapshot.

    Resolves the selected agent workspace, patch workspace, checkout marker,
    and primary/default anchors. Callers must run this off the event loop.
    """
    if captured.source == "agent":
        return agent_link_context(
            captured.workspace_num,
            captured.project_file,
            captured.workspace_dir,
        )
    if captured.source == "patch":
        workspace_dir = _workspace_dir_for_project_basename(captured.project_basename)
        if not workspace_dir:
            return default_link_context()
        return workspace_link_context(workspace_dir)
    return default_link_context()


def _workspace_dir_for_project_basename(project_basename: str | None) -> str | None:
    if not project_basename:
        return None
    try:
        return get_workspace_directory_for_patch(
            SimpleNamespace(project_basename=project_basename)  # type: ignore[arg-type]
        )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return None
