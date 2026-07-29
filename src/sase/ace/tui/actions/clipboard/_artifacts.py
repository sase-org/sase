"""Copy targets for the non-PR Artifacts sub-tabs."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from sase.core.agent_identity_facade import present_agent_name
from sase.core.commit_footer_facade import parse_commit_footer

from ...keymaps import key_display_name
from ...tab_order import ARTIFACTS_TAB
from ...util.pump_tasks import spawn_pump_free_task
from ._base import ClipboardBase
from ._helpers import copy_to_system_clipboard


class ClipboardArtifactsMixin(ClipboardBase):
    """Dispatch copy-mode keys using the visible Artifacts entry."""

    def _non_pr_artifacts_copy_active(self) -> bool:
        return self.current_tab == ARTIFACTS_TAB and self.current_artifacts_subtab in {
            "commits",
            "plans",
            "chats",
            "bugs",
        }

    def _handle_artifacts_copy_key(self, key: str) -> bool:
        subtab = self.current_artifacts_subtab
        group_name = f"artifacts_{subtab}"
        subtab_keys = self._keymap_registry.copy_mode.keys.get(group_name, {})
        assert isinstance(subtab_keys, dict)

        if key == subtab_keys["snapshot"]:
            self._copy_snapshot()  # type: ignore[attr-defined]
            return True

        handlers: dict[str, Callable[[], None]]
        if subtab == "commits":
            handlers = {
                str(subtab_keys["sha"]): lambda: self._copy_commit_target("sha"),
                str(subtab_keys["message"]): lambda: self._copy_commit_target(
                    "message"
                ),
                str(subtab_keys["repo_sha"]): lambda: self._copy_commit_target(
                    "repo_sha"
                ),
                str(subtab_keys["plan"]): lambda: self._copy_commit_target("plan"),
            }
        elif subtab == "plans":
            handlers = {
                str(subtab_keys["path"]): lambda: self._copy_plan_target("path"),
                str(subtab_keys["title"]): lambda: self._copy_plan_target("title"),
                str(subtab_keys["body"]): lambda: self._copy_plan_target("body"),
            }
        elif subtab == "chats":
            handlers = {
                str(subtab_keys["path"]): lambda: self._copy_chat_target("path"),
                str(subtab_keys["agent"]): lambda: self._copy_chat_target("agent"),
                str(subtab_keys["transcript"]): lambda: self._copy_chat_target(
                    "transcript"
                ),
            }
        else:
            handlers = {
                str(subtab_keys["number"]): lambda: self._copy_bug_target("number"),
                str(subtab_keys["url"]): lambda: self._copy_bug_target("url"),
                str(subtab_keys["title"]): lambda: self._copy_bug_target("title"),
                str(subtab_keys["prompt"]): lambda: self._copy_bug_target("prompt"),
            }

        handler = handlers.get(key)
        if handler is None:
            key_list = ", ".join(
                key_display_name(value)
                for value in subtab_keys.values()
                if isinstance(value, str)
            )
            self.notify(  # type: ignore[attr-defined]
                f"Unknown copy key ({subtab.title()}: {key_list})",
                severity="warning",
            )
            return False
        handler()
        return True

    def _copy_commit_target(self, target: str) -> None:
        if target == "sha":
            self.action_commits_copy_sha()  # type: ignore[attr-defined]
            return
        pane = self._commits_pane()  # type: ignore[attr-defined]
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

    def _schedule_artifacts_copy(
        self,
        content: str | Callable[[], str],
        *,
        copied_message: str,
        task_name: str = "sase-artifacts-copy",
    ) -> None:
        """Resolve and copy content without blocking Textual's message pump."""

        async def copy_content() -> None:
            try:
                value = (
                    await asyncio.to_thread(content) if callable(content) else content
                )
                copied = await asyncio.to_thread(copy_to_system_clipboard, value)
            except Exception as exc:
                self.notify(  # type: ignore[attr-defined]
                    f"Unable to copy: {exc}",
                    severity="error",
                )
                return
            self.notify(  # type: ignore[attr-defined]
                copied_message
                if copied
                else "Copy failed — clipboard tool not available",
                severity="information" if copied else "error",
            )

        spawn_pump_free_task(
            self,
            copy_content(),
            name=task_name,
            registry_attr="_pump_free_async_tasks",
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


__all__ = ["ClipboardArtifactsMixin"]
