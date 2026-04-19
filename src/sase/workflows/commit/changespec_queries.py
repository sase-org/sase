"""Functions for querying ChangeSpec existence."""

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


def changespec_exists(project: str, cl_name: str) -> bool:
    """Check if a ChangeSpec with the given name already exists in the project file.

    Args:
        project: Project name.
        cl_name: CL name to check for.

    Returns:
        True if a ChangeSpec with the given NAME exists, False otherwise.
    """
    return _name_in_file(get_project_file_path(project), cl_name)


def changespec_exists_anywhere(project: str, cl_name: str) -> bool:
    """Check if a ChangeSpec with the given name exists in active *or* archive.

    The archive holds ChangeSpecs in terminal statuses (Submitted, Reverted,
    Archived), which are still valid PARENT references.
    """
    if changespec_exists(project, cl_name):
        return True
    from sase.ace.changespec.archive import get_archive_file_path

    project_file = get_project_file_path(project)
    return _name_in_file(get_archive_file_path(project_file), cl_name)
