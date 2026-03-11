"""Hook persistence - reading and writing hooks to ChangeSpec project files."""

import os

from sase.sase_utils import (
    ensure_sase_directory,
    make_safe_filename,
    strip_reverted_suffix,
)

from ..changespec import (
    HookEntry,
    write_changespec_atomic,
)
from .formatting import apply_hooks_update, format_hooks_field


def get_hook_output_path(name: str, timestamp: str) -> str:
    """Get the output file path for a hook run.

    Args:
        name: The ChangeSpec name.
        timestamp: The timestamp in YYmmdd_HHMMSS format.

    Returns:
        Full path to the hook output file.
    """
    hooks_dir = ensure_sase_directory("hooks")
    safe_name = make_safe_filename(strip_reverted_suffix(name))
    filename = f"{safe_name}-{timestamp}.txt"
    return os.path.join(hooks_dir, filename)


def write_hooks_unlocked(
    project_file: str,
    changespec_name: str,
    hooks: list[HookEntry],
) -> None:
    """Write hooks to file. Must be called while holding the lock.

    Args:
        project_file: Path to the ProjectSpec file.
        changespec_name: NAME of the ChangeSpec to update.
        hooks: List of HookEntry objects to write.
    """
    with open(project_file, encoding="utf-8") as f:
        lines = f.readlines()

    updated_lines = apply_hooks_update(lines, changespec_name, hooks)

    write_changespec_atomic(
        project_file,
        "".join(updated_lines),
        f"Update HOOKS for {changespec_name}",
    )


def update_changespec_hooks_field(
    project_file: str,
    changespec_name: str,
    hooks: list[HookEntry],
) -> bool:
    """Update the HOOKS field in the project file.

    Submits a SET_HOOKS request through the spec_writer queue.

    Args:
        project_file: Path to the ProjectSpec file.
        changespec_name: NAME of the ChangeSpec to update.
        hooks: List of HookEntry objects to write.

    Returns:
        True if update succeeded, False otherwise.
    """
    from dataclasses import asdict

    from sase.spec_writer.client import make_request, submit_spec_write_and_wait
    from sase.spec_writer.models import OperationType

    try:
        request = make_request(
            project_file,
            OperationType.SET_HOOKS,
            {
                "changespec_name": changespec_name,
                "hooks": [asdict(h) for h in hooks],
            },
        )
        response = submit_spec_write_and_wait(request, timeout=10.0)
        return response.success
    except Exception:
        return False


def merge_hook_updates(
    project_file: str,
    changespec_name: str,
    hook_updates: dict[str, HookEntry],
) -> bool:
    """Merge hook status updates with current disk state.

    Submits a MERGE_HOOKS request through the spec_writer queue.

    Args:
        project_file: Path to the ProjectSpec file.
        changespec_name: NAME of the ChangeSpec to update.
        hook_updates: Dict mapping hook command -> updated HookEntry.
            Only hooks in this dict will be updated; other hooks on disk
            are preserved unchanged.

    Returns:
        True if update succeeded, False otherwise.
    """
    from dataclasses import asdict

    from sase.spec_writer.client import make_request, submit_spec_write_and_wait
    from sase.spec_writer.models import OperationType

    try:
        request = make_request(
            project_file,
            OperationType.MERGE_HOOKS,
            {
                "changespec_name": changespec_name,
                "hook_updates": {k: asdict(v) for k, v in hook_updates.items()},
            },
        )
        response = submit_spec_write_and_wait(request, timeout=10.0)
        return response.success
    except Exception:
        return False


def update_hook_status_line_suffix_type(
    project_file: str,
    changespec_name: str,
    hook_command: str,
    commit_entry_num: str,
    new_suffix_type: str,
) -> bool:
    """Update the suffix_type of a specific hook status line.

    Submits an UPDATE_HOOK_SUFFIX_TYPE request through the spec_writer queue.

    Args:
        project_file: Path to the project file.
        changespec_name: NAME of the ChangeSpec.
        hook_command: The hook command to find.
        commit_entry_num: The history entry number of the status line.
        new_suffix_type: The new suffix type ("error" or "plain").

    Returns:
        True if update succeeded, False otherwise.
    """
    from sase.spec_writer.client import make_request, submit_spec_write_and_wait
    from sase.spec_writer.models import OperationType

    try:
        request = make_request(
            project_file,
            OperationType.UPDATE_HOOK_SUFFIX_TYPE,
            {
                "changespec_name": changespec_name,
                "hook_command": hook_command,
                "commit_entry_num": commit_entry_num,
                "new_suffix_type": new_suffix_type,
            },
        )
        response = submit_spec_write_and_wait(request, timeout=10.0)
        return response.success
    except Exception:
        return False
