"""Functions for managing project files."""

from sase.spec_writer.client import make_request, submit_spec_write_and_wait
from sase.spec_writer.models import OperationType
from sase.workflow_utils import get_project_file_path


def create_project_file(project: str) -> bool:
    """Create a new project file if it doesn't exist.

    Delegates to the spec_writer queue for consistency.

    Args:
        project: Project name.

    Returns:
        True if the file was created or already exists, False on error.
    """
    try:
        request = make_request(
            get_project_file_path(project),
            OperationType.CREATE_PROJECT_FILE,
            {"project": project},
        )
        response = submit_spec_write_and_wait(request, timeout=10.0)
        return response.success
    except Exception:
        return False
