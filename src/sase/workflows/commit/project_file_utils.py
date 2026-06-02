"""Functions for managing project files."""

import os

from sase.ace.changespec import write_changespec_atomic
from sase.core.paths import is_valid_sase_project_name
from sase.output import print_status
from sase.workflows.utils import get_project_file_path


def create_project_file(project: str) -> bool:
    """Create a new project file if it doesn't exist.

    Uses locking and atomic writes for consistency.

    Args:
        project: Project name.

    Returns:
        True if the file was created or already exists, False on error.
    """
    if not is_valid_sase_project_name(project):
        print_status(f"Invalid project name: {project!r}", "warning")
        return False

    project_file = get_project_file_path(project)
    project_dir = os.path.dirname(project_file)

    # Create directory if it doesn't exist
    try:
        os.makedirs(project_dir, exist_ok=True)
    except Exception as e:
        print_status(f"Failed to create project directory: {e}", "warning")
        return False

    # Create file if it doesn't exist
    if not os.path.isfile(project_file):
        try:
            # Use atomic write for new file creation
            write_changespec_atomic(
                project_file,
                "",
                f"Create project file for {project}",
            )
            print_status(f"Created project file: {project_file}", "info")
        except Exception as e:
            print_status(f"Failed to create project file: {e}", "warning")
            return False

    return True
