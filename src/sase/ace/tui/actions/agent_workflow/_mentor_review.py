"""Mentor review, activity dashboard, and comment clearing for the ace TUI app."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from ._types import PromptContext

if TYPE_CHECKING:
    from ....changespec import ChangeSpec
    from ...activity_log import ActivityLog


class MentorReviewMixin:
    """Mixin providing mentor review, activity dashboard, and comment clearing."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int
    _activity_log: ActivityLog
    _inactive_seconds: int
    _prompt_context: PromptContext | None

    def _show_activity_dashboard(self) -> None:
        """Show the Activity Dashboard modal."""
        from ...modals import ActivityModal

        self.push_screen(ActivityModal(self._activity_log, self._inactive_seconds))  # type: ignore[attr-defined]

    def _open_mentor_review(self) -> None:
        """Open the Mentor Review popup for the latest commit's mentors."""
        if not self.changespecs:
            self.notify("No ChangeSpecs available", severity="warning")  # type: ignore[attr-defined]
            return

        changespec = self.changespecs[self.current_idx]
        if not changespec.mentors:
            self.notify("No mentors for this CL", severity="warning")  # type: ignore[attr-defined]
            return

        # Find the latest mentor entry (highest entry_id)
        latest_entry = max(changespec.mentors, key=lambda e: e.entry_id)

        # Check if any mentor has COMMENTED or FAILED status
        has_reviewable = False
        if latest_entry.status_lines:
            for sl in latest_entry.status_lines:
                if sl.status in ("COMMENTED", "FAILED", "RUNNING", "PASSED"):
                    has_reviewable = True
                    break

        if not has_reviewable:
            self.notify("No mentor results to review", severity="warning")  # type: ignore[attr-defined]
            return

        from ...modals import (
            MentorApplyResult,
            MentorReviewModal,
            build_mentor_review_data,
        )

        data = build_mentor_review_data(latest_entry, changespec.name)
        if data is None:
            self.notify("No mentor data available", severity="warning")  # type: ignore[attr-defined]
            return

        # Capture changespec info for the callback closure
        project_file = changespec.file_path

        def on_mentor_review_dismiss(result: MentorApplyResult | None) -> None:
            if result is None:
                return
            self._launch_mentor_apply_agent(
                result.accepted_comments,
                result.cl_name,
                project_file,
            )

        self.push_screen(MentorReviewModal(data), on_mentor_review_dismiss)  # type: ignore[attr-defined]

    def _launch_mentor_apply_agent(
        self,
        accepted_comments: list[dict[str, str | int]],
        cl_name: str,
        project_file: str,
    ) -> None:
        """Build and launch the apply agent for accepted mentor comments.

        Args:
            accepted_comments: The accepted mentor comment dicts.
            cl_name: The CL name.
            project_file: Path to the project ``.gp`` file.
        """
        import json
        from pathlib import Path

        from sase.sase_utils import generate_timestamp
        from sase.workspace_provider import detect_workflow_type
        from sase.xprompt.tags import XPromptTag, get_by_tag

        vcs_type = detect_workflow_type(project_file)

        # Render accepted comments into prompt text
        rendered_changes = "\n\n".join(
            f"### Change {i + 1}: {c['focus_name']} ({c['severity']})\n"
            f"**File**: `{c['file_path']}:{c['line_number']}`\n"
            f"{c['description']}"
            for i, c in enumerate(accepted_comments)
        )

        prompt = (
            f"#{vcs_type}:{cl_name}\n\n"
            "### Task\n\n"
            "Apply the following code review changes to the codebase. "
            "Make each change as described, run any relevant tests, "
            "and commit your changes.\n\n"
            f"{rendered_changes}"
        )

        # Append commit-tagged xprompt if one exists
        commit_wf = get_by_tag(XPromptTag.commit)
        if commit_wf is not None:
            prompt += f"\n\n#{commit_wf.name}"

        # Set up prompt context in home mode (VCS resolution happens
        # in _finish_agent_launch from the #vcs:cl_name prefix)
        timestamp = generate_timestamp()
        workflow_name = f"ace(run)-{timestamp}"
        self._prompt_context = PromptContext(
            project_name="home",
            cl_name=None,
            project_file=os.path.expanduser("~/.sase/projects/home/home.gp"),
            workspace_dir=str(Path.home()),
            workspace_num=0,
            workflow_name=workflow_name,
            timestamp=timestamp,
            history_sort_key=cl_name,
            display_name=cl_name,
            update_target="",
            is_home_mode=True,
        )

        # Save accepted comments as JSON artifact for traceability
        artifacts_dir = Path.home() / ".sase" / "mentors"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = (
            artifacts_dir / f"{cl_name.replace('/', '_')}-apply-{timestamp}.json"
        )
        artifact_path.write_text(
            json.dumps(accepted_comments, indent=2), encoding="utf-8"
        )

        self._finish_agent_launch(prompt)  # type: ignore[attr-defined]

    def _clear_changespec_comments(self) -> None:
        """Remove the COMMENTS field, kill running CRS agents, and delete proposals."""
        if not self.changespecs:
            self.notify("No ChangeSpecs available", severity="warning")  # type: ignore[attr-defined]
            return

        changespec = self.changespecs[self.current_idx]
        if not changespec.comments:
            self.notify("No comments to clear", severity="warning")  # type: ignore[attr-defined]
            return

        # Kill any running CRS agents
        import signal

        from sase.ace.changespec import extract_pid_from_agent_suffix

        killed_agents = 0
        for comment in changespec.comments:
            if (
                comment.suffix_type == "running_agent"
                and comment.suffix
                and comment.suffix.startswith("crs")
            ):
                pid = extract_pid_from_agent_suffix(comment.suffix)
                if pid is not None:
                    try:
                        os.killpg(pid, signal.SIGTERM)
                        killed_agents += 1
                    except (ProcessLookupError, PermissionError):
                        pass

        # Delete any CRS proposal commits associated with comments
        deleted_proposals = 0
        if changespec.commits:
            from sase.ace.change_actions import delete_proposal_entry

            crs_proposals = [
                c
                for c in changespec.commits
                if c.is_proposed and c.note.startswith("[crs")
            ]
            for entry in crs_proposals:
                if entry.diff:
                    try:
                        diff_path = os.path.expanduser(entry.diff)
                        if os.path.isfile(diff_path):
                            os.remove(diff_path)
                    except OSError:
                        pass
                if entry.proposal_letter:
                    if delete_proposal_entry(
                        changespec.file_path,
                        changespec.name,
                        entry.number,
                        entry.proposal_letter,
                    ):
                        deleted_proposals += 1

        from sase.ace.comments.operations import update_changespec_comments_field

        ok = update_changespec_comments_field(
            changespec.file_path, changespec.name, None
        )
        if ok:
            changespec.comments = None
            if changespec.commits and deleted_proposals:
                changespec.commits = [
                    c
                    for c in changespec.commits
                    if not (c.is_proposed and c.note.startswith("[crs"))
                ]
            msg = f"Cleared COMMENTS for {changespec.name}"
            details = []
            if killed_agents:
                details.append(f"killed {killed_agents} CRS agent(s)")
            if deleted_proposals:
                details.append(f"deleted {deleted_proposals} CRS proposal(s)")
            if details:
                msg += f" ({', '.join(details)})"
            self.notify(msg)  # type: ignore[attr-defined]
        else:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to clear COMMENTS for {changespec.name}", severity="error"
            )
