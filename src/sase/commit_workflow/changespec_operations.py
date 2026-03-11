"""Functions for manipulating ChangeSpec files."""

from sase.rich_utils import print_status
from sase.spec_writer.client import make_request, submit_spec_write_and_wait
from sase.spec_writer.models import OperationType
from sase.workflow_utils import get_project_file_path


def find_changespec_end_line(lines: list[str], changespec_name: str) -> int | None:
    """Find the line number where a ChangeSpec ends.

    A ChangeSpec ends at the last non-empty line before either:
    - The next NAME: field
    - The end of the file

    Args:
        lines: List of lines from the project file.
        changespec_name: NAME of the ChangeSpec to find.

    Returns:
        The line index (0-based) of the last line of the ChangeSpec,
        or None if the ChangeSpec is not found.
    """
    in_target_changespec = False
    changespec_end = None

    for i, line in enumerate(lines):
        if line.startswith("NAME: "):
            if in_target_changespec:
                # We hit the next ChangeSpec, so the previous one ended
                # Find the last non-empty line before this
                for j in range(i - 1, -1, -1):
                    if lines[j].strip():
                        return j
                return i - 1

            # Check if this is the target ChangeSpec
            current_name = line[6:].strip()
            if current_name == changespec_name:
                in_target_changespec = True
                changespec_end = i

        elif in_target_changespec and line.strip():
            # Track the last non-empty line in the target ChangeSpec
            changespec_end = i

    # If we're still in the target ChangeSpec at the end of file
    if in_target_changespec:
        return changespec_end

    return None


def add_changespec_to_project_file(
    project: str,
    cl_name: str,
    description: str,
    parent: str | None,
    cl_url: str | None = None,
    initial_hooks: list[str] | None = None,
    initial_commits: list[tuple[int, str, str | None, str | None]] | None = None,
    bug: str | None = None,
    cl_label: str = "CL",
    status: str = "Draft",
) -> str | None:
    """Add a new ChangeSpec to the project file.

    The ChangeSpec is placed:
    - Directly after the parent ChangeSpec if parent is specified
    - At the top of the file (after BUG: header) if no parent

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project: Project name.
        cl_name: NAME field value (will be suffixed with _<N> for uniqueness).
        description: DESCRIPTION field value (raw, will be indented).
        parent: PARENT field value (or None for "None").
        cl_url: CL/PR URL (e.g., ``"http://cl/12345"`` or a GitHub PR URL).
            If None, the CL line is omitted from the ChangeSpec.
        initial_hooks: List of hook commands to include in the HOOKS field.
            If None or empty, no HOOKS field is added.
        initial_commits: List of (number, note, chat_path, diff_path) tuples
            for the COMMITS field. chat_path and diff_path are optional drawer
            paths. If None or empty, no COMMITS field is added.
        bug: BUG field value (e.g., "http://b/12345"). If None, no BUG field
            is added.
        status: STATUS field value (e.g., "Draft", "WIP"). Defaults to "Draft".

    Returns:
        The suffixed cl_name (e.g., "foo_bar_1") on success, None on failure.
    """
    project_file = get_project_file_path(project)

    try:
        request = make_request(
            project_file,
            OperationType.ADD_CHANGESPEC,
            {
                "project": project,
                "cl_name": cl_name,
                "description": description,
                "parent": parent,
                "cl_url": cl_url,
                "initial_hooks": initial_hooks,
                "initial_commits": initial_commits,
                "bug": bug,
                "cl_label": cl_label,
                "status": status,
            },
        )
        response = submit_spec_write_and_wait(request, timeout=10.0)
        if response.success and response.result:
            return response.result["cl_name"]
        return None
    except Exception as e:
        print_status(f"Failed to add ChangeSpec to project file: {e}", "warning")
        return None
