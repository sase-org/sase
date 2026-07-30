"""Per-subtab copy targets for Artifacts copy mode."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from sase.core.agent_identity_facade import present_agent_name
from sase.core.commit_footer_facade import parse_commit_footer

from ...widgets.artifacts.chats_list import chat_row_target
from ...widgets.artifacts.plans_list import plan_row_target
from ._base import ClipboardBase
from ._delivery import schedule_copy_delivery
from ._helpers import format_multi_copy_content


class ClipboardArtifactTargetsMixin(ClipboardBase):
    """Copy individual fields from visible or marked Artifacts entries."""

    def _copy_commit_target(self, target: str) -> None:
        pane = self._commits_pane()  # type: ignore[attr-defined]
        marked = self._visible_marked_targets(pane)
        if marked is not None:
            self._copy_marked_commit_targets(pane, marked, target)
            return
        if target == "sha":
            self.action_commits_copy_sha()  # type: ignore[attr-defined]
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
            value = _commit_plan_reference(pane._view_spec(entry).message)
            label = "linked plan reference"
            if value is None:
                self.notify(  # type: ignore[attr-defined]
                    "The selected commit has no linked plan reference",
                    severity="warning",
                )
                return
        self._schedule_artifacts_copy(value, copied_message=f"Copied {label}")

    def _copy_plan_target(self, target: str) -> None:
        pane = self._plans_pane()  # type: ignore[attr-defined]
        marked = self._visible_marked_targets(pane)
        if marked is not None:
            self._copy_marked_plan_targets(pane, marked, target)
            return
        row = pane.selected_row() if pane is not None else None
        if row is None:
            self.notify("No plan entry selected", severity="warning")  # type: ignore[attr-defined]
            return

        if row.proposal is not None:
            values = {
                "path": row.proposal.plan_path,
                "title": row.proposal.title,
                "body": row.proposal.body,
            }
        elif row.archive is not None:
            plan = row.archive.plan
            values = {
                "path": plan.path,
                "title": plan.title or plan.name,
                "body": plan.body,
            }
        else:
            preview = pane.selected_preview()
            issue = row.issue
            values = {
                "path": None if preview is None else preview.source_path,
                "title": None if issue is None else issue.title,
                "body": None if preview is None else preview.content,
            }

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
                lambda: _bug_prompt(pane, issue, project),
                copied_message=f"Copied issue #{issue.number} agent prompt",
                task_name="sase-bug-copy-prompt",
            )

    def _visible_marked_targets(
        self,
        pane: Any,
    ) -> tuple[tuple[str, ...], ...] | None:
        """Return marked targets in visible row order, or None when unmarked."""
        all_marks = getattr(self, "_artifacts_marked_targets", {})
        marks = all_marks.get(self.current_artifacts_subtab, set())
        if not marks:
            return None
        if pane is None:
            return ()
        targets = tuple(target for target in pane.entry_targets() if target in marks)
        if not targets:
            self.notify(  # type: ignore[attr-defined]
                f"No marked {self.current_artifacts_subtab} entries are visible",
                severity="warning",
            )
        return targets

    def _copy_marked_commit_targets(
        self,
        pane: Any,
        targets: tuple[tuple[str, ...], ...],
        target: str,
    ) -> None:
        if not targets:
            return
        result = getattr(pane, "result", None)
        entries = () if result is None else result.commits
        by_target: dict[tuple[str, ...], Any] = {
            ("commit", entry.repo, entry.commit.full_id): entry for entry in entries
        }
        selected = [by_target[item] for item in targets if item in by_target]
        labels = {
            "sha": "commit SHAs",
            "message": "commit messages",
            "repo_sha": "repository commit references",
            "plan": "linked plan references",
        }

        def value(entry: Any) -> str:
            if target == "sha":
                return entry.commit.full_id
            if target == "message":
                return pane._view_spec(entry).message
            if target == "repo_sha":
                return f"{entry.repo}@{entry.commit.full_id}"
            plan = _commit_plan_reference(pane._view_spec(entry).message)
            if plan is None:
                raise ValueError(
                    f"{entry.repo}@{entry.commit.short_id} has no linked plan reference"
                )
            return plan

        self._schedule_marked_copy(
            [
                (
                    f"{entry.repo}@{entry.commit.short_id}",
                    partial(value, entry),
                )
                for entry in selected
            ],
            copied_message=f"Copied {len(selected)} {labels[target]}",
        )

    def _copy_marked_plan_targets(
        self,
        pane: Any,
        targets: tuple[tuple[str, ...], ...],
        target: str,
    ) -> None:
        if not targets:
            return
        by_target: dict[tuple[str, ...], Any] = {
            plan_row_target(row): row for row in getattr(pane, "_rows", {}).values()
        }
        rows = [by_target[item] for item in targets if item in by_target]
        self._schedule_marked_copy(
            [
                (
                    row.row_id,
                    partial(_plan_copy_value, pane, row, target),
                )
                for row in rows
            ],
            copied_message=f"Copied {len(rows)} plan {_plural(target)}",
        )

    def _copy_marked_chat_targets(
        self,
        pane: Any,
        targets: tuple[tuple[str, ...], ...],
        target: str,
    ) -> None:
        if not targets:
            return
        by_target: dict[tuple[str, ...], Any] = {
            chat_row_target(row): row.entry
            for row in getattr(pane, "_rows", {}).values()
        }
        entries = [by_target[item] for item in targets if item in by_target]

        def value(entry: Any) -> str:
            if target == "path":
                return entry.absolute_path
            if target == "agent":
                agent = entry.agent_local_name or entry.agent
                if not agent:
                    raise ValueError(f"{entry.basename} has no agent name")
                return present_agent_name(agent)
            from ...widgets.artifacts.chats_detail import read_full_chat

            return read_full_chat(entry)

        labels = {
            "path": "chat paths",
            "agent": "chat agent names",
            "transcript": "chat transcripts",
        }
        self._schedule_marked_copy(
            [(entry.basename, partial(value, entry)) for entry in entries],
            copied_message=f"Copied {len(entries)} {labels[target]}",
            task_name="sase-chat-copy-marked",
        )

    def _copy_marked_bug_targets(
        self,
        pane: Any,
        targets: tuple[tuple[str, ...], ...],
        target: str,
    ) -> None:
        if not targets:
            return
        project = getattr(pane, "project_scope", None)
        if project is None:
            self.notify("Pick a project before copying marked bugs", severity="warning")  # type: ignore[attr-defined]
            return
        by_target = {pane._issue_target(issue): issue for issue in pane.issues}
        issues = [by_target[item] for item in targets if item in by_target]

        def value(issue: Any) -> str:
            if target == "number":
                return f"#{issue.number}"
            if target == "title":
                return issue.title
            if target == "url":
                from ..artifact_bugs import resolved_bug_url

                return resolved_bug_url(project, issue)
            return _bug_prompt(pane, issue, project)

        labels = {
            "number": "issue numbers",
            "url": "issue URLs",
            "title": "issue titles",
            "prompt": "issue agent prompts",
        }
        self._schedule_marked_copy(
            [(f"#{issue.number}", partial(value, issue)) for issue in issues],
            copied_message=f"Copied {len(issues)} {labels[target]}",
            task_name="sase-bug-copy-marked",
        )

    def _schedule_marked_copy(
        self,
        contents: list[tuple[str, str | Callable[[], str]]],
        *,
        copied_message: str,
        task_name: str = "sase-artifacts-copy-marked",
    ) -> None:
        """Resolve a marked set off-thread and format it consistently."""
        if not contents:
            self.notify("No marked entries are available to copy", severity="warning")  # type: ignore[attr-defined]
            return

        def resolve() -> str:
            return format_multi_copy_content(
                [
                    (name, content() if callable(content) else content)
                    for name, content in contents
                ]
            )

        self._schedule_artifacts_copy(
            resolve,
            copied_message=copied_message,
            task_name=task_name,
        )

    def _schedule_artifacts_copy(
        self,
        content: str | Callable[[], str],
        *,
        copied_message: str,
        task_name: str = "sase-artifacts-copy",
    ) -> None:
        """Resolve and copy content without blocking Textual's message pump."""
        schedule_copy_delivery(
            self,
            content,
            copied_label=copied_message.removeprefix("Copied "),
            task_name=task_name,
        )


