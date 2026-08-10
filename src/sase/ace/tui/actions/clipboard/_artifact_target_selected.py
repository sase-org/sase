"""Selected-entry actions for artifact copy targets."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from sase.artifact_refs import design_reference_for_plan_row
from sase.core.agent_identity_facade import present_agent_name

from ...models.artifact_file_clipboard import (
    ArtifactFilePathCopy,
    artifact_file_clipboard_path,
    artifact_file_source_clipboard_path,
)
from ._artifact_target_marked import ClipboardArtifactMarkedTargetsMixin
from ._artifact_target_values import (
    artifact_file_contents,
    bead_copy_value,
    bug_prompt,
    commit_plan_reference,
)


class ClipboardArtifactSelectedTargetsMixin(ClipboardArtifactMarkedTargetsMixin):
    """Copy individual fields from the selected artifact entry."""

    def _copy_bead_target(self, target: str) -> None:
        pane = self._beads_pane()  # type: ignore[attr-defined]
        marked = self._visible_marked_targets(pane)
        if marked is not None:
            self._copy_marked_bead_targets(pane, marked, target)
            return
        row = pane.selected_row() if pane is not None else None
        if row is None:
            self.notify("No bead selected", severity="warning")  # type: ignore[attr-defined]
            return
        self._schedule_artifacts_copy(
            lambda: bead_copy_value(pane, row, target),
            copied_message=f"Copied bead {target}",
            content_shaped=target == "body",
        )

    def _copy_commit_target(self, target: str) -> None:
        pane = self._commits_pane()  # type: ignore[attr-defined]
        marked = self._visible_marked_targets(pane)
        if marked is not None:
            self._copy_marked_commit_targets(pane, marked, target)
            return
        if target == "sha":
            self.action_stitches_copy_sha()  # type: ignore[attr-defined]
            return
        entry = pane._selected_entry() if pane is not None else None
        if entry is None:
            self.notify("No commit selected", severity="warning")  # type: ignore[attr-defined]
            return
        if target == "message":
            value = pane._view_spec(entry).message
            label = "commit message"
        elif target == "repo_sha":
            value = f"{entry.repo}@{entry.commit.full_id}"
            label = "repository commit reference"
        else:
            value = commit_plan_reference(pane._view_spec(entry).message)
            label = "linked plan reference"
            if value is None:
                self.notify(  # type: ignore[attr-defined]
                    "The selected commit has no linked plan reference",
                    severity="warning",
                )
                return
        self._schedule_artifacts_copy(
            value,
            copied_message=f"Copied {label}",
            content_shaped=target == "message",
        )

    def _copy_plan_target(self, target: str) -> None:
        pane = self._plans_pane()  # type: ignore[attr-defined]
        marked = self._visible_marked_targets(pane)
        if marked is not None:
            self._copy_marked_plan_targets(pane, marked, target)
            return
        row = pane.selected_row() if pane is not None else None
        if row is None:
            self.notify(  # type: ignore[attr-defined]
                "No plan entry selected",
                severity="warning",
            )
            return

        if target in {"bead_id", "design"}:
            if target == "bead_id":
                value = None if row.bead_link is None else row.bead_link.bead_id
                label = "owning bead id"
            else:
                value = design_reference_for_plan_row(row)
                label = "owning bead design reference"
            if value is None:
                self.notify(  # type: ignore[attr-defined]
                    f"The selected plan has no {label}",
                    severity="warning",
                )
                return
            self._schedule_artifacts_copy(
                value,
                copied_message=f"Copied {label}",
            )
            return

        if row.proposal is not None:
            values = {
                "path": row.proposal.plan_path,
                "title": row.proposal.title,
                "body": row.proposal.body,
            }
        elif row.active is not None:
            document = row.active.document
            values = {
                "path": document.path,
                "title": document.frontmatter.get("title") or Path(document.path).stem,
                "body": document.body,
            }
        elif row.archive is not None:
            plan = row.archive.plan
            values = {
                "path": plan.path,
                "title": plan.title or plan.name,
                "body": plan.body,
            }
        else:  # pragma: no cover - PlanRow always has a document payload.
            values = {"path": None, "title": None, "body": None}

        value = values[target]
        if not value:
            self.notify(  # type: ignore[attr-defined]
                f"The selected plan entry has no {target}",
                severity="warning",
            )
            return
        self._schedule_artifacts_copy(
            value,
            copied_message=f"Copied plan {target}",
            content_shaped=target == "body",
        )

    def _copy_chat_target(self, target: str) -> None:
        pane = self._chats_pane()  # type: ignore[attr-defined]
        marked = self._visible_marked_targets(pane)
        if marked is not None:
            self._copy_marked_chat_targets(pane, marked, target)
            return
        entry = pane.selected_entry if pane is not None else None
        if entry is None:
            self.notify("No chat selected", severity="warning")  # type: ignore[attr-defined]
            return

        if target == "path":
            self.action_chats_copy_path()  # type: ignore[attr-defined]
            return
        if target == "agent":
            agent = entry.agent_local_name or entry.agent
            if not agent:
                self.notify(  # type: ignore[attr-defined]
                    "The selected chat has no agent name",
                    severity="warning",
                )
                return
            presented = present_agent_name(agent)
            self._schedule_artifacts_copy(
                presented,
                copied_message="Copied chat agent name",
            )
            return

        from ...widgets.artifacts.chats_detail import read_full_chat

        self._schedule_artifacts_copy(
            lambda: read_full_chat(entry),
            copied_message="Copied chat transcript",
            task_name="sase-chat-copy-transcript",
            content_shaped=True,
        )

    def _copy_file_target(self, target: str) -> None:
        pane = self._files_pane()  # type: ignore[attr-defined]
        marked = self._visible_marked_targets(pane)
        if marked is not None:
            self._copy_marked_file_targets(pane, marked, target)
            return
        entry = pane.selected_entry if pane is not None else None
        if entry is None:
            self.notify(  # type: ignore[attr-defined]
                "No artifact file selected",
                severity="warning",
            )
            return

        if target == "contents":
            view_mode = pane.selected_view_mode
            if view_mode not in {"markdown", "text"}:
                self.notify(  # type: ignore[attr-defined]
                    f"Cannot copy {view_mode or entry.kind} contents; "
                    "that artifact file is binary",
                    severity="warning",
                )
                return
            self._schedule_artifacts_copy(
                partial(artifact_file_contents, entry),
                copied_message=f"Copied contents of {entry.label}",
                task_name="sase-file-copy-contents",
                content_shaped=True,
            )
            return

        if target == "label":
            self._schedule_artifacts_copy(
                entry.label,
                copied_message="Copied artifact file label",
            )
            return

        copy_path: ArtifactFilePathCopy | None = None

        def value() -> str:
            nonlocal copy_path
            copy_path = (
                artifact_file_clipboard_path(entry)
                if target == "path"
                else artifact_file_source_clipboard_path(entry)
            )
            if copy_path is None:
                raise ValueError(
                    f"{entry.label} has no "
                    f"{'stored' if target == 'path' else 'source'} path"
                )
            return copy_path.text

        def copied_message() -> str:
            assert copy_path is not None
            suffix = " (no longer exists)" if copy_path.missing else ""
            return f"Copied {copy_path.label}{suffix}: {copy_path.text}"

        self._schedule_artifacts_copy(
            value,
            copied_message=copied_message,
            task_name=f"sase-file-copy-{target}",
        )

    def _copy_bug_target(self, target: str) -> None:
        pane = self._bugs_pane()  # type: ignore[attr-defined]
        marked = self._visible_marked_targets(pane)
        if marked is not None:
            self._copy_marked_bug_targets(pane, marked, target)
            return
        context = self._selected_bug_copy_context()  # type: ignore[attr-defined]
        if context is None:
            self.notify("No bug selected", severity="warning")  # type: ignore[attr-defined]
            return
        pane, issue, project = context

        if target == "number":
            self._schedule_artifacts_copy(
                f"#{issue.number}",
                copied_message=f"Copied issue #{issue.number}",
            )
        elif target == "title":
            self._schedule_artifacts_copy(
                issue.title,
                copied_message="Copied issue title",
            )
        elif target == "url":
            from ..artifact_bugs import resolved_bug_url

            self._schedule_artifacts_copy(
                lambda: resolved_bug_url(project, issue),
                copied_message=f"Copied issue #{issue.number} URL",
                task_name="sase-bug-copy-url",
            )
        else:
            self._schedule_artifacts_copy(
                lambda: bug_prompt(pane, issue, project),
                copied_message=f"Copied issue #{issue.number} agent prompt",
                task_name="sase-bug-copy-prompt",
                content_shaped=True,
            )


__all__ = ["ClipboardArtifactSelectedTargetsMixin"]
