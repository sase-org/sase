"""Patch validation functions."""

from collections.abc import Iterable

from .models import Patch, get_base_status


def has_any_status_suffix(patch: Patch) -> bool:
    """Check if a Patch has any error suffix in status, stitches, hooks, or comments."""
    if " - (!: " in patch.status:
        return True
    if patch.stitches:
        for stitch in patch.stitches:
            if stitch.suffix_type == "error":
                return True
    if patch.hooks:
        for hook in patch.hooks:
            if hook.status_lines:
                for line in hook.status_lines:
                    if line.suffix_type == "error":
                        return True
    if patch.comments:
        for comment in patch.comments:
            if comment.suffix_type == "error":
                return True
    return False


def has_any_error_suffix(patch: Patch) -> bool:
    """Check if a Patch has any error suffixes."""
    return has_any_status_suffix(patch)


def is_parent_ready_for_mail(patch: Patch, all_patches: list[Patch]) -> bool:
    """Check if a Patch's parent is ready for mail."""
    if patch.parent is None:
        return True
    for candidate in all_patches:
        if candidate.name == patch.parent:
            return get_base_status(candidate.status) in ("Submitted", "Mailed")
    return True


def get_current_and_proposal_stitch_ids(patch: Patch) -> list[str]:
    """Get the current stitch ID and all proposal stitch IDs for that number."""
    if not patch.stitches:
        return []

    current_stitch = None
    for stitch in reversed(patch.stitches):
        if not stitch.is_proposed:
            current_stitch = stitch
            break

    if current_stitch is None:
        return []

    current_number = current_stitch.number
    result = [str(current_number)]
    for stitch in patch.stitches:
        if stitch.is_proposed and stitch.number == current_number:
            result.append(stitch.display_number)
    return result


def get_current_and_proposal_entry_ids(patch: Patch) -> list[str]:
    """Legacy alias for :func:`get_current_and_proposal_stitch_ids`."""
    return get_current_and_proposal_stitch_ids(patch)


def all_hooks_passed_for_stitches(patch: Patch, stitch_ids: list[str]) -> bool:
    """Check if all hooks have PASSED status for the given stitch IDs."""
    if not patch.hooks or not stitch_ids:
        return True

    for hook in patch.hooks:
        if hook.skip_proposal_runs:
            continue
        for stitch_id in stitch_ids:
            status_line = hook.get_status_line_for_stitch(stitch_id)
            if status_line is None or status_line.status != "PASSED":
                return False
    return True


def all_hooks_passed_for_entries(patch: Patch, entry_ids: list[str]) -> bool:
    """Legacy alias for :func:`all_hooks_passed_for_stitches`."""
    return all_hooks_passed_for_stitches(patch, entry_ids)


def has_any_running_agent(patch: Patch) -> bool:
    """Check if Patch has any running agents in hooks, comments, or mentors."""
    if patch.hooks:
        for hook in patch.hooks:
            if hook.status_lines:
                for hook_line in hook.status_lines:
                    if hook_line.suffix_type == "running_agent":
                        return True
    if patch.comments:
        for comment in patch.comments:
            if comment.suffix_type == "running_agent":
                return True
    if patch.mentors:
        for mentor in patch.mentors:
            if mentor.status_lines:
                for mentor_line in mentor.status_lines:
                    if mentor_line.suffix_type == "running_agent":
                        return True
    return False


def has_any_running_process(patch: Patch) -> bool:
    """Check if Patch has any running hook processes."""
    if patch.hooks:
        for hook in patch.hooks:
            if hook.status_lines:
                for line in hook.status_lines:
                    if line.suffix_type == "running_process":
                        return True
    return False


def count_running_hooks_global() -> int:
    """Count running hook processes across all Patches."""
    from . import find_all_patches

    count = 0
    for patch in find_all_patches():
        if patch.hooks:
            for hook in patch.hooks:
                if hook.status_lines:
                    for line in hook.status_lines:
                        if line.suffix_type == "running_process":
                            count += 1
    return count


def count_running_agents_global() -> int:
    """Count running agents across all Patches."""
    from . import find_all_patches

    count = 0
    for patch in find_all_patches():
        if patch.hooks:
            for hook in patch.hooks:
                if hook.status_lines:
                    for hook_line in hook.status_lines:
                        if hook_line.suffix_type == "running_agent":
                            count += 1
        if patch.comments:
            for comment in patch.comments:
                if comment.suffix_type == "running_agent":
                    count += 1
    return count


def _count_hook_runners(patches: Iterable[Patch]) -> int:
    """Count limited running hook processes across *patches*."""
    count = 0
    for patch in patches:
        if patch.hooks:
            for hook in patch.hooks:
                if hook.is_unlimited:
                    continue
                if hook.status_lines:
                    for line in hook.status_lines:
                        if line.suffix_type == "running_process":
                            count += 1
    return count


def _count_agent_runners(patches: Iterable[Patch]) -> int:
    """Count running agents across *patches*, across hooks, comments, and mentors."""
    count = 0
    for patch in patches:
        if patch.hooks:
            for hook in patch.hooks:
                if hook.status_lines:
                    for line in hook.status_lines:
                        if line.suffix_type == "running_agent":
                            count += 1
        if patch.comments:
            for comment in patch.comments:
                if comment.suffix_type == "running_agent":
                    count += 1
        if patch.mentors:
            for mentor in patch.mentors:
                if mentor.status_lines:
                    for mentor_line in mentor.status_lines:
                        if mentor_line.suffix_type == "running_agent":
                            count += 1
    return count


def count_hook_runners_global() -> int:
    """Count limited running hook processes globally."""
    from . import find_all_patches

    return _count_hook_runners(find_all_patches())


def count_agent_runners_global() -> int:
    """Count running agents globally across hooks, comments, and mentors."""
    from . import find_all_patches

    return _count_agent_runners(find_all_patches())


def count_hook_and_agent_runners_global() -> tuple[int, int]:
    """Count hook and agent runners globally from one shared cached Patch load.

    Callers that need both counts should use this instead of calling
    ``count_hook_runners_global`` and ``count_agent_runners_global``
    separately, which each independently parse the full ProjectSpec archive.
    This loads the archive once through the cached snapshot and counts both
    from the same Patch list. The cache returns Patch objects shared across
    callers, but these counters only read them, so sharing is safe here.
    """
    from .cache import find_all_patches_cached

    patches = find_all_patches_cached()
    return _count_hook_runners(patches), _count_agent_runners(patches)


def count_all_runners_global() -> int:
    """Count all running hook processes and agents globally.

    Both counts come from one shared cached Patch load rather than two
    independent full-archive parses. Runner-pool admission control calls this
    per tick, some of it while holding the shared counter's exclusive lock, so
    the second parse was pure latency inside that critical section. Counting
    both from the same snapshot also removes a torn read: the two separate
    parses could observe different on-disk states.
    """
    hook_runners, agent_runners = count_hook_and_agent_runners_global()
    return hook_runners + agent_runners
