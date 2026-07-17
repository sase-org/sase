"""Shared types and constants for agent panel actions."""

from __future__ import annotations

from typing import Literal

TabName = Literal["changespecs", "agents", "axe"]

ARTIFACT_FILE_VIEWER_LAYOUT_CLASS = "-artifact-file-viewer-active"
ARTIFACT_FILE_VIEWER_NAV_MESSAGE = (
    "Close the artifact-file viewer before switching agents"
)
ARTIFACT_FILE_NOTIFY_PID_ENV = "SASE_ARTIFACT_FILE_NOTIFY_PID"
