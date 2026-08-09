"""Hook persistence - reading and writing hooks to Patch project files."""

import logging
from collections.abc import Callable
from dataclasses import replace

from sase.core.patch import strip_reverted_suffix
from sase.core.paths import make_safe_filename, sharded_path

from ..patch import (
    HookEntry,
    HookStatusLine,
    LockTimeoutError,
    patch_lock,
    write_patch_atomic,
)
from .formatting import apply_hooks_update, format_hooks_field


def get_hook_output_path(name: str, timestamp: str) -> str:
    """Get the output file path for a hook run.

    Args:
        name: The Patch name.
        timestamp: The timestamp in YYmmdd_HHMMSS format.

    Returns:
        Full path to the hook output file.
    """
    safe_name = make_safe_filename(strip_reverted_suffix(name))
    filename = f"{safe_name}-{timestamp}.txt"
    return sharded_path("hooks", filename)


def write_hooks_unlocked(
    project_file: str,
    patch_name: str,
    hooks: list[HookEntry],
) -> bool:
    """Write hooks to file. Must be called while holding the lock.

    Args:
        project_file: Path to the ProjectSpec file.
        patch_name: NAME of the Patch to update.
        hooks: List of HookEntry objects to write.

    Returns:
        True if the file content changed, False if the update was a no-op.
    """
    with open(project_file, encoding="utf-8") as f:
        lines = f.readlines()

    updated_lines = apply_hooks_update(lines, patch_name, hooks)
    updated_content = "".join(updated_lines)
    if updated_content == "".join(lines):
        return False

    write_patch_atomic(
        project_file,
        updated_content,
        f"Update HOOKS for {patch_name}",
    )
    return True


def update_patch_hooks_field(
    project_file: str,
    patch_name: str,
    hooks: list[HookEntry],
) -> bool:
    """Update the HOOKS field in the project file.

    Acquires a lock on the file for the entire read-modify-write cycle.

    Args:
        project_file: Path to the ProjectSpec file.
        patch_name: NAME of the Patch to update.
        hooks: List of HookEntry objects to write.

    Returns:
        True if update succeeded, False otherwise.
    """
    try:
        with patch_lock(project_file):
            write_hooks_unlocked(project_file, patch_name, hooks)
            return True

    except Exception:
        return False


def _normalize_parsed_plain_suffix_types(hooks: list[HookEntry]) -> list[HookEntry]:
    """Mark unprefixed parsed suffixes as explicit plain values.

    The parser represents an unprefixed on-disk suffix with ``suffix_type=None``.
    The formatter treats ``None`` as permission to infer a marker from the suffix
    text, so a fresh read-modify-write must make the absence of a prefix explicit
    to avoid turning values such as ``ZOMBIE`` back into errors.
    """
    normalized_hooks: list[HookEntry] = []
    for hook in hooks:
        if not hook.status_lines:
            normalized_hooks.append(hook)
            continue

        normalized_status_lines = [
            replace(status_line, suffix_type="plain")
            if status_line.suffix is not None and status_line.suffix_type is None
            else status_line
            for status_line in hook.status_lines
        ]
        normalized_hooks.append(replace(hook, status_lines=normalized_status_lines))
    return normalized_hooks


def transform_patch_hooks_field(
    project_file: str,
    patch_name: str,
    transform: Callable[[list[HookEntry]], list[HookEntry]],
) -> bool:
    """Transform the current HOOKS field under the Patch lock.

    The Patch is parsed from disk after acquiring the lock. The transformed
    hooks are persisted only when they differ from the current hooks, so ``True``
    means an actual write occurred rather than merely a successful no-op.

    Args:
        project_file: Path to the ProjectSpec file.
        patch_name: NAME of the Patch to update.
        transform: Pure hook-list transformation to apply to current disk state.

    Returns:
        True if the hooks were changed and persisted, False otherwise.
    """
    from ..patch import parse_project_file

    try:
        with patch_lock(project_file):
            patches = parse_project_file(project_file)
            patch = next((cs for cs in patches if cs.name == patch_name), None)
            if patch is None:
                return False

            current_hooks = _normalize_parsed_plain_suffix_types(
                list(patch.hooks or [])
            )
            updated_hooks = transform(current_hooks)
            if updated_hooks == current_hooks:
                return False

            return write_hooks_unlocked(
                project_file,
                patch_name,
                updated_hooks,
            )

    except LockTimeoutError:
        logging.warning(
            f"Lock timeout transforming hooks for {patch_name} in {project_file}"
        )
        return False
    except Exception as e:
        logging.error(f"Failed to transform hooks for {patch_name}: {e}")
        return False


