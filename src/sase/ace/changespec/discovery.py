"""Legacy discovery names backed by :mod:`sase.ace.patch.discovery`."""

from sase.ace.patch.discovery import (
    iter_changespec_project_file_records,
    iter_changespec_project_files,
    iter_patch_project_file_records,
    iter_patch_project_files,
)

__all__ = [
    "iter_changespec_project_file_records",
    "iter_changespec_project_files",
    "iter_patch_project_file_records",
    "iter_patch_project_files",
]
