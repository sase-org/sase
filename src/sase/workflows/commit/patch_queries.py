"""Functions for querying Patch existence."""

import os

from sase.workflows.utils import get_project_file_path


def _name_in_file(path: str, cl_name: str) -> bool:
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("NAME: ") and line[6:].strip() == cl_name:
                    return True
        return False
    except Exception:
        return False


def patch_exists(project: str, patch_name: str) -> bool:
    """Check if a Patch with the given name already exists in the project file.

    Args:
        project: Project name.
        patch_name: Patch name to check for.

    Returns:
        True if a Patch with the given NAME exists, False otherwise.
    """
    return _name_in_file(get_project_file_path(project), patch_name)


def patch_exists_anywhere(project: str, patch_name: str) -> bool:
    """Check if a Patch with the given name exists in active *or* archive.

    The archive holds Patches in terminal statuses (Submitted, Reverted,
    Archived), which are still valid PARENT references.
    """
    if patch_exists(project, patch_name):
        return True
    from sase.ace.patch.archive import get_archive_file_path

    project_file = get_project_file_path(project)
    return _name_in_file(get_archive_file_path(project_file), patch_name)


changespec_exists = patch_exists
changespec_exists_anywhere = patch_exists_anywhere


__all__ = [
    "changespec_exists",
    "changespec_exists_anywhere",
    "patch_exists",
    "patch_exists_anywhere",
]
