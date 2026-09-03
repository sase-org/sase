"""Shared constants for agent markdown documents."""

from __future__ import annotations

AGENTS_FILENAME = "AGENTS.md"
AGENTS_TEMPLATE_FILENAME = "AGENTS.md.tmpl"
AGENTS_SOURCE_FILENAMES = frozenset({AGENTS_FILENAME, AGENTS_TEMPLATE_FILENAME})
# Provider instruction files. ``sase memory init`` writes each as a byte-for-byte
# copy of the root's ``AGENTS.md`` (some providers do not read ``AGENTS.md``
# directly, and some do not support ``@``-import composition). ``GEMINI.md`` is
# retained for the Antigravity CLI (`agy`), which still reads ``GEMINI.md`` for
# workspace context per Google's Gemini CLI -> Antigravity migration.
PROVIDER_SHIM_FILES = ("CLAUDE.md", "GEMINI.md", "QWEN.md", "OPENCODE.md")
# Legacy ``@``-import provider shim texts. Provider files used to be one-line
# ``@AGENTS.md`` imports; they are now full copies. These strings are retained
# only so existing legacy shims are recognized and migrated cleanly.
PROVIDER_SHIM_CONTENT = "@AGENTS.md\n"
HOME_PROVIDER_SHIM_CONTENT = "@~/AGENTS.md\n"
CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT = "@{{ .chezmoi.homeDir }}/AGENTS.md\n"

__all__ = [
    "AGENTS_FILENAME",
    "AGENTS_SOURCE_FILENAMES",
    "AGENTS_TEMPLATE_FILENAME",
    "CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT",
    "HOME_PROVIDER_SHIM_CONTENT",
    "PROVIDER_SHIM_CONTENT",
    "PROVIDER_SHIM_FILES",
]