def _commit_plan_reference(message: str) -> str | None:
    """Return the same terminal SASE_PLAN label used by the commit modal."""
    try:
        footer = parse_commit_footer(message)
    except Exception:
        return None
    tag = next(
        (tag for tag in reversed(footer.tags) if tag.raw_key == "SASE_PLAN"),
        None,
    )
    return None if tag is None else tag.label


def _bug_prompt(pane: Any, issue: Any, project: str) -> str:
    """Build the same project-anchored prompt used by the Bugs launch action."""
    from sase.workspace_provider import detect_workflow_type

    from ..artifact_bugs import bug_agent_prompt

    workflow_type = detect_workflow_type(pane.project_file)
    display_name = pane.snapshot.display_name or project
    return bug_agent_prompt(f"#{workflow_type}:{display_name} ", issue)


def _plan_copy_value(pane: Any, row: Any, target: str) -> str:
    if row.proposal is not None:
        values = {
            "path": row.proposal.plan_path,
            "title": row.proposal.title,
            "body": row.proposal.body,
        }
    elif row.archive is not None:
        plan = row.archive.plan
        values = {
            "path": plan.path,
            "title": plan.title or plan.name,
            "body": plan.body,
        }
    else:
        preview = pane.preview_for_row(row)
        issue = row.issue
        values = {
            "path": None if preview is None else preview.source_path,
            "title": None if issue is None else issue.title,
            "body": None if preview is None else preview.content,
        }
    value = values[target]
    if not value:
        raise ValueError(f"{row.row_id} has no {target}")
    return value


def _plural(value: str) -> str:
    return "bodies" if value == "body" else f"{value}s"
