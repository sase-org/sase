"""Shared constants for agent markdown documents."""

from __future__ import annotations

AGENTS_FILENAME = "AGENTS.md"
PROVIDER_SHIM_FILES = ("CLAUDE.md", "GEMINI.md", "QWEN.md", "OPENCODE.md")
PROVIDER_SHIM_CONTENT = "@AGENTS.md\n"
HOME_PROVIDER_SHIM_CONTENT = "@~/AGENTS.md\n"
CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT = "@{{ .chezmoi.homeDir }}/AGENTS.md\n"

__all__ = [
    "AGENTS_FILENAME",
    "CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT",
    "HOME_PROVIDER_SHIM_CONTENT",
    "PROVIDER_SHIM_CONTENT",
    "PROVIDER_SHIM_FILES",
]
