"""Copy targets for the non-PR Artifacts sub-tabs."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from sase.artifact_refs import artifact_ref_context, reference_for_entry_target
from sase.core.agent_identity_facade import present_agent_name
from sase.core.commit_footer_facade import parse_commit_footer

from ...keymaps import key_display_name
from ...tab_order import ARTIFACTS_TAB
from ...util.pump_tasks import spawn_pump_free_task
from ...widgets.artifacts.chats_list import chat_row_target
from ...widgets.artifacts.plans_list import plan_row_target
from ._base import ClipboardBase
from ._delivery import deliver_copy, schedule_copy_delivery
from ._helpers import format_multi_copy_content


@dataclass(frozen=True, slots=True)
class _ArtifactReferenceItem:
    label: str
    target: tuple[str, ...]
    row: object | None
    project: str | None
    workspace_dir: str


@dataclass(frozen=True, slots=True)
class _ArtifactReferenceSelection:
    subtab: str
    items: tuple[_ArtifactReferenceItem, ...]
    marked: bool
    prompt_project: str | None
    prompt_display_name: str | None
    prompt_project_file: str | None


class ClipboardArtifactsMixin(ClipboardBase):
    """Dispatch copy-mode keys using the visible Artifacts entry."""

    def _non_pr_artifacts_copy_active(self) -> bool:
        return self.current_tab == ARTIFACTS_TAB and self.current_artifacts_subtab in {
            "commits",
            "plans",
            "chats",
            "bugs",
            "files",
        }

    def _handle_artifacts_copy_key(self, key: str) -> bool:
        subtab = self.current_artifacts_subtab
        group_name = f"artifacts_{subtab}"
        subtab_keys = self._keymap_registry.copy_mode.keys.get(group_name, {})
        assert isinstance(subtab_keys, dict)

        if key == subtab_keys["snapshot"]:
            self._copy_snapshot()  # type: ignore[attr-defined]
            return True
        if key == subtab_keys["reference"]:
            self._run_artifact_reference_action(handoff=False)
            return True
        if key == subtab_keys["handoff"]:
            self._run_artifact_reference_action(handoff=True)
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
        elif subtab == "files":
            handlers = {}
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

    def _run_artifact_reference_action(self, *, handoff: bool) -> None:
        selection = self._capture_artifact_reference_selection()
        if selection is None:
            return

        async def act() -> None:
            try:
                references = await asyncio.to_thread(
                    _resolve_artifact_references,
                    selection,
                )
            except Exception as exc:
                self.notify(  # type: ignore[attr-defined]
                    str(exc),
                    severity="warning",
                )
                return

            if handoff:
                project = selection.prompt_project
                display_name = selection.prompt_display_name
                project_file = selection.prompt_project_file
                if project is None or display_name is None:
                    self.notify(  # type: ignore[attr-defined]
                        "Pick one project before handing artifact references to an agent",
                        severity="warning",
                    )
                    return
                if not project_file:
                    self.notify(  # type: ignore[attr-defined]
                        f"{display_name} has no launchable ProjectSpec",
                        severity="warning",
                    )
                    return
                try:
                    from sase.workspace_provider import detect_workflow_type

                    workflow_type = await asyncio.to_thread(
                        detect_workflow_type,
                        project_file,
                    )
                except Exception as exc:
                    self.notify(  # type: ignore[attr-defined]
                        f"Cannot start an agent for {display_name}: {exc}",
                        severity="error",
                    )
                    return
                prompt = f"#{workflow_type}:{display_name} {' '.join(references)} "
                self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                    initial_text=prompt,
                    display_name=f"{display_name} artifact reference",
                    history_sort_key=project,
                )
                return

            content = (
                references[0]
                if not selection.marked
                else format_multi_copy_content(
                    [
                        (item.label, reference)
                        for item, reference in zip(
                            selection.items,
                            references,
                            strict=True,
                        )
                    ]
                )
            )
            count = len(references)
            await deliver_copy(
                self,
                content,
                copied_label=(
                    "artifact reference"
                    if count == 1
                    else f"{count} artifact references"
                ),
            )

        spawn_pump_free_task(
            self,
            act(),
            name=(
                "sase-artifact-reference-handoff"
                if handoff
                else "sase-artifact-reference-copy"
            ),
            registry_attr="_pump_free_async_tasks",
        )

    def _capture_artifact_reference_selection(
        self,
    ) -> _ArtifactReferenceSelection | None:
        subtab = self.current_artifacts_subtab
        pane = {
            "commits": self._commits_pane,  # type: ignore[attr-defined]
            "plans": self._plans_pane,  # type: ignore[attr-defined]
            "chats": self._chats_pane,  # type: ignore[attr-defined]
            "bugs": self._bugs_pane,  # type: ignore[attr-defined]
            "files": self._files_pane,  # type: ignore[attr-defined]
        }[subtab]()
        if pane is None:
            self.notify(f"No {subtab} entry selected", severity="warning")  # type: ignore[attr-defined]
            return None

        marked_targets = self._visible_marked_targets(pane)
        marked = marked_targets is not None
        if marked:
            targets = marked_targets
        else:
            target = pane.selected_entry_target()
            targets = () if target is None else (target,)
        if not targets:
            if not marked:
                self.notify(f"No {subtab} entry selected", severity="warning")  # type: ignore[attr-defined]
            return None

        items = _reference_items_for_targets(subtab, pane, targets)
        if not items:
            self.notify(  # type: ignore[attr-defined]
                f"No visible {subtab} entries are available",
                severity="warning",
            )
            return None

        projects = tuple(
            dict.fromkeys(item.project for item in items if item.project is not None)
        )
        prompt_project = projects[0] if len(projects) == 1 else None
        display_name, project_file = self._artifact_prompt_project_metadata(
            pane,
            prompt_project,
        )
        return _ArtifactReferenceSelection(
            subtab=subtab,
            items=items,
            marked=marked,
            prompt_project=prompt_project,
            prompt_display_name=display_name,
            prompt_project_file=project_file,
        )

    def _artifact_prompt_project_metadata(
        self,
        pane: Any,
        project: str | None,
    ) -> tuple[str | None, str | None]:
        if project is None:
            return None, None
        display_name = project
        project_file: str | None = None

        snapshot = getattr(pane, "snapshot", None) or getattr(
            pane,
            "_snapshot",
            None,
        )
        snapshot_display = getattr(snapshot, "display_name", None)
        if isinstance(snapshot_display, str) and snapshot_display:
            display_name = snapshot_display
        display_names = getattr(snapshot, "display_names", None)
        if isinstance(display_names, dict):
            display_name = str(display_names.get(project, display_name))
        pane_display = getattr(pane, "_project_display_name", None)
        if isinstance(pane_display, str) and pane_display:
            display_name = pane_display
        pane_project_file = getattr(pane, "project_file", None)
        if isinstance(pane_project_file, str) and pane_project_file:
            project_file = pane_project_file

        choices = getattr(self, "_artifacts_project_choices", None)
        if choices is not None:
            for choice in getattr(choices, "choices", ()):
                if project not in {choice.project_key, choice.display_name}:
                    continue
                project = choice.project_key
                display_name = choice.display_name
                project_file = getattr(choices, "project_files", {}).get(project)
                break
            else:
                project_file = getattr(choices, "project_files", {}).get(project)
                display_name = getattr(choices, "display_names", {}).get(
                    project,
                    display_name,
                )
        return display_name, project_file

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


def _reference_items_for_targets(
    subtab: str,
    pane: Any,
    targets: tuple[tuple[str, ...], ...],
) -> tuple[_ArtifactReferenceItem, ...]:
    cwd = str(Path.cwd())
    items: list[_ArtifactReferenceItem] = []
    if subtab == "commits":
        result = getattr(pane, "result", None)
        entries = () if result is None else result.commits
        commits_by_target: dict[tuple[str, ...], Any] = {
            ("commit", entry.repo, entry.commit.full_id): entry for entry in entries
        }
        project = getattr(pane, "project_scope", None)
        for target in targets:
            entry = commits_by_target.get(target)
            label = (
                f"{target[1]}@{target[2][:7]}"
                if entry is None
                else f"{entry.repo}@{entry.commit.short_id}"
            )
            items.append(_ArtifactReferenceItem(label, target, None, project, cwd))
    elif subtab == "plans":
        plans_by_target: dict[tuple[str, ...], Any] = {
            plan_row_target(row): row for row in getattr(pane, "_rows", {}).values()
        }
        snapshot = getattr(pane, "_snapshot", None)
        workspace_dirs = getattr(snapshot, "workspace_dirs", {})
        for target in targets:
            row = plans_by_target.get(target)
            if row is None:
                continue
            project = row.project
            workspace_dir = workspace_dirs.get(project) or cwd
            items.append(
                _ArtifactReferenceItem(
                    row.row_id,
                    target,
                    row,
                    project,
                    workspace_dir,
                )
            )
    elif subtab == "chats":
        chats_by_target: dict[tuple[str, ...], Any] = {
            chat_row_target(row): row.entry
            for row in getattr(pane, "_rows", {}).values()
        }
        selected = getattr(pane, "selected_entry", None)
        if selected is not None:
            chats_by_target.setdefault(("chat", selected.absolute_path), selected)
        project = getattr(pane, "project_scope", None)
        for target in targets:
            entry = chats_by_target.get(target)
            if entry is None:
                continue
            items.append(
                _ArtifactReferenceItem(
                    entry.basename,
                    target,
                    None,
                    project,
                    cwd,
                )
            )
    else:
        issues = getattr(pane, "issues", ())
        issues_by_target: dict[tuple[str, ...], Any] = {
            pane._issue_target(issue): issue for issue in issues
        }
        selected = getattr(pane, "selected_issue", None)
        if selected is not None:
            issues_by_target.setdefault(pane._issue_target(selected), selected)
        for target in targets:
            issue = issues_by_target.get(target)
            if issue is None:
                continue
            items.append(
                _ArtifactReferenceItem(
                    f"#{issue.number}",
                    target,
                    None,
                    target[1],
                    cwd,
                )
            )
    return tuple(items)


def _resolve_artifact_references(
    selection: _ArtifactReferenceSelection,
) -> tuple[str, ...]:
    contexts: dict[tuple[str, str | None], Any] = {}
    references: list[str] = []
    for item in selection.items:
        context_key = (item.workspace_dir, item.project)
        context = contexts.get(context_key)
        if context is None:
            context = artifact_ref_context(
                item.workspace_dir,
                _workspace_num(item.workspace_dir),
                item.project,
            )
            contexts[context_key] = context
        reference = reference_for_entry_target(
            selection.subtab,
            item.target,
            context=context,
            row=item.row,
        )
        if reference is None:
            raise ValueError(_missing_reference_message(selection.subtab, item.label))
        references.append(f"@{reference}")
    return tuple(references)


def _workspace_num(workspace_dir: str) -> int:
    try:
        from sase.workspace_provider import find_marker_from_cwd

        found = find_marker_from_cwd(workspace_dir)
    except Exception:
        return 1
    if found is None:
        return 1
    workspace_num = found[1].workspace_num
    return workspace_num if isinstance(workspace_num, int) and workspace_num > 0 else 1


def _missing_reference_message(subtab: str, label: str) -> str:
    if subtab == "chats":
        reason = "it is an imported transcript outside the chats root"
    elif subtab == "plans":
        reason = "it has no canonical document reference"
    else:
        reason = "its artifact identity is incomplete"
    return f"{label} cannot be referenced because {reason}"


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


__all__ = ["ClipboardArtifactsMixin"]
