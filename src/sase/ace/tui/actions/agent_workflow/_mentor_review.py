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
            MentorKillResult,
            MentorReviewModal,
            build_mentor_review_data,
        )

        # Capture changespec info for the callback closure
        project_file = changespec.file_path
        project_basename = changespec.project_basename

        # Get VCS provider from the primary workspace (read-only, no claim needed)
        from sase.running_field import get_workspace_directory_for_num
        from sase.vcs_provider import get_vcs_provider

        provider = None
        revision = ""
        ws_dir = ""
        try:
            ws_dir, _ = get_workspace_directory_for_num(1, project_basename)
            provider = get_vcs_provider(ws_dir)
            revision = provider.resolve_revision(
                changespec.name, project_basename, ws_dir
            )
        except Exception:
            pass

        data = build_mentor_review_data(
            latest_entry,
            changespec.name,
            vcs_provider=provider,
            revision=revision,
            vcs_cwd=ws_dir,
        )
        if data is None:
            self.notify("No mentor data available", severity="warning")  # type: ignore[attr-defined]
            return

        def on_mentor_review_dismiss(
            result: MentorApplyResult | MentorKillResult | None,
        ) -> None:
            if result is None:
                return
            if isinstance(result, MentorKillResult):
                self._kill_mentor_from_review(result, project_file)
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

        from sase.main.query_handler import execute_standalone_steps
        from sase.sase_utils import generate_timestamp
        from sase.workspace_provider import detect_workflow_type
        from sase.xprompt.tags import XPromptTag, get_by_tag, get_by_tag_strict
        from sase.xprompt.workflow_executor_utils import render_template

        vcs_type = detect_workflow_type(project_file)

        # Resolve the make_mentor_changes xprompt via tag
        changes_wf = get_by_tag_strict(XPromptTag.make_mentor_changes)
        if changes_wf is None:
            raise RuntimeError(
                "No xprompt with tag 'make_mentor_changes' found. "
                "Ensure src/sase/xprompts/make_mentor_changes.yml is installed."
            )

        # Build input context
        context: dict[str, str] = {
            "accepted_comments_json": json.dumps(accepted_comments),
            "cl_name": cl_name,
            "vcs_type": vcs_type,
        }

        # Execute pre-prompt steps (render_changes python step)
        pre_steps = changes_wf.get_pre_prompt_steps()
        if pre_steps:
            context = execute_standalone_steps(
                pre_steps, context, "make_mentor_changes", None
            )

        # Render prompt_part with context
        prompt_part_content = changes_wf.get_prompt_part_content()
        if not prompt_part_content:
            raise RuntimeError(
                "The #make_mentor_changes xprompt has no prompt_part step. "
                "Check src/sase/xprompts/make_mentor_changes.yml."
            )
        prompt = render_template(prompt_part_content, context)

        # Append commit-tagged xprompt if one exists
        commit_wf = get_by_tag(XPromptTag.commit)
        if commit_wf is not None:
            prompt += f"\n\n#{commit_wf.name}(who=mentor)"

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

    def _kill_mentor_from_review(
        self,
        kill_result: object,
        project_file: str,
    ) -> None:
        """Kill a running mentor process triggered from the review modal.

        Args:
            kill_result: A ``MentorKillResult`` with identifying fields.
            project_file: Path to the project ``.gp`` file.
        """
        import os
        import signal

        from sase.ace.changespec import (
            extract_pid_from_agent_suffix,
            parse_project_file,
        )
        from sase.ace.hooks.processes import (
            extract_mentor_workflow_from_suffix,
            mark_mentor_agents_as_killed,
        )
        from sase.ace.mentors import update_changespec_mentors_field

        entry_id: str = kill_result.entry_id  # type: ignore[attr-defined]
        mentor_name: str = kill_result.mentor_name  # type: ignore[attr-defined]
        profile_name: str = kill_result.profile_name  # type: ignore[attr-defined]
        cl_name: str = kill_result.cl_name  # type: ignore[attr-defined]

        # Re-read fresh state from disk for concurrency safety
        changespecs = parse_project_file(project_file)
        target_cs = None
        for cs in changespecs:
            if cs.name == cl_name:
                target_cs = cs
                break

        if target_cs is None or not target_cs.mentors:
            self.notify("ChangeSpec not found", severity="error")  # type: ignore[attr-defined]
            return

        # Find and kill the matching running mentor
        killed_agents = []
        for entry in target_cs.mentors:
            if entry.entry_id != entry_id or not entry.status_lines:
                continue
            for sl in entry.status_lines:
                if (
                    sl.suffix_type != "running_agent"
                    or not sl.suffix
                    or sl.profile_name != profile_name
                    or sl.mentor_name != mentor_name
                ):
                    continue

                pid = extract_pid_from_agent_suffix(sl.suffix)
                if pid is None:
                    continue

                try:
                    os.killpg(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass

                killed_agents.append((entry, sl, pid))

        if not killed_agents:
            self.notify(  # type: ignore[attr-defined]
                f"Mentor {mentor_name} is no longer running",
                severity="warning",
            )
            self._reload_and_reposition()  # type: ignore[attr-defined]
            return

        # Mark killed and persist to project file
        updated_mentors = mark_mentor_agents_as_killed(target_cs.mentors, killed_agents)
        update_changespec_mentors_field(project_file, cl_name, updated_mentors)

        # Release workspaces claimed by the killed mentor
        from sase.running_field import get_claimed_workspaces, release_workspace

        for _, status_line, _ in killed_agents:
            if not status_line.suffix:
                continue
            workflow = extract_mentor_workflow_from_suffix(status_line.suffix)
            if not workflow:
                continue
            for claim in get_claimed_workspaces(project_file):
                if claim.workflow == workflow and claim.cl_name == cl_name:
                    release_workspace(
                        project_file, claim.workspace_num, workflow, cl_name
                    )
                    break

        self.notify(f"Killed mentor: {mentor_name}")  # type: ignore[attr-defined]
        self._reload_and_reposition()  # type: ignore[attr-defined]

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
