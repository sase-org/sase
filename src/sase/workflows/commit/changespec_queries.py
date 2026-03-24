"""Functions for querying ChangeSpec existence."""

import os

from sase.workflows.utils import get_project_file_path


def changespec_exists(project: str, cl_name: str) -> bool:
    """Check if a ChangeSpec with the given name already exists in the project file.

    Args:
        project: Project name.
        cl_name: CL name to check for.

    Returns:
        True if a ChangeSpec with the given NAME exists, False otherwise.
    """
    project_file = get_project_file_path(project)
    if not os.path.isfile(project_file):
        return False

    try:
        with open(project_file, encoding="utf-8") as f:
            for line in f:
                if line.startswith("NAME: "):
                    existing_name = line[6:].strip()
                    if existing_name == cl_name:
                        return True
        return False
    except Exception:
        return False
