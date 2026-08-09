"""Hook job runner for short-interval hook cycle jobs.

This module handles the 1-second interval hook cycle jobs that check
completions, start hooks/mentors/workflows, and perform cleanup tasks.
"""

from collections.abc import Callable
from datetime import datetime

from sase.ace.patch import Patch
from sase.ace.scheduler.checks_runner import (
    reap_orphan_check_files,
    process_pending_checks_for,
    scan_all_pending_checks,
)
from sase.ace.scheduler.comments_handler import check_comment_zombies
from sase.ace.scheduler.hook_checks import check_hooks
from sase.ace.scheduler.mentor_checks import check_mentors
from sase.ace.scheduler.orphan_cleanup import cleanup_orphaned_workspace_claims
from sase.ace.scheduler.stale_running_cleanup import cleanup_stale_running_entries
from sase.ace.scheduler.suffix_transforms import (
    strip_old_entry_error_markers,
    strip_terminal_status_markers,
    transform_old_proposal_suffixes,
)
from sase.ace.scheduler.workflows_runner import (
    check_and_complete_workflows,
    start_stale_workflows,
)
from sase.config.mentor import get_all_mentor_profiles
from sase.core.paths import make_safe_filename
from sase.core.time import get_timezone

from .state import AxeMetrics

# Type alias for log callback
LogCallback = Callable[[str, str | None], None]


def _count_entries(patches: list[Patch], attr: str) -> int:
    return sum(len(getattr(patch, attr) or []) for patch in patches)


def _format_noop_reason(
    *, inspected_patches: int, inspected_entries: int, noun: str
) -> str:
    if inspected_patches == 0:
        return "no_matching_patches"
    if inspected_entries == 0:
        return f"no_{noun}"
    return "no_updates_or_launches"


