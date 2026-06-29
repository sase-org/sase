"""Shared types and display constants for the config edit modal."""

from __future__ import annotations

from typing import Literal


EditorKind = Literal["bool", "enum", "int", "number", "string", "string_list", "yaml"]
Stage = Literal["edit", "preview"]

_OK_COLOR = "#5FAF5F"
_ERR_COLOR = "#FF8787"
_WARN_COLOR = "#FFAF5F"
_ACCENT = "#00D7AF"
_MUTED = "#888888"
_MOD_COLOR = "#FFD700"
