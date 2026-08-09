"""Check cycle runner for full and comment check cycles.

This module handles the longer-interval check cycles (1-5 minutes) that
start PR submitted checks and comment checks for Patches.
"""

import time
from collections.abc import Callable
from datetime import datetime

from sase.ace.patch import (
    Patch,
    find_all_patches,
    get_base_status,
    is_edit_locked,
)
from sase.ace.pr_status import is_parent_submitted
from sase.ace.comments import is_timestamp_suffix
from sase.ace.scheduler.checks_runner import (
    CHECK_TYPE_CL_SUBMITTED,
    CHECK_TYPE_REVIEWER_COMMENTS,
    has_pending_check,
    start_cl_submitted_check,
    start_reviewer_comments_check,
)
from sase.ace.sync_cache import should_check, update_last_checked
from sase.core.query_facade import evaluate_query_many
from sase.core.time import get_timezone
from sase.running_field import get_workspace_directory

from .state import CycleResult, write_cycle_result

# Type alias for log callback
LogCallback = Callable[[str, str | None], None]


class CheckCycleRunner:
    """Runner for full and comment check cycles.

    Handles the longer-interval check cycles that:
    - Start PR submitted checks (full cycle)
    - Start reviewer/author comment checks (comment cycle)
    """

    def __init__(
        self,
        query: str | None,
        log_callback: LogCallback,
    ) -> None:
        """Initialize the check cycle runner.

        Args:
            query: Query string for filtering Patches (or None/empty for all).
            log_callback: Callback function for logging messages.
        """
        self.query = query or None
        self._log = log_callback
        self._first_cycle = True

    def set_first_cycle_done(self) -> None:
        """Mark the first cycle as completed."""
        self._first_cycle = False

    def is_first_cycle(self) -> bool:
        """Check if this is still the first cycle."""
        return self._first_cycle

    def get_all_patches(self) -> list[Patch]:
        """Get all patches (unfiltered)."""
        return find_all_patches()

    def get_filtered_patches(
        self, all_patches: list[Patch] | None = None
    ) -> list[Patch]:
        """Get all patches filtered by query.

        Args:
            all_patches: Optional pre-fetched list of all patches.

        Returns:
            List of patches matching the query filter.
        """
        if all_patches is None:
            all_patches = find_all_patches()

        # Remove patches from edit-locked project files
        unlocked = [cs for cs in all_patches if not is_edit_locked(cs.file_path)]
        if len(unlocked) < len(all_patches):
            skipped = len(all_patches) - len(unlocked)
            self._log(f"Skipping {skipped} patch(s) due to edit lock", None)

        if not self.query:
            return unlocked

        mask = evaluate_query_many(self.query, unlocked)
        return [cs for cs, keep in zip(unlocked, mask, strict=True) if keep]

    def is_leaf_cl(self, patch: Patch) -> bool:
        """Check if a Patch is a leaf Patch (no parent or parent is submitted)."""
        return is_parent_submitted(patch)

    def should_check_status(self, patch: Patch, bypass_cache: bool = False) -> bool:
        """Determine if a Patch's status should be checked.

        Uses sync_cache to throttle checks to minimum 5-minute intervals.

        Args:
            patch: The Patch to check.
            bypass_cache: If True, skip the cache check.

        Returns:
            True if the Patch should be checked, False otherwise.
        """
        if bypass_cache:
            return True
        return should_check(patch.name)

    def run_full_check_cycle(self) -> tuple[datetime, int, list[dict]]:
        """Run full status check cycle - starts PR submitted checks only.

        Returns:
            Tuple of (cycle_timestamp, patches_processed, updates_list).
        """
        start = time.time()
        all_patches = self.get_all_patches()
        filtered_patches = self.get_filtered_patches(all_patches)
        updates: list[dict] = []

        for patch in filtered_patches:
            # On first cycle, bypass cache for leaf Patches
            bypass_cache = self._first_cycle and self.is_leaf_cl(patch)

            # Start PR submitted checks only
            check_updates = self._start_cl_submitted_check(patch, bypass_cache)
            for update in check_updates:
                updates.append({"patch": patch.name, "message": update})
                self._log(f"* {patch.name}: {update}", "green bold")

        cycle_timestamp = datetime.now(get_timezone())
        self._first_cycle = False

        # Write cycle result
        duration_ms = int((time.time() - start) * 1000)
        result = CycleResult(
            timestamp=cycle_timestamp.isoformat(),
            cycle_type="full",
            duration_ms=duration_ms,
            patches_processed=len(filtered_patches),
            updates=updates,
            errors=[],
        )
        write_cycle_result(result)

        summary = (
            "pr_submitted_checks: "
            f"all_patches={len(all_patches)} "
            f"filtered_patches={len(filtered_patches)} "
            f"processed={len(filtered_patches)} started={len(updates)} "
            f"updates={len(updates)} duration_ms={duration_ms}"
        )
        if not updates:
            summary += " reason="
            summary += (
                "no_matching_patches"
                if not filtered_patches
                else "no_eligible_pr_submitted_checks"
            )
        self._log(summary, "green" if updates else None)

        return cycle_timestamp, len(filtered_patches), updates

    def run_comment_check_cycle(self) -> tuple[datetime, int, list[dict]]:
        """Run comment check cycle - starts reviewer/author comment checks.

        Returns:
            Tuple of (cycle_timestamp, patches_processed, updates_list).
        """
        start = time.time()
        all_patches = self.get_all_patches()
        filtered_patches = self.get_filtered_patches(all_patches)
        updates: list[dict] = []

        for patch in filtered_patches:
            # Start comment checks (no cache throttling - has its own interval)
            check_updates = self._start_comment_checks(patch)
            for update in check_updates:
                updates.append({"patch": patch.name, "message": update})
                self._log(f"* {patch.name}: {update}", "green bold")

        cycle_timestamp = datetime.now(get_timezone())

        # Write cycle result
        duration_ms = int((time.time() - start) * 1000)
        result = CycleResult(
            timestamp=cycle_timestamp.isoformat(),
            cycle_type="comment",
            duration_ms=duration_ms,
            patches_processed=len(filtered_patches),
            updates=updates,
            errors=[],
        )
        write_cycle_result(result)

        mailed_count = sum(
            1 for patch in filtered_patches if get_base_status(patch.status) == "Mailed"
        )
        summary = (
            "comment_checks: "
            f"all_patches={len(all_patches)} "
            f"filtered_patches={len(filtered_patches)} "
            f"mailed={mailed_count} processed={len(filtered_patches)} "
            f"started={len(updates)} updates={len(updates)} duration_ms={duration_ms}"
        )
        if not updates:
            if not filtered_patches:
                reason = "no_matching_patches"
            elif mailed_count == 0:
                reason = "no_mailed_patches"
            else:
                reason = "no_eligible_comment_checks"
            summary += f" reason={reason}"
        self._log(summary, "green" if updates else None)

        return cycle_timestamp, len(filtered_patches), updates

    def _start_cl_submitted_check(
        self, patch: Patch, bypass_cache: bool = False
    ) -> list[str]:
        """Start PR submitted check for a Patch (non-blocking).

        Args:
            patch: The Patch to check.
            bypass_cache: If True, skip the cache check.

        Returns:
            List of update messages for checks that were started.
        """
        updates: list[str] = []

        # Get workspace directory
        try:
            workspace_dir = get_workspace_directory(patch.project_basename)
        except RuntimeError:
            workspace_dir = None

        # Check if we should run status checks
        if not self.should_check_status(patch, bypass_cache):
            return updates

        # Update cache when starting checks
        update_last_checked(patch.name)

        # Start PR submitted check if not already pending
        if not has_pending_check(patch, CHECK_TYPE_CL_SUBMITTED):
            if is_parent_submitted(patch) and patch.pr_url:
                update = start_cl_submitted_check(patch, workspace_dir, self._log)
                if update:
                    updates.append(update)

        return updates

    def _start_comment_checks(self, patch: Patch) -> list[str]:
        """Start reviewer comment checks for a Patch (non-blocking).

        Comment checks bypass the sync_cache since they have their own interval.

        Args:
            patch: The Patch to check.

        Returns:
            List of update messages for checks that were started.
        """
        updates: list[str] = []

        # Get workspace directory
        try:
            workspace_dir = get_workspace_directory(patch.project_basename)
        except RuntimeError:
            workspace_dir = None

        if not workspace_dir:
            return updates

        # Start reviewer comments check if conditions are met
        if not has_pending_check(patch, CHECK_TYPE_REVIEWER_COMMENTS):
            if get_base_status(patch.status) == "Mailed":
                # Check if we need to start
                existing_reviewer_entry = None
                if patch.comments:
                    for entry in patch.comments:
                        if entry.reviewer == "critique":
                            existing_reviewer_entry = entry
                            break
                should_start = existing_reviewer_entry is None or (
                    existing_reviewer_entry.suffix is not None
                    and not is_timestamp_suffix(existing_reviewer_entry.suffix)
                )
                if should_start:
                    update = start_reviewer_comments_check(
                        patch, workspace_dir, self._log
                    )
                    if update:
                        updates.append(update)

        return updates
