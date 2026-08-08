"""Legacy ProjectSpec path names backed by :mod:`sase.ace.patch.project_spec_path`."""

from sase.ace.patch.project_spec_path import (
    LEGACY_PROJECT_SPEC_EXTENSION,
    PROJECT_SPEC_ARCHIVE_SUFFIX,
    PROJECT_SPEC_EXTENSION,
    PROJECT_SPEC_EXTENSIONS,
    active_project_spec_filename,
    archive_project_spec_filename,
    is_archive_project_spec,
    legacy_active_project_spec_filename,
    legacy_archive_project_spec_filename,
    preferred_project_spec_path,
    project_spec_basename,
)

__all__ = [
    "LEGACY_PROJECT_SPEC_EXTENSION",
    "PROJECT_SPEC_ARCHIVE_SUFFIX",
    "PROJECT_SPEC_EXTENSION",
    "PROJECT_SPEC_EXTENSIONS",
    "active_project_spec_filename",
    "archive_project_spec_filename",
    "is_archive_project_spec",
    "legacy_active_project_spec_filename",
    "legacy_archive_project_spec_filename",
    "preferred_project_spec_path",
    "project_spec_basename",
]
