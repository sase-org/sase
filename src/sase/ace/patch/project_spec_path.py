"""Project spec path helpers.

Canonical project spec files use the ``.sase`` extension. Legacy ``.gp``
files are still recognized so existing user data remains readable during
the migration window.

This module centralizes filename construction, basename derivation,
archive/main path conversion, and preferred-with-legacy-fallback
resolution so callers do not need to embed extension literals.
"""

from __future__ import annotations

import os

PROJECT_SPEC_EXTENSION = ".sase"
LEGACY_PROJECT_SPEC_EXTENSION = ".gp"
PROJECT_SPEC_ARCHIVE_SUFFIX = "-archive"

PROJECT_SPEC_EXTENSIONS: tuple[str, ...] = (
    PROJECT_SPEC_EXTENSION,
    LEGACY_PROJECT_SPEC_EXTENSION,
)


def active_project_spec_filename(project_name: str) -> str:
    """Canonical active project spec filename for ``project_name``."""
    return f"{project_name}{PROJECT_SPEC_EXTENSION}"


def archive_project_spec_filename(project_name: str) -> str:
    """Canonical archive project spec filename for ``project_name``."""
    return f"{project_name}{PROJECT_SPEC_ARCHIVE_SUFFIX}{PROJECT_SPEC_EXTENSION}"


def legacy_active_project_spec_filename(project_name: str) -> str:
    """Legacy ``.gp`` active filename. Used only for backward-compat reads."""
    return f"{project_name}{LEGACY_PROJECT_SPEC_EXTENSION}"


def legacy_archive_project_spec_filename(project_name: str) -> str:
    """Legacy ``.gp`` archive filename. Used only for backward-compat reads."""
    return f"{project_name}{PROJECT_SPEC_ARCHIVE_SUFFIX}{LEGACY_PROJECT_SPEC_EXTENSION}"


def project_spec_basename(file_path: str) -> str:
    """Project basename for an active or archive project spec path.

    Strips the directory, the canonical/legacy extension, and a trailing
    ``-archive`` suffix. Mirrors ``Patch.project_basename`` and the
    Rust ``project_spec_basename`` helper so both sides agree.
    """
    base = os.path.basename(file_path)
    stem = os.path.splitext(base)[0]
    if stem.endswith(PROJECT_SPEC_ARCHIVE_SUFFIX):
        return stem[: -len(PROJECT_SPEC_ARCHIVE_SUFFIX)]
    return stem


def is_archive_project_spec(file_path: str) -> bool:
    """Return True if ``file_path`` names an archive project spec file.

    Accepts both the canonical ``.sase`` extension and legacy ``.gp``.
    """
    base = os.path.basename(file_path)
    stem, ext = os.path.splitext(base)
    if ext not in PROJECT_SPEC_EXTENSIONS:
        return False
    return stem.endswith(PROJECT_SPEC_ARCHIVE_SUFFIX)


def preferred_project_spec_path(
    project_dir: str, project_name: str, *, archive: bool = False
) -> str:
    """Resolve a project spec path preferring canonical over legacy.

    Returns the canonical ``.sase`` path if it exists, otherwise the legacy
    ``.gp`` path if it exists, otherwise the canonical path (so callers
    have a stable destination for writes).
    """
    canonical_name = (
        archive_project_spec_filename(project_name)
        if archive
        else active_project_spec_filename(project_name)
    )
    legacy_name = (
        legacy_archive_project_spec_filename(project_name)
        if archive
        else legacy_active_project_spec_filename(project_name)
    )
    canonical_path = os.path.join(project_dir, canonical_name)
    if os.path.exists(canonical_path):
        return canonical_path
    legacy_path = os.path.join(project_dir, legacy_name)
    if os.path.exists(legacy_path):
        return legacy_path
    return canonical_path
