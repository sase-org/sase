"""Shared constants for agent markdown documents."""

from __future__ import annotations

AGENTS_FILENAME = "AGENTS.md"
AGENTS_TEMPLATE_FILENAME = "AGENTS.md.tmpl"
AGENTS_SOURCE_FILENAMES = frozenset({AGENTS_FILENAME, AGENTS_TEMPLATE_FILENAME})
# Project roots and the directory of any nested ``AGENTS.md`` keep only
# ``CLAUDE.md`` beside ``AGENTS.md``. agy 1.4.0 reads both ``GEMINI.md`` and
# ``AGENTS.md``, Qwen reads ``QWEN.md`` and ``AGENTS.md``, and OpenCode never
# reads ``OPENCODE.md``; those three copies are retired at project roots.
PROJECT_PROVIDER_SHIM_FILES = ("CLAUDE.md",)
# Home and chezmoi roots keep all four copies until E5.
HOME_PROVIDER_SHIM_FILES = ("CLAUDE.md", "GEMINI.md", "QWEN.md", "OPENCODE.md")
RETIRED_PROJECT_PROVIDER_SHIM_FILES = tuple(
    name for name in HOME_PROVIDER_SHIM_FILES if name not in PROJECT_PROVIDER_SHIM_FILES
)
# Classifiers keep retired names so leftover copies in other projects stay
# classified as generated.
RECOGNIZED_PROVIDER_SHIM_FILES = tuple(
    dict.fromkeys((*PROJECT_PROVIDER_SHIM_FILES, *HOME_PROVIDER_SHIM_FILES))
)
# Legacy ``@``-import provider shim texts. Provider files used to be one-line
# ``@AGENTS.md`` imports; they are now full copies. These strings are retained
# only so existing legacy shims are recognized and migrated cleanly.
PROVIDER_SHIM_CONTENT = "@AGENTS.md\n"
HOME_PROVIDER_SHIM_CONTENT = "@~/AGENTS.md\n"
CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT = "@{{ .chezmoi.homeDir }}/AGENTS.md\n"


def production_provider_shim_files(*, include_project_memory: bool) -> tuple[str, ...]:
    """Return the shim filenames written at a project root or a home root."""
    if include_project_memory:
        return PROJECT_PROVIDER_SHIM_FILES
    return HOME_PROVIDER_SHIM_FILES


__all__ = [
    "AGENTS_FILENAME",
    "AGENTS_SOURCE_FILENAMES",
    "AGENTS_TEMPLATE_FILENAME",
    "CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT",
    "HOME_PROVIDER_SHIM_CONTENT",
    "HOME_PROVIDER_SHIM_FILES",
    "PROJECT_PROVIDER_SHIM_FILES",
    "PROVIDER_SHIM_CONTENT",
    "RECOGNIZED_PROVIDER_SHIM_FILES",
    "RETIRED_PROJECT_PROVIDER_SHIM_FILES",
    "production_provider_shim_files",
]
