"""Shared constants for agent markdown documents."""

from __future__ import annotations

AGENTS_FILENAME = "AGENTS.md"
PROVIDER_SHIM_FILES = ("CLAUDE.md", "GEMINI.md", "QWEN.md", "OPENCODE.md")
PROVIDER_SHIM_CONTENT = "@AGENTS.md\n"

SHORT_MEMORY_START_MARKER = "<!-- sase-amd:short-memory:start -->"
SHORT_MEMORY_END_MARKER = "<!-- sase-amd:short-memory:end -->"
LONG_MEMORY_START_MARKER = "<!-- sase-amd:long-memory:start -->"
LONG_MEMORY_END_MARKER = "<!-- sase-amd:long-memory:end -->"

__all__ = [
    "AGENTS_FILENAME",
    "LONG_MEMORY_END_MARKER",
    "LONG_MEMORY_START_MARKER",
    "PROVIDER_SHIM_CONTENT",
    "PROVIDER_SHIM_FILES",
    "SHORT_MEMORY_END_MARKER",
    "SHORT_MEMORY_START_MARKER",
]
