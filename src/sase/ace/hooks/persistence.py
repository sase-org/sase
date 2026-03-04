"""Hook persistence - reading and writing hooks to ChangeSpec project files."""

import logging
import os

from sase.sase_utils import (
    ensure_sase_directory,
    make_safe_filename,
    strip_reverted_suffix,
)

from ..changespec import (
    HookEntry,
    HookStatusLine,
    LockTimeoutError,
    changespec_lock,
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

    Acquires a lock on the file for the entire read-modify-write cycle.

    Args:
        project_file: Path to the ProjectSpec file.
        changespec_name: NAME of the ChangeSpec to update.
        hooks: List of HookEntry objects to write.

    Returns:
        True if update succeeded, False otherwise.
    """
    try:
        with changespec_lock(project_file):
            write_hooks_unlocked(project_file, changespec_name, hooks)
            return True

    except Exception:
        return False


def merge_hook_updates(
    project_file: str,
    changespec_name: str,
    hook_updates: dict[str, HookEntry],
) -> bool:
    """Merge hook status updates with current disk state.

    Acquires a lock and re-reads hooks from disk before writing to avoid
    overwriting hooks added by concurrent processes (e.g., sase commit adding
    test hooks while sase axe is updating hook statuses).

    Args:
        project_file: Path to the ProjectSpec file.
        changespec_name: NAME of the ChangeSpec to update.
        hook_updates: Dict mapping hook command -> updated HookEntry.
            Only hooks in this dict will be updated; other hooks on disk
            are preserved unchanged.

    Returns:
        True if update succeeded, False otherwise.
    """
    from ..changespec import parse_project_file

    try:
        with changespec_lock(project_file):
            # Re-read current hooks from disk while holding lock
            changespecs = parse_project_file(project_file)
            current_hooks: list[HookEntry] = []
            for cs in changespecs:
                if cs.name == changespec_name:
                    current_hooks = list(cs.hooks) if cs.hooks else []
                    break

            # Deduplicate by command name (keep first occurrence) to self-heal
            # corrupted files where multi-line suffixes caused duplicate hooks
            seen_commands: set[str] = set()
            deduped_hooks: list[HookEntry] = []
            for hook in current_hooks:
                if hook.command not in seen_commands:
                    seen_commands.add(hook.command)
                    deduped_hooks.append(hook)
            current_hooks = deduped_hooks

            # Merge: use updated version if available, otherwise keep disk version
            merged_hooks: list[HookEntry] = []
            for hook in current_hooks:
                if hook.command in hook_updates:
                    merged_hooks.append(hook_updates[hook.command])
                else:
                    merged_hooks.append(hook)

            write_hooks_unlocked(project_file, changespec_name, merged_hooks)
            return True

    except LockTimeoutError:
        # Log lock timeout specifically - this is likely due to contention
        logging.warning(
            f"Lock timeout updating hooks for {changespec_name} in {project_file}"
        )
        return False
    except Exception as e:
        # Log unexpected errors
        logging.error(f"Failed to update hooks for {changespec_name}: {e}")
        return False


def update_hook_status_line_suffix_type(
    project_file: str,
    changespec_name: str,
    hook_command: str,
    commit_entry_num: str,
    new_suffix_type: str,
) -> bool:
    """Update the suffix_type of a specific hook status line.

    Re-reads hooks from disk under lock to avoid clobbering concurrent
    changes (e.g., hook_checks writing PASSED while suffix_transforms
    strips error markers in the same tick).

    Args:
        project_file: Path to the project file.
        changespec_name: NAME of the ChangeSpec.
        hook_command: The hook command to find.
        commit_entry_num: The history entry number of the status line.
        new_suffix_type: The new suffix type ("error" or "plain").

    Returns:
        True if update succeeded, False otherwise.
    """
    from ..changespec import parse_project_file

    try:
        with changespec_lock(project_file):
            # Re-read current hooks from disk while holding lock
            changespecs = parse_project_file(project_file)
            current_hooks: list[HookEntry] = []
            for cs in changespecs:
                if cs.name == changespec_name:
                    current_hooks = list(cs.hooks) if cs.hooks else []
                    break

            if not current_hooks:
                return False

            updated_hooks: list[HookEntry] = []
            found = False

            for hook in current_hooks:
                if hook.command == hook_command and hook.status_lines:
                    updated_status_lines: list[HookStatusLine] = []
                    for sl in hook.status_lines:
                        # Allow transitioning from "error" to other types, or to "plain" from any type
                        if (
                            sl.commit_entry_num == commit_entry_num
                            and sl.suffix
                            and (
                                sl.suffix_type == "error" or new_suffix_type == "plain"
                            )
                        ):
                            found = True
                            updated_status_lines.append(
                                HookStatusLine(
                                    commit_entry_num=sl.commit_entry_num,
                                    timestamp=sl.timestamp,
                                    status=sl.status,
                                    duration=sl.duration,
                                    suffix=sl.suffix,
                                    suffix_type=new_suffix_type,
                                )
                            )
                        else:
                            updated_status_lines.append(sl)
                    updated_hooks.append(
                        HookEntry(
                            command=hook.command, status_lines=updated_status_lines
                        )
                    )
                else:
                    updated_hooks.append(hook)

            if not found:
                return False

            write_hooks_unlocked(project_file, changespec_name, updated_hooks)
            return True

    except LockTimeoutError:
        logging.warning(
            f"Lock timeout updating hook suffix_type for {changespec_name} in {project_file}"
        )
        return False
    except Exception as e:
        logging.error(f"Failed to update hook suffix_type for {changespec_name}: {e}")
        return False
