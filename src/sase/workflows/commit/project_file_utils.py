"""Functions for managing project files."""

import logging
import os

from sase.ace.changespec import write_changespec_atomic
from sase.core.paths import is_valid_sase_project_name
from sase.output import print_status
from sase.workflows.utils import get_project_file_path

log = logging.getLogger(__name__)


def _log_project_creation(project: str, project_file: str) -> None:
    try:
        from sase.logs.project_creation_log import log_project_creation

        log_project_creation(project=project, project_file=project_file)
    except Exception:  # pragma: no cover - creation must not depend on logging
        log.warning("Failed to invoke project-creation logger", exc_info=True)


def _project_ref_owner(project: str) -> str | None:
    """Best-effort lookup of a project claiming *project* as a ref."""
    try:
        from sase.project_aliases import find_project_ref_owner

        return find_project_ref_owner(project)
    except Exception:  # pragma: no cover - creation must not depend on lookup
        log.warning("Failed to check project ref ownership", exc_info=True)
        return None


def create_project_file(project: str) -> bool:
    """Create a new project file if it doesn't exist.

    Uses locking and atomic writes for consistency. Refuses to mint a new
    project whose name is already claimed as another project's PROJECT_NAME
    or alias — creating one would shadow that ref and break alias
    resolution (crashing ``sase ace`` at startup).

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

    if not os.path.isfile(project_file):
        owner = _project_ref_owner(project)
        if owner is not None:
            print_status(
                f"Refusing to create project {project!r}: the name is "
                f"already used as a PROJECT_NAME or alias of {owner!r}.",
                "warning",
            )
            return False

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
            _log_project_creation(project, project_file)
            print_status(f"Created project file: {project_file}", "info")
        except Exception as e:
            print_status(f"Failed to create project file: {e}", "warning")
            return False

    return True
