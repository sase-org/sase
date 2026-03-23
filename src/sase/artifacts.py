import os
import random
import string
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sase.core.shell import get_vendored_tool, run_shell_command
from sase.core.time import get_timezone
from sase.output import (
    print_file_operation,
    print_status,
    print_workflow_header,
)

# LangGraph configuration
LANGGRAPH_RECURSION_LIMIT = 100


@dataclass
class WorkflowContext:
    """Context for a workflow run.

    Contains the workflow metadata generated during initialization,
    including the unique tag and artifacts directory path.
    """

    workflow_tag: str
    artifacts_dir: str
    workflow_name: str


def convert_timestamp_to_artifacts_format(timestamp: str) -> str:
    """Convert a YYmmdd_HHMMSS timestamp to YYYYmmddHHMMSS format.

    Args:
        timestamp: Timestamp in YYmmdd_HHMMSS format (e.g., '251227_143052').

    Returns:
        Timestamp in YYYYmmddHHMMSS format (e.g., '20251227143052').
    """
    return f"20{timestamp[:6]}{timestamp[7:]}"


def create_artifacts_directory(
    workflow_name: str,
    project_name: str | None = None,
    timestamp: str | None = None,
) -> str:
    """Create a timestamped artifacts directory using NYC Eastern timezone.

    Args:
        workflow_name: Name of the workflow (e.g., 'crs', 'new-tdd-feature')
        project_name: Name of the project. If None, will attempt to get from sase_workspace_name command
        timestamp: Optional pre-existing timestamp in YYmmdd_HHMMSS format.
            When provided, it is converted to YYYYmmddHHMMSS format for the
            artifacts directory. When None, generates a new timestamp.

    Returns:
        Path to the created artifacts directory: ~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>
    """
    if timestamp is not None:
        artifacts_timestamp = convert_timestamp_to_artifacts_format(timestamp)
    else:
        artifacts_timestamp = datetime.now(get_timezone()).strftime("%Y%m%d%H%M%S")

    # Get project name from workspace provider if not provided
    if project_name is None:
        from sase.workspace_provider import get_workspace_name

        project_name = get_workspace_name(os.getcwd())
        if not project_name:
            raise RuntimeError("Failed to detect project name from workspace provider")

    # Create artifacts directory in new location: ~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>
    artifacts_dir = os.path.expanduser(
        f"~/.sase/projects/{project_name}/artifacts/{workflow_name}/{artifacts_timestamp}"
    )
    Path(artifacts_dir).mkdir(parents=True, exist_ok=True)
    return artifacts_dir


def generate_workflow_tag() -> str:
    """Generate a unique 3-digit alphanumeric tag for the workflow run."""
    # Use digits and uppercase letters for better readability
    chars = string.digits + string.ascii_uppercase
    return "".join(random.choices(chars, k=3))


def initialize_workflow(workflow_name: str) -> WorkflowContext:
    """Initialize a workflow with standard boilerplate.

    Creates artifacts directory, prints workflow header, and initializes
    the sase.md log file.

    Args:
        workflow_name: Name of the workflow (e.g., "qa", "crs", "crs").

    Returns:
        WorkflowContext with workflow_tag and artifacts_dir.
    """
    workflow_tag = generate_workflow_tag()
    print_workflow_header(workflow_name, workflow_tag)
    print_status(f"Initializing {workflow_name} workflow", "info")
    artifacts_dir = create_artifacts_directory(workflow_name)
    print_status(f"Created artifacts directory: {artifacts_dir}", "success")
    initialize_sase_log(artifacts_dir, workflow_name, workflow_tag)
    return WorkflowContext(
        workflow_tag=workflow_tag,
        artifacts_dir=artifacts_dir,
        workflow_name=workflow_name,
    )


def run_bam_command(message: str, delay: float = 0.1) -> None:
    """Run bam command to signal completion.

    Args:
        message: Message to display with the bam notification
        delay: Delay in seconds for the bam sound (default: 0.1)
    """
    try:
        bam = get_vendored_tool("bam")
        run_shell_command(f'{bam} 3 {delay} "{message}"', capture_output=False)
    except Exception as e:
        print(f"Warning: Failed to run bam command: {e}")


def get_sase_log_file(artifacts_dir: str) -> str:
    """Get the path to the workflow-specific sase.md log file."""
    return os.path.join(artifacts_dir, "sase.md")


def _initialize_log_file(log_file: str, content: str, operation_name: str) -> None:
    """Write initial content to a log file.

    Args:
        log_file: Path to the log file to create.
        content: The formatted content to write.
        operation_name: Name for print_file_operation message.
    """
    try:
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(content)
        print_file_operation(operation_name, log_file, True)
    except Exception as e:
        print_status(f"Failed to initialize {operation_name.lower()}: {e}", "warning")


def _finalize_log_file(log_file: str, content: str, operation_name: str) -> None:
    """Append final content to a log file.

    Args:
        log_file: Path to the log file to append to.
        content: The formatted content to append.
        operation_name: Name for print_file_operation message.
    """
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(content)
        print_file_operation(operation_name, log_file, True)
    except Exception as e:
        print_status(f"Failed to finalize {operation_name.lower()}: {e}", "warning")


def initialize_sase_log(
    artifacts_dir: str, workflow_name: str, workflow_tag: str
) -> None:
    """Initialize the sase.md log file for a new workflow run.

    Args:
        artifacts_dir: Directory where the sase.md file should be stored
        workflow_name: Name of the workflow (e.g., "crs", "add-tests")
        workflow_tag: Unique workflow tag
    """
    log_file = get_sase_log_file(artifacts_dir)
    timestamp = datetime.now(get_timezone()).strftime("%Y-%m-%d %H:%M:%S %Z")

    content = f"""# SASE Workflow Log - {workflow_name} ({workflow_tag})

Started: {timestamp}
Artifacts Directory: {artifacts_dir}

"""
    _initialize_log_file(log_file, content, "Initialized SASE log")


def finalize_sase_log(
    artifacts_dir: str, workflow_name: str, workflow_tag: str, success: bool
) -> None:
    """Finalize the sase.md log file for a completed workflow run.

    Args:
        artifacts_dir: Directory where the sase.md file is stored
        workflow_name: Name of the workflow
        workflow_tag: Unique workflow tag
        success: Whether the workflow completed successfully
    """
    log_file = get_sase_log_file(artifacts_dir)
    timestamp = datetime.now(get_timezone()).strftime("%Y-%m-%d %H:%M:%S %Z")
    status = "SUCCESS" if success else "FAILED"

    content = f"""
## Workflow Completed - {timestamp}

**Status:** {status}
**Workflow:** {workflow_name}
**Tag:** {workflow_tag}
**Artifacts Directory:** {artifacts_dir}

===============================================================================

"""
    _finalize_log_file(log_file, content, "Finalized SASE log")