class HookJobRunner:
    """Runner for hook cycle jobs.

    Handles the short-interval (1 second) jobs that:
    - Check hook/mentor/workflow completions and start new ones
    - Poll for pending check results
    - Handle zombie comment entries
    - Run suffix transformations
    - Clean up orphaned workspace claims
    - Clean up stale RUNNING entries
    """

    def __init__(
        self,
        metrics: AxeMetrics,
        zombie_timeout_seconds: int,
        max_hook_runners: int,
        max_agent_runners: int,
        log_callback: LogCallback,
        verbose_diagnostics: bool = False,
    ) -> None:
        """Initialize the hook job runner.

        Args:
            metrics: Metrics object for tracking statistics.
            zombie_timeout_seconds: Timeout in seconds for zombie detection.
            max_hook_runners: Maximum concurrent hook runners allowed.
            max_agent_runners: Maximum concurrent agent runners allowed.
            log_callback: Callback function for logging messages.
        """
        self.metrics = metrics
        self.zombie_timeout_seconds = zombie_timeout_seconds
        self.max_hook_runners = max_hook_runners
        self.max_agent_runners = max_agent_runners
        self._log = log_callback
        self.verbose_diagnostics = verbose_diagnostics
        self._hooks_started_this_tick = 0
        self._agents_started_this_tick = 0

    def run_hook_checks(self, filtered_patches: list[Patch]) -> None:
        """Run hook completion and startup checks.

        Args:
            filtered_patches: List of patches to check.
        """
        self._hooks_started_this_tick = 0
        self._agents_started_this_tick = 0
        updates_before = self.metrics.total_updates
        hooks_started_before = self.metrics.hooks_started
        inspected_hooks = _count_entries(filtered_patches, "hooks")

        for patch in filtered_patches:
            if not patch.hooks:
                continue

            hook_updates, hooks_started = check_hooks(
                patch,
                self._log,
                self.zombie_timeout_seconds,
                self.max_hook_runners,
                self._hooks_started_this_tick,
            )

            self._hooks_started_this_tick += hooks_started
            self.metrics.hooks_started += hooks_started
            self.metrics.total_updates += len(hook_updates)

            for update in hook_updates:
                self._log(f"* {patch.name}: {update}", "green bold")

        updates = self.metrics.total_updates - updates_before
        started = self.metrics.hooks_started - hooks_started_before
        summary = (
            "hook_checks: "
            f"patches={len(filtered_patches)} hooks={inspected_hooks} "
            f"updates={updates} started={started}"
        )
        if updates == 0 and started == 0:
            summary += " reason=" + _format_noop_reason(
                inspected_patches=len(filtered_patches),
                inspected_entries=inspected_hooks,
                noun="hooks",
            )
        self._log(summary, "green" if updates or started else None)

    def run_mentor_checks(self, filtered_patches: list[Patch]) -> None:
        """Run mentor completion and startup checks.

        Args:
            filtered_patches: List of patches to check.
        """
        updates_before = self.metrics.total_updates
        mentors_started_before = self.metrics.mentors_started
        inspected_mentors = _count_entries(filtered_patches, "mentors")
        all_profiles = get_all_mentor_profiles()
        for patch in filtered_patches:
            mentor_updates, mentors_started = check_mentors(
                patch,
                self._log,
                self.zombie_timeout_seconds,
                self.max_agent_runners,
                self._agents_started_this_tick,
                mentor_profiles=all_profiles,
                verbose_diagnostics=self.verbose_diagnostics,
            )

            self._agents_started_this_tick += mentors_started
            self.metrics.mentors_started += mentors_started
            self.metrics.total_updates += len(mentor_updates)

            for update in mentor_updates:
                self._log(f"* {patch.name}: {update}", "green bold")

        updates = self.metrics.total_updates - updates_before
        started = self.metrics.mentors_started - mentors_started_before
        summary = (
            "mentor_checks: "
            f"patches={len(filtered_patches)} mentors={inspected_mentors} "
            f"profiles={len(all_profiles)} updates={updates} started={started}"
        )
        if updates == 0 and started == 0:
            summary += " reason=" + _format_noop_reason(
                inspected_patches=len(filtered_patches),
                inspected_entries=inspected_mentors,
                noun="mentors",
            )
        self._log(summary, "green" if updates or started else None)

    def run_workflow_checks(self, filtered_patches: list[Patch]) -> None:
        """Run CRS/fix-hook workflow checks.

        Args:
            filtered_patches: List of patches to check.
        """
        updates_before = self.metrics.total_updates
        workflows_started_before = self.metrics.workflows_started
        for patch in filtered_patches:
            # Check completion of running workflows
            completion_updates = check_and_complete_workflows(patch, self._log)
            self.metrics.total_updates += len(completion_updates)

            for update in completion_updates:
                self._log(f"* {patch.name}: {update}", "green bold")

            # Start stale workflows
            start_updates, started, _ = start_stale_workflows(
                patch,
                self._log,
                self.max_agent_runners,
                self._agents_started_this_tick,
            )

            self._agents_started_this_tick += started
            self.metrics.workflows_started += started
            self.metrics.total_updates += len(start_updates)

            for update in start_updates:
                self._log(f"* {patch.name}: {update}", "green bold")

        updates = self.metrics.total_updates - updates_before
        started = self.metrics.workflows_started - workflows_started_before
        summary = (
            "workflow_checks: "
            f"patches={len(filtered_patches)} updates={updates} "
            f"started={started}"
        )
        if updates == 0 and started == 0:
            summary += " reason="
            summary += (
                "no_matching_patches"
                if not filtered_patches
                else "no_workflow_updates_or_launches"
            )
        self._log(summary, "green" if updates or started else None)

    def run_pending_checks_poll(self, filtered_patches: list[Patch]) -> None:
        """Poll for completed background checks.

        Walks ~/.sase/checks/ once per tick (O(M) in file count), dispatches
        per-Patch work from the single scan, and reaps orphaned output
        files left behind by killed or crashed background checks.

        Args:
            filtered_patches: List of patches to check.
        """
        updates_before = self.metrics.total_updates
        reaped = reap_orphan_check_files(self._log)
        by_name = scan_all_pending_checks()
        pending_files = sum(len(pending) for pending in by_name.values())
        matched_files = 0
        unmatched_groups = 0

        # Filenames encode Patch names via make_safe_filename(), which is
        # lossy (e.g. "foo-bar" and "foo_bar" both map to "foo_bar").  Any
        # collisions here inherit a pre-existing ambiguity in the filename
        # format and are not resolved in this poll.
        safe_to_cs = {make_safe_filename(cs.name): cs for cs in filtered_patches}
        for safe_name, pending in by_name.items():
            patch = safe_to_cs.get(safe_name)
            if patch is None:
                unmatched_groups += 1
                continue
            matched_files += len(pending)
            updates = process_pending_checks_for(patch, pending, self._log)
            self.metrics.total_updates += len(updates)

            for update in updates:
                self._log(f"* {patch.name}: {update}", "green bold")

        update_count = self.metrics.total_updates - updates_before
        summary = (
            "pending_checks_poll: "
            f"patches={len(filtered_patches)} pending_files={pending_files} "
            f"matched_files={matched_files} unmatched_groups={unmatched_groups} "
            f"reaped={reaped} updates={update_count}"
        )
        if update_count == 0 and reaped == 0:
            if not by_name:
                reason = "no_pending_check_files"
            elif matched_files == 0:
                reason = "no_pending_files_for_filtered_patches"
            else:
                reason = "no_completed_checks"
            summary += f" reason={reason}"
        self._log(summary, "green" if update_count or reaped else None)

    def run_comment_zombie_checks(self, filtered_patches: list[Patch]) -> None:
        """Check for zombie comment entries.

        Args:
            filtered_patches: List of patches to check.
        """
        updates_before = self.metrics.total_updates
        zombies_before = self.metrics.zombies_detected
        inspected_comments = _count_entries(filtered_patches, "comments")
        for patch in filtered_patches:
            updates = check_comment_zombies(patch, self.zombie_timeout_seconds)
            if updates:
                self.metrics.zombies_detected += len(updates)
                self.metrics.total_updates += len(updates)

                for update in updates:
                    self._log(f"* {patch.name}: {update}", "yellow")

        update_count = self.metrics.total_updates - updates_before
        zombies = self.metrics.zombies_detected - zombies_before
        summary = (
            "comment_zombie_checks: "
            f"patches={len(filtered_patches)} comments={inspected_comments} "
            f"zombies={zombies} updates={update_count}"
        )
        if update_count == 0:
            summary += " reason=" + _format_noop_reason(
                inspected_patches=len(filtered_patches),
                inspected_entries=inspected_comments,
                noun="comments",
            )
        self._log(summary, "yellow" if update_count else None)

    def run_suffix_transforms(
        self, all_patches: list[Patch], filtered_patches: list[Patch]
    ) -> datetime:
        """Run suffix transformation checks.

        Args:
            all_patches: All patches (for ready-to-mail check).
            filtered_patches: List of filtered patches to transform.

        Returns:
            Timestamp of when the hook cycle completed.
        """
        updates_before = self.metrics.total_updates
        for patch in filtered_patches:
            updates: list[str] = []

            # Transform old proposal suffixes (!: -> ~:)
            updates.extend(transform_old_proposal_suffixes(patch))

            # Strip error markers from old commit entry hooks
            updates.extend(strip_old_entry_error_markers(patch))

            # Acknowledge terminal status attention markers
            updates.extend(strip_terminal_status_markers(patch))

            self.metrics.total_updates += len(updates)

            for update in updates:
                self._log(f"* {patch.name}: {update}", "green bold")

        cycle_timestamp = datetime.now(get_timezone())
        update_count = self.metrics.total_updates - updates_before
        summary = (
            "suffix_transforms: "
            f"all_patches={len(all_patches)} "
            f"filtered_patches={len(filtered_patches)} updates={update_count}"
        )
        if update_count == 0:
            summary += " reason="
            summary += (
                "no_matching_patches"
                if not filtered_patches
                else "no_stale_suffix_markers"
            )
        self._log(summary, "green" if update_count else None)

        return cycle_timestamp

    def run_orphan_cleanup(self, all_patches: list[Patch]) -> None:
        """Clean up orphaned workspace claims for reverted Patches.

        Args:
            all_patches: All patches to check for orphans.
        """
        released = cleanup_orphaned_workspace_claims(all_patches, self._log)
        if released > 0:
            self.metrics.total_updates += released
        summary = f"orphan_cleanup: patches={len(all_patches)} released={released}"
        if released == 0:
            summary += " reason=no_orphaned_workspace_claims"
        self._log(summary, "green" if released else None)

    def run_stale_running_cleanup(self) -> None:
        """Clean up stale RUNNING entries for dead processes."""
        released = cleanup_stale_running_entries(self._log)
        if released > 0:
            self.metrics.stale_running_cleaned += released
            self.metrics.total_updates += released
        summary = f"stale_running_cleanup: released={released}"
        if released == 0:
            summary += " reason=no_dead_running_process_claims"
        self._log(summary, "green" if released else None)
