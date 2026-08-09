"""Hook job runner for short-interval hook cycle jobs.

This module handles the 1-second interval hook cycle jobs that check
completions, start hooks/mentors/workflows, and perform cleanup tasks.
"""

from collections.abc import Callable
from datetime import datetime

from sase.ace.patch import ChangeSpec
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


def _count_entries(changespecs: list[ChangeSpec], attr: str) -> int:
    return sum(len(getattr(changespec, attr) or []) for changespec in changespecs)


def _format_noop_reason(
    *, inspected_changespecs: int, inspected_entries: int, noun: str
) -> str:
    if inspected_changespecs == 0:
        return "no_matching_changespecs"
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

    def run_hook_checks(self, filtered_changespecs: list[ChangeSpec]) -> None:
        """Run hook completion and startup checks.

        Args:
            filtered_changespecs: List of changespecs to check.
        """
        self._hooks_started_this_tick = 0
        self._agents_started_this_tick = 0
        updates_before = self.metrics.total_updates
        hooks_started_before = self.metrics.hooks_started
        inspected_hooks = _count_entries(filtered_changespecs, "hooks")

        for changespec in filtered_changespecs:
            if not changespec.hooks:
                continue

            hook_updates, hooks_started = check_hooks(
                changespec,
                self._log,
                self.zombie_timeout_seconds,
                self.max_hook_runners,
                self._hooks_started_this_tick,
            )

            self._hooks_started_this_tick += hooks_started
            self.metrics.hooks_started += hooks_started
            self.metrics.total_updates += len(hook_updates)

            for update in hook_updates:
                self._log(f"* {changespec.name}: {update}", "green bold")

        updates = self.metrics.total_updates - updates_before
        started = self.metrics.hooks_started - hooks_started_before
        summary = (
            "hook_checks: "
            f"changespecs={len(filtered_changespecs)} hooks={inspected_hooks} "
            f"updates={updates} started={started}"
        )
        if updates == 0 and started == 0:
            summary += " reason=" + _format_noop_reason(
                inspected_changespecs=len(filtered_changespecs),
                inspected_entries=inspected_hooks,
                noun="hooks",
            )
        self._log(summary, "green" if updates or started else None)

    def run_mentor_checks(self, filtered_changespecs: list[ChangeSpec]) -> None:
        """Run mentor completion and startup checks.

        Args:
            filtered_changespecs: List of changespecs to check.
        """
        updates_before = self.metrics.total_updates
        mentors_started_before = self.metrics.mentors_started
        inspected_mentors = _count_entries(filtered_changespecs, "mentors")
        all_profiles = get_all_mentor_profiles()
        for changespec in filtered_changespecs:
            mentor_updates, mentors_started = check_mentors(
                changespec,
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
                self._log(f"* {changespec.name}: {update}", "green bold")

        updates = self.metrics.total_updates - updates_before
        started = self.metrics.mentors_started - mentors_started_before
        summary = (
            "mentor_checks: "
            f"changespecs={len(filtered_changespecs)} mentors={inspected_mentors} "
            f"profiles={len(all_profiles)} updates={updates} started={started}"
        )
        if updates == 0 and started == 0:
            summary += " reason=" + _format_noop_reason(
                inspected_changespecs=len(filtered_changespecs),
                inspected_entries=inspected_mentors,
                noun="mentors",
            )
        self._log(summary, "green" if updates or started else None)

    def run_workflow_checks(self, filtered_changespecs: list[ChangeSpec]) -> None:
        """Run CRS/fix-hook workflow checks.

        Args:
            filtered_changespecs: List of changespecs to check.
        """
        updates_before = self.metrics.total_updates
        workflows_started_before = self.metrics.workflows_started
        for changespec in filtered_changespecs:
            # Check completion of running workflows
            completion_updates = check_and_complete_workflows(changespec, self._log)
            self.metrics.total_updates += len(completion_updates)

            for update in completion_updates:
                self._log(f"* {changespec.name}: {update}", "green bold")

            # Start stale workflows
            start_updates, started, _ = start_stale_workflows(
                changespec,
                self._log,
                self.max_agent_runners,
                self._agents_started_this_tick,
            )

            self._agents_started_this_tick += started
            self.metrics.workflows_started += started
            self.metrics.total_updates += len(start_updates)

            for update in start_updates:
                self._log(f"* {changespec.name}: {update}", "green bold")

        updates = self.metrics.total_updates - updates_before
        started = self.metrics.workflows_started - workflows_started_before
        summary = (
            "workflow_checks: "
            f"changespecs={len(filtered_changespecs)} updates={updates} "
            f"started={started}"
        )
        if updates == 0 and started == 0:
            summary += " reason="
            summary += (
                "no_matching_changespecs"
                if not filtered_changespecs
                else "no_workflow_updates_or_launches"
            )
        self._log(summary, "green" if updates or started else None)

    def run_pending_checks_poll(self, filtered_changespecs: list[ChangeSpec]) -> None:
        """Poll for completed background checks.

        Walks ~/.sase/checks/ once per tick (O(M) in file count), dispatches
        per-ChangeSpec work from the single scan, and reaps orphaned output
        files left behind by killed or crashed background checks.

        Args:
            filtered_changespecs: List of changespecs to check.
        """
        updates_before = self.metrics.total_updates
        reaped = reap_orphan_check_files(self._log)
        by_name = scan_all_pending_checks()
        pending_files = sum(len(pending) for pending in by_name.values())
        matched_files = 0
        unmatched_groups = 0

        # Filenames encode ChangeSpec names via make_safe_filename(), which is
        # lossy (e.g. "foo-bar" and "foo_bar" both map to "foo_bar").  Any
        # collisions here inherit a pre-existing ambiguity in the filename
        # format and are not resolved in this poll.
        safe_to_cs = {make_safe_filename(cs.name): cs for cs in filtered_changespecs}
        for safe_name, pending in by_name.items():
            changespec = safe_to_cs.get(safe_name)
            if changespec is None:
                unmatched_groups += 1
                continue
            matched_files += len(pending)
            updates = process_pending_checks_for(changespec, pending, self._log)
            self.metrics.total_updates += len(updates)

            for update in updates:
                self._log(f"* {changespec.name}: {update}", "green bold")

        update_count = self.metrics.total_updates - updates_before
        summary = (
            "pending_checks_poll: "
            f"changespecs={len(filtered_changespecs)} pending_files={pending_files} "
            f"matched_files={matched_files} unmatched_groups={unmatched_groups} "
            f"reaped={reaped} updates={update_count}"
        )
        if update_count == 0 and reaped == 0:
            if not by_name:
                reason = "no_pending_check_files"
            elif matched_files == 0:
                reason = "no_pending_files_for_filtered_changespecs"
            else:
                reason = "no_completed_checks"
            summary += f" reason={reason}"
        self._log(summary, "green" if update_count or reaped else None)

    def run_comment_zombie_checks(self, filtered_changespecs: list[ChangeSpec]) -> None:
        """Check for zombie comment entries.

        Args:
            filtered_changespecs: List of changespecs to check.
        """
        updates_before = self.metrics.total_updates
        zombies_before = self.metrics.zombies_detected
        inspected_comments = _count_entries(filtered_changespecs, "comments")
        for changespec in filtered_changespecs:
            updates = check_comment_zombies(changespec, self.zombie_timeout_seconds)
            if updates:
                self.metrics.zombies_detected += len(updates)
                self.metrics.total_updates += len(updates)

                for update in updates:
                    self._log(f"* {changespec.name}: {update}", "yellow")

        update_count = self.metrics.total_updates - updates_before
        zombies = self.metrics.zombies_detected - zombies_before
        summary = (
            "comment_zombie_checks: "
            f"changespecs={len(filtered_changespecs)} comments={inspected_comments} "
            f"zombies={zombies} updates={update_count}"
        )
        if update_count == 0:
            summary += " reason=" + _format_noop_reason(
                inspected_changespecs=len(filtered_changespecs),
                inspected_entries=inspected_comments,
                noun="comments",
            )
        self._log(summary, "yellow" if update_count else None)

    def run_suffix_transforms(
        self, all_changespecs: list[ChangeSpec], filtered_changespecs: list[ChangeSpec]
    ) -> datetime:
        """Run suffix transformation checks.

        Args:
            all_changespecs: All changespecs (for ready-to-mail check).
            filtered_changespecs: List of filtered changespecs to transform.

        Returns:
            Timestamp of when the hook cycle completed.
        """
        updates_before = self.metrics.total_updates
        for changespec in filtered_changespecs:
            updates: list[str] = []

            # Transform old proposal suffixes (!: -> ~:)
            updates.extend(transform_old_proposal_suffixes(changespec))

            # Strip error markers from old commit entry hooks
            updates.extend(strip_old_entry_error_markers(changespec))

            # Acknowledge terminal status attention markers
            updates.extend(strip_terminal_status_markers(changespec))

            self.metrics.total_updates += len(updates)

            for update in updates:
                self._log(f"* {changespec.name}: {update}", "green bold")

        cycle_timestamp = datetime.now(get_timezone())
        update_count = self.metrics.total_updates - updates_before
        summary = (
            "suffix_transforms: "
            f"all_changespecs={len(all_changespecs)} "
            f"filtered_changespecs={len(filtered_changespecs)} updates={update_count}"
        )
        if update_count == 0:
            summary += " reason="
            summary += (
                "no_matching_changespecs"
                if not filtered_changespecs
                else "no_stale_suffix_markers"
            )
        self._log(summary, "green" if update_count else None)

        return cycle_timestamp

    def run_orphan_cleanup(self, all_changespecs: list[ChangeSpec]) -> None:
        """Clean up orphaned workspace claims for reverted ChangeSpecs.

        Args:
            all_changespecs: All changespecs to check for orphans.
        """
        released = cleanup_orphaned_workspace_claims(all_changespecs, self._log)
        if released > 0:
            self.metrics.total_updates += released
        summary = (
            f"orphan_cleanup: changespecs={len(all_changespecs)} released={released}"
        )
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