def merge_hook_updates(
    project_file: str,
    patch_name: str,
    hook_updates: dict[str, HookEntry],
) -> bool:
    """Merge hook status updates with current disk state.

    Acquires a lock and re-reads hooks from disk before writing to avoid
    overwriting hooks added by concurrent processes (e.g., sase commit adding
    test hooks while sase axe is updating hook statuses).

    Args:
        project_file: Path to the ProjectSpec file.
        patch_name: NAME of the Patch to update.
        hook_updates: Dict mapping hook command -> updated HookEntry.
            Only hooks in this dict will be updated; other hooks on disk
            are preserved unchanged.

    Returns:
        True if update succeeded, False otherwise.
    """
    from ..patch import parse_project_file

    try:
        with patch_lock(project_file):
            # Re-read current hooks from disk while holding lock
            patches = parse_project_file(project_file)
            current_hooks: list[HookEntry] = []
            for cs in patches:
                if cs.name == patch_name:
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

            write_hooks_unlocked(project_file, patch_name, merged_hooks)

            # Log hook completion events for terminal statuses
            try:
                from sase.logs.run_log import log_event

                for cmd, entry in hook_updates.items():
                    for sl in entry.status_lines or []:
                        if sl.status in ("PASSED", "FAILED"):
                            log_event(
                                event="hook_completed",
                                hook=cmd,
                                cl_name=patch_name,
                                status=sl.status,
                                duration=sl.duration,
                            )
            except Exception:
                pass  # Best effort

            return True

    except LockTimeoutError:
        # Log lock timeout specifically - this is likely due to contention
        logging.warning(
            f"Lock timeout updating hooks for {patch_name} in {project_file}"
        )
        return False
    except Exception as e:
        # Log unexpected errors
        logging.error(f"Failed to update hooks for {patch_name}: {e}")
        return False


def update_hook_status_line_suffix_type(
    project_file: str,
    patch_name: str,
    hook_command: str,
    stitch_num: str,
    new_suffix_type: str,
) -> bool:
    """Update the suffix_type of a specific hook status line.

    Re-reads hooks from disk under lock to avoid clobbering concurrent
    changes (e.g., hook_checks writing PASSED while suffix_transforms
    strips error markers in the same tick).

    Args:
        project_file: Path to the project file.
        patch_name: NAME of the Patch.
        hook_command: The hook command to find.
        stitch_num: The history entry number of the status line.
        new_suffix_type: The new suffix type ("error" or "plain").

    Returns:
        True if update succeeded, False otherwise.
    """

    def transform(hooks: list[HookEntry]) -> list[HookEntry]:
        updated_hooks: list[HookEntry] = []
        for hook in hooks:
            if hook.command != hook_command or not hook.status_lines:
                updated_hooks.append(hook)
                continue

            updated_status_lines: list[HookStatusLine] = []
            for status_line in hook.status_lines:
                # Allow transitioning from "error" to other types, or to
                # "plain" from any type.
                if (
                    status_line.stitch_num == stitch_num
                    and status_line.suffix
                    and (
                        status_line.suffix_type == "error" or new_suffix_type == "plain"
                    )
                ):
                    updated_status_lines.append(
                        replace(status_line, suffix_type=new_suffix_type)
                    )
                else:
                    updated_status_lines.append(status_line)
            updated_hooks.append(replace(hook, status_lines=updated_status_lines))

        return updated_hooks

    return transform_patch_hooks_field(
        project_file,
        patch_name,
        transform,
    )


update_changespec_hooks_field = update_patch_hooks_field  # legacy compatibility alias
transform_changespec_hooks_field = (
    transform_patch_hooks_field  # legacy compatibility alias
)
