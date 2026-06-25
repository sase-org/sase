"""Save prompt-bar drafts as reusable xprompts."""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import (
    SaveTargetFormat,
    save_config_xprompt,
    save_markdown_xprompt,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from sase.ace.tui.modals import XPromptLocation, XPromptSaveTarget
    from sase.ace.tui.widgets._prompt_input_bar_stack_actions import (
        StashedPromptPane,
    )


class PromptBarSaveXpromptMixin:
    """Handle prompt-bar save-as-xprompt requests."""

    _prompt_context: PromptContext | None

    async def on_prompt_input_bar_save_as_xprompt_requested(
        self, event: object
    ) -> None:
        """Open the save-as-xprompt target picker for the captured draft."""
        import asyncio

        from ...modals import XPromptSaveTargetModal
        from ...modals.xprompt_save_target_modal import load_xprompt_save_rows
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.SaveAsXpromptRequested):
            return

        body = self._captured_xprompt_body(event.panes)
        frontmatter = self._captured_xprompt_frontmatter(event.panes)
        if not body.strip() and frontmatter.is_empty:
            self.notify(  # type: ignore[attr-defined]
                "Nothing to save as an xprompt",
                severity="warning",
            )
            return

        project = (
            self._prompt_context.project_name
            if self._prompt_context is not None
            else None
        )
        rows = await asyncio.to_thread(load_xprompt_save_rows, project)

        def _on_target(target: XPromptSaveTarget | None) -> None:
            if target is None:
                return
            if target.kind == "create":
                self._spawn_xprompt_save_task(
                    self._create_xprompt_flow(frontmatter, body)
                )
                return
            self._confirm_overwrite_xprompt(target, frontmatter, body)

        self.push_screen(  # type: ignore[attr-defined]
            XPromptSaveTargetModal(
                rows,
                project=project,
                pane_count=sum(1 for pane in event.panes if pane.text.strip()),
                has_frontmatter=not frontmatter.is_empty,
            ),
            _on_target,
        )

    @staticmethod
    def _captured_xprompt_body(panes: list[StashedPromptPane]) -> str:
        """Return canonical multi-prompt body text for captured panes."""
        return "\n---\n".join(pane.text for pane in panes if pane.text.strip())

    @staticmethod
    def _captured_xprompt_frontmatter(
        panes: list[StashedPromptPane],
    ) -> PromptFrontmatter:
        """Return parsed shared frontmatter from captured panes."""
        raw = next((pane.frontmatter for pane in panes if pane.frontmatter), "")
        return PromptFrontmatter.parse(raw)

    def _confirm_overwrite_xprompt(
        self,
        target: XPromptSaveTarget,
        frontmatter: PromptFrontmatter,
        body: str,
    ) -> None:
        from ...modals import ConfirmActionModal

        display_path = target.display_path or target.path

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._spawn_xprompt_save_task(
                self._write_xprompt_target(
                    target,
                    frontmatter,
                    body,
                    is_new=False,
                    toast_name=target.name,
                )
            )

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                "Overwrite XPrompt",
                f"Overwrite xprompt '{target.name}' at {display_path}?",
            ),
            _on_confirm,
        )

    async def _create_xprompt_flow(
        self,
        frontmatter: PromptFrontmatter,
        body: str,
    ) -> None:
        from ...modals import XPromptLocationModal

        project = (
            self._prompt_context.project_name
            if self._prompt_context is not None
            else None
        )

        def _on_location(location: XPromptLocation | None) -> None:
            if location is None:
                return
            self._spawn_xprompt_save_task(
                self._ask_new_xprompt_name(location, frontmatter, body)
            )

        self.push_screen(  # type: ignore[attr-defined]
            XPromptLocationModal(project=project),
            _on_location,
        )

    async def _ask_new_xprompt_name(
        self,
        location: XPromptLocation,
        frontmatter: PromptFrontmatter,
        body: str,
    ) -> None:
        import asyncio

        from ...modals import XPromptNameModal

        existing_names = await asyncio.to_thread(_existing_names_for_location, location)

        def _on_name(name: str | None) -> None:
            if name is None:
                return
            target = _target_for_new_xprompt(location, name)
            if _name_exists_at_location(location, name, existing_names):
                self._confirm_create_overwrite(target, frontmatter, body, name)
                return
            self._spawn_xprompt_save_task(
                self._write_xprompt_target(
                    target,
                    _frontmatter_for_new_target(target, frontmatter, name),
                    body,
                    is_new=True,
                    toast_name=name,
                )
            )

        self.push_screen(  # type: ignore[attr-defined]
            XPromptNameModal(
                location_label=location.label,
                location_path=location.path,
                existing_names=existing_names,
            ),
            _on_name,
        )

    def _confirm_create_overwrite(
        self,
        target: XPromptSaveTarget,
        frontmatter: PromptFrontmatter,
        body: str,
        name: str,
    ) -> None:
        from ...modals import ConfirmActionModal

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._spawn_xprompt_save_task(
                self._write_xprompt_target(
                    target,
                    _frontmatter_for_new_target(target, frontmatter, name),
                    body,
                    is_new=False,
                    toast_name=name,
                )
            )

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                "Overwrite Existing XPrompt",
                f"'{name}' already exists at this location. Overwrite it?",
            ),
            _on_confirm,
        )

    async def _write_xprompt_target(
        self,
        target: XPromptSaveTarget,
        frontmatter: PromptFrontmatter,
        body: str,
        *,
        is_new: bool,
        toast_name: str,
    ) -> None:
        import asyncio

        try:
            await asyncio.to_thread(_write_target_sync, target, frontmatter, body)
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to save xprompt: {exc}",
                severity="error",
            )
            return

        verb = "Created" if is_new else "Saved draft as"
        self.notify(f"{verb} xprompt '{toast_name}'")  # type: ignore[attr-defined]
        self._offer_git_commit(target.path, is_new=is_new, xprompt_name=toast_name)

    def _offer_git_commit(
        self, file_path: str, *, is_new: bool, xprompt_name: str
    ) -> None:
        """If the file is in a git repo and has changes, offer to commit/push."""
        from ...modals import ConfirmActionModal
        from ...modals.xprompt_browser_helpers import get_git_root, has_git_changes
        from sase.config import get_use_chezmoi

        git_root = get_git_root(file_path)
        if git_root is None or not has_git_changes(git_root, file_path):
            return

        rel_path = os.path.relpath(file_path, git_root)
        verb = "Add" if is_new else "Update"

        def _run_chezmoi_apply() -> None:
            if not get_use_chezmoi():
                return
            result = subprocess.run(
                ["chezmoi", "apply"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                self.notify("Applied chezmoi changes")  # type: ignore[attr-defined]
            else:
                self.notify(  # type: ignore[attr-defined]
                    f"chezmoi apply failed: {result.stderr.strip()}",
                    severity="error",
                )

        def _on_commit_push_answer(confirmed: bool | None) -> None:
            if not confirmed:
                return
            subprocess.run(
                ["git", "-C", git_root, "add", "--", file_path],
                capture_output=True,
                check=False,
            )
            subject = f"chore: {verb} xprompt {xprompt_name}"
            from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

            message = apply_auto_commit_type_tag(subject, "xprompt")
            result = subprocess.run(
                ["git", "-C", git_root, "commit", "-m", message],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self.notify(  # type: ignore[attr-defined]
                    f"Commit failed: {result.stderr.strip()}",
                    severity="error",
                )
                return
            self.notify(f"Committed: {subject}")  # type: ignore[attr-defined]

            pull_result = subprocess.run(
                ["git", "-C", git_root, "pull", "--rebase"],
                capture_output=True,
                text=True,
                check=False,
            )
            if pull_result.returncode != 0:
                self.notify(  # type: ignore[attr-defined]
                    f"Pull failed: {pull_result.stderr.strip()}",
                    severity="error",
                )
                return
            push_result = subprocess.run(
                ["git", "-C", git_root, "push"],
                capture_output=True,
                text=True,
                check=False,
            )
            if push_result.returncode == 0:
                self.notify("Pushed to remote")  # type: ignore[attr-defined]
                _run_chezmoi_apply()
            else:
                self.notify(  # type: ignore[attr-defined]
                    f"Push failed: {push_result.stderr.strip()}",
                    severity="error",
                )

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                "Commit & Push",
                f"Commit and push changes to '{rel_path}'?",
            ),
            _on_commit_push_answer,
        )

    def _spawn_xprompt_save_task(self, coro: Coroutine[object, object, None]) -> None:
        """Run *coro* on the running loop, holding a reference until complete."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            return
        task = loop.create_task(coro)
        tasks = getattr(self, "_xprompt_save_async_tasks", None)
        if tasks is None:
            tasks = set()
            self._xprompt_save_async_tasks = tasks
        tasks.add(task)
        task.add_done_callback(tasks.discard)


def _write_target_sync(
    target: XPromptSaveTarget,
    frontmatter: PromptFrontmatter,
    body: str,
) -> None:
    if target.target_format == SaveTargetFormat.MARKDOWN:
        save_markdown_xprompt(target.path, frontmatter, body)
        return
    if target.target_format == SaveTargetFormat.CONFIG:
        entry_name = target.entry_name or target.name
        if not save_config_xprompt(target.path, entry_name, frontmatter, body):
            raise RuntimeError("config insertion failed")
        return
    raise RuntimeError("unsupported xprompt save target")


def _target_for_new_xprompt(
    location: XPromptLocation,
    name: str,
) -> XPromptSaveTarget:
    from ...modals import XPromptSaveTarget

    if location.location_type == "directory":
        filename = name.replace("/", "_") + ".md"
        path = str(Path(location.path) / filename)
        return XPromptSaveTarget(
            kind="overwrite",
            name=name,
            path=path,
            target_format=SaveTargetFormat.MARKDOWN,
            display_path=_short_display_path(path),
        )
    return XPromptSaveTarget(
        kind="overwrite",
        name=name,
        path=location.path,
        target_format=SaveTargetFormat.CONFIG,
        entry_name=name,
        display_path=_short_display_path(location.path),
    )


def _frontmatter_for_new_target(
    target: XPromptSaveTarget,
    frontmatter: PromptFrontmatter,
    name: str,
) -> PromptFrontmatter:
    if target.target_format == SaveTargetFormat.MARKDOWN and frontmatter.name == name:
        return replace(frontmatter, name=None)
    return frontmatter


def _existing_names_for_location(location: XPromptLocation) -> set[str]:
    if location.location_type == "directory":
        path = Path(location.path)
        if not path.is_dir():
            return set()
        return {entry.stem for entry in path.glob("*.md") if entry.is_file()}

    import yaml  # type: ignore[import-untyped]

    config_path = Path(location.path)
    if not config_path.is_file():
        return set()
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    xprompts = data.get("xprompts")
    if not isinstance(xprompts, dict):
        return set()
    return {str(name) for name in xprompts}


def _name_exists_at_location(
    location: XPromptLocation,
    name: str,
    existing_names: set[str],
) -> bool:
    if location.location_type == "directory":
        return name.replace("/", "_") in existing_names
    return name in existing_names


def _short_display_path(path: str) -> str:
    home = str(Path.home())
    cwd = str(Path.cwd())
    if path.startswith(cwd + "/"):
        return "./" + path[len(cwd) + 1 :]
    if path.startswith(home + "/"):
        return "~" + path[len(home) :]
    return path


__all__ = ["PromptBarSaveXpromptMixin"]
