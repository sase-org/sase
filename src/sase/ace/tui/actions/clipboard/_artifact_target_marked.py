"""Marked-entry actions for artifact copy targets."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from sase.core.agent_identity_facade import present_agent_name

from ...models.artifact_file_clipboard import (
    artifact_file_clipboard_path,
    artifact_file_source_clipboard_path,
)
from ...widgets.artifacts.beads_list import bead_row_target
from ...widgets.artifacts.chats_list import chat_row_target
from ...widgets.artifacts.plans_list import plan_row_target
from ._artifact_target_support import ClipboardArtifactTargetSupportMixin
from ._artifact_target_values import (
    artifact_file_contents,
    bead_copy_value,
    commit_plan_reference,
    plan_copy_value,
    plural,
)


class ClipboardArtifactMarkedTargetsMixin(ClipboardArtifactTargetSupportMixin):
    """Copy individual fields from visible marked artifact entries."""

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
            plan = commit_plan_reference(pane._view_spec(entry).message)
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
            plural_label=labels[target],
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
                    partial(plan_copy_value, pane, row, target),
                )
                for row in rows
            ],
            plural_label=(
                "owning bead ids"
                if target == "bead_id"
                else "owning bead design references"
                if target == "design"
                else f"plan {plural(target)}"
            ),
        )

    def _copy_marked_bead_targets(
        self,
        pane: Any,
        targets: tuple[tuple[str, ...], ...],
        target: str,
    ) -> None:
        if not targets:
            return
        by_target = {
            bead_row_target(row): row for row in getattr(pane, "_rows", {}).values()
        }
        rows = [by_target[item] for item in targets if item in by_target]
        self._schedule_marked_copy(
            [
                (
                    row.row_id,
                    partial(bead_copy_value, pane, row, target),
                )
                for row in rows
            ],
            plural_label=f"bead {plural(target)}",
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
            plural_label=labels[target],
            task_name="sase-chat-copy-marked",
        )

    def _copy_marked_file_targets(
        self,
        pane: Any,
        targets: tuple[tuple[str, ...], ...],
        target: str,
    ) -> None:
        if not targets:
            return
        entries = pane.entries_for_targets(targets)
        if not entries:
            self.notify(  # type: ignore[attr-defined]
                "No marked artifact files are available to copy",
                severity="warning",
            )
            return

        if target == "label":
            self._schedule_artifacts_copy(
                "\n".join(entry.label for entry in entries),
                copied_message=f"Copied {len(entries)} artifact file labels",
            )
            return

        state = {"successes": 0, "failures": 0, "missing": 0}

        def path_values() -> str:
            values: list[str] = []
            for entry in entries:
                copy_path = (
                    artifact_file_clipboard_path(entry)
                    if target == "path"
                    else artifact_file_source_clipboard_path(entry)
                )
                if copy_path is None:
                    state["failures"] += 1
                    continue
                values.append(copy_path.text)
                state["missing"] += int(copy_path.missing)
            state["successes"] = len(values)
            if not values:
                path_kind = "stored" if target == "path" else "source"
                raise ValueError(f"marked artifact files have no {path_kind} paths")
            return "\n".join(values)

        if target in {"path", "source"}:

            def path_message() -> str:
                path_kind = "stored" if target == "path" else "source"
                message = f"Copied {state['successes']} {path_kind} paths"
                if state["failures"]:
                    message += f" — {state['failures']} unavailable"
                if state["missing"]:
                    message += f" — {state['missing']} no longer exist"
                return message

            self._schedule_artifacts_copy(
                path_values,
                copied_message=path_message,
                task_name=f"sase-file-copy-marked-{target}",
            )
            return

        contents: list[tuple[str, str | Callable[[], str]]] = []
        binary_modes: list[str] = []
        for entry in entries:
            view_mode = pane.snapshot.view_mode_for(entry)
            if view_mode not in {"markdown", "text"}:
                binary_modes.append(view_mode or entry.kind)
                continue
            contents.append((entry.label, partial(artifact_file_contents, entry)))
        if not contents:
            kinds = ", ".join(dict.fromkeys(binary_modes))
            self.notify(  # type: ignore[attr-defined]
                f"Cannot copy marked {kinds or 'binary'} artifact-file contents",
                severity="warning",
            )
            return
        self._schedule_marked_copy(
            contents,
            plural_label="artifact-file contents",
            task_name="sase-file-copy-marked-contents",
            unavailable_count=len(binary_modes),
        )


__all__ = ["ClipboardArtifactMarkedTargetsMixin"]
