"""Shared types and constants for agent panel actions."""

from __future__ import annotations

from typing import Literal

TabName = Literal["changespecs", "agents", "axe"]

ARTIFACT_VIEWER_LAYOUT_CLASS = "-artifact-viewer-active"
ARTIFACT_VIEWER_NAV_MESSAGE = "Close the artifact viewer before switching agents"
ARTIFACT_NOTIFY_PID_ENV = "SASE_ARTIFACT_NOTIFY_PID"
