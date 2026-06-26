"""Shared constants for agent markdown documents."""

from __future__ import annotations

AGENTS_FILENAME = "AGENTS.md"
# Provider context-shim files that point at the canonical ``AGENTS.md``. Each
# entry is named for a CLI that does not read ``AGENTS.md`` directly. ``GEMINI.md``
# is retained for the Antigravity CLI (`agy`), which still reads ``GEMINI.md`` for
# workspace context per Google's Gemini CLI -> Antigravity migration.
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
