"""Save prompt-bar drafts as reusable xprompts."""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.actions.task_actions import (
    TrackedTaskCompletion,
    TrackedTaskResult,
)
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
    # Provided by the app's startup/state-init mixins; refreshed here after a
    # snippet write so ``get_snippets()`` rebuilds with the new template.
    _user_snippets: dict[str, str]
    _snippets_cache: dict[str, str] | None

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

        non_empty_count = sum(1 for pane in event.panes if pane.text.strip())
        # The snippet save option is always offered. Its source is the active
        # pane captured separately as ``snippet_body``; a legacy/direct event
        # without that field falls back to the xprompt body, but only when a
        # single non-blank pane makes that unambiguous. Snippets are single
        # templates, so the active-pane body never carries ``---`` separators.
        snippet_body = event.snippet_body
        if snippet_body is None:
            snippet_body = body if non_empty_count == 1 else ""
        snippet_body = snippet_body.strip()

        def _on_target(target: XPromptSaveTarget | None) -> None:
            if target is None:
                return
            if target.kind == "create":
                self._spawn_xprompt_save_task(
                    self._create_xprompt_flow(frontmatter, body)
                )
                return
            if target.kind == "create_snippet":
                if not snippet_body:
                    self.notify(  # type: ignore[attr-defined]
                        "Current prompt pane is empty - nothing to save as a snippet",
                        severity="warning",
                    )
                    return
                self._spawn_xprompt_save_task(self._create_snippet_flow(snippet_body))
                return
            self._confirm_overwrite_xprompt(target, frontmatter, body)

        self.push_screen(  # type: ignore[attr-defined]
            XPromptSaveTargetModal(
                rows,
                project=project,
                pane_count=non_empty_count,
                has_frontmatter=not frontmatter.is_empty,
                allow_create_snippet=True,
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
        from ...modals import ConfirmActionModal, ConfirmKind

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
                f"Overwrite xprompt '{target.name}'?",
                subject=display_path,
                kind=ConfirmKind.DANGER,
                confirm_label="Overwrite",
                cancel_label="Cancel",
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

    async def _create_snippet_flow(self, body: str) -> None:
        import asyncio

        from ...modals import (
            SnippetConfigLocation,
            SnippetConfigLocationModal,
            load_snippet_config_locations,
        )

        project = (
            self._prompt_context.project_name
            if self._prompt_context is not None
            else None
        )
        locations = await asyncio.to_thread(load_snippet_config_locations, project)
        if not any(location.is_selectable for location in locations):
            self.notify(  # type: ignore[attr-defined]
                "No writable config file available to store a snippet",
                severity="warning",
            )
            return

        def _on_location(location: SnippetConfigLocation | None) -> None:
            if location is None:
                return
            self._spawn_xprompt_save_task(self._ask_snippet_name(location, body))

        self.push_screen(  # type: ignore[attr-defined]
            SnippetConfigLocationModal(locations),
            _on_location,
        )

    async def _ask_snippet_name(
        self,
        location: object,
        body: str,
    ) -> None:
        import asyncio

        from ...modals import SnippetConfigLocation, SnippetNameModal

        assert isinstance(location, SnippetConfigLocation)
        existing_names = await asyncio.to_thread(_existing_snippet_names, location.path)

        def _on_name(name: str | None) -> None:
            if name is None:
                return
            self._spawn_xprompt_save_task(self._write_snippet(location, name, body))

        self.push_screen(  # type: ignore[attr-defined]
            SnippetNameModal(
                config_path=location.path,
                display_path=location.display_path,
                existing_names=existing_names,
            ),
            _on_name,
        )

    async def _write_snippet(
        self,
        location: object,
        name: str,
        body: str,
    ) -> None:
        import asyncio

        from ...modals import SnippetConfigLocation

        assert isinstance(location, SnippetConfigLocation)
        try:
            await asyncio.to_thread(_write_snippet_sync, location.path, name, body)
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to save snippet: {exc}",
                severity="error",
            )
            return

        self.notify(  # type: ignore[attr-defined]
            f"Created snippet '{name}' in {location.display_path}"
        )
        self._refresh_snippet_caches()
        self._offer_git_commit(
            location.path,
            is_new=True,
            xprompt_name=name,
            noun="snippet",
            commit_type="snippet",
        )

    def _refresh_snippet_caches(self) -> None:
        """Reload merged ``ace.snippets`` and drop the resolved snippet cache.

        The merged-config cache invalidates itself by file mtime, so re-reading
        it after the write picks up the new entry; we then refresh the app's
        ``_user_snippets`` and clear ``_snippets_cache`` so the next
        ``get_snippets()`` rebuilds with the new template.
        """
        from sase.config import load_merged_config

        merged = load_merged_config()
        ace_cfg = merged.get("ace", {}) if isinstance(merged, dict) else {}
        raw = ace_cfg.get("snippets", {}) if isinstance(ace_cfg, dict) else {}
        if isinstance(raw, dict):
            self._user_snippets = {
                key: value
                for key, value in raw.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        else:
            self._user_snippets = {}
        self._snippets_cache = None

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
        from ...modals import ConfirmActionModal, ConfirmKind

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
                f"'{name}' already exists at this location.",
                subject=target.display_path or target.path,
                kind=ConfirmKind.DANGER,
                confirm_label="Overwrite",
                cancel_label="Cancel",
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
        self,
        file_path: str,
        *,
        is_new: bool,
        xprompt_name: str,
        noun: str = "xprompt",
        commit_type: str = "xprompt",
    ) -> None:
        """If the file is in a git repo and has changes, offer to commit/push."""
        from ...modals import ConfirmActionModal
        from ...modals.xprompt_browser_helpers import get_git_root, has_git_changes

        git_root = get_git_root(file_path)
        if git_root is None or not has_git_changes(git_root, file_path):
            return

        rel_path = os.path.relpath(file_path, git_root)
        verb = "Add" if is_new else "Update"
        subject = f"chore: {verb} {noun} {xprompt_name}"
        from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

        message = apply_auto_commit_type_tag(subject, commit_type)

        def _on_commit_push_answer(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._submit_xprompt_commit_task(
                git_root=git_root,
                file_path=file_path,
                rel_path=rel_path,
                message=message,
                noun=noun,
            )

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                "Commit & Push",
                "Commit and push your saved changes?",
                subject=rel_path,
                icon="↑",
                confirm_label="Commit & push",
                cancel_label="Skip",
                default="confirm",
            ),
            _on_commit_push_answer,
        )

    def _submit_xprompt_commit_task(
        self,
        *,
        git_root: str,
        file_path: str,
        rel_path: str,
        message: str,
        noun: str = "xprompt",
    ) -> None:
        """Run the git commit/push flow through the tracked task queue."""

        def _task() -> TrackedTaskResult[None]:
            success, result_message = _run_git_commit_push_sync(
                git_root=git_root,
                file_path=file_path,
                commit_message=message,
            )
            return TrackedTaskResult(
                success=success,
                message=result_message,
                error=None if success else result_message,
            )

        def _on_complete(completion: TrackedTaskCompletion[None]) -> None:
            if completion.success:
                self.notify(completion.message)  # type: ignore[attr-defined]
            else:
                self.notify(  # type: ignore[attr-defined]
                    completion.message,
                    severity="error",
                )

        submit = getattr(self, "_submit_tracked_task", None)
        if submit is None:
            self.notify(  # type: ignore[attr-defined]
                f"Could not commit {noun}: background task queue unavailable.",
                severity="error",
            )
            return

        submit(
            f"{noun}-commit",
            rel_path,
            git_root,
            _task,
            display_name=f"commit {noun} {rel_path}",
            dedup_key=f"{noun}-commit:{git_root}:{rel_path}",
            duplicate_message=f"Another {noun} commit is already running for {rel_path}.",
            on_complete=_on_complete,
            reload_on_complete=False,
            notify_on_complete=False,
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


def _existing_snippet_names(config_path: str) -> set[str]:
    """Return the snippet triggers defined in *config_path* only.

    Reads ``ace.snippets`` from the single selected YAML file (not the merged
    config) so the name modal's "already defined" warning and overwrite behavior
    reflect what writing to this file would actually replace.
    """
    import yaml  # type: ignore[import-untyped]

    path = Path(config_path)
    if not path.is_file():
        return set()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    ace = data.get("ace")
    if not isinstance(ace, dict):
        return set()
    snippets = ace.get("snippets")
    if not isinstance(snippets, dict):
        return set()
    return {str(name) for name in snippets}


def _write_snippet_sync(config_path: str, name: str, body: str) -> None:
    from sase.xprompt.snippet_config_yaml import insert_snippet_into_config

    if not insert_snippet_into_config(config_path, name, body):
        raise RuntimeError("snippet insertion failed")


def _name_exists_at_location(
    location: XPromptLocation,
    name: str,
    existing_names: set[str],
) -> bool:
    if location.location_type == "directory":
        return name.replace("/", "_") in existing_names
    return name in existing_names


def _run_git_commit_push_sync(
    *,
    git_root: str,
    file_path: str,
    commit_message: str,
) -> tuple[bool, str]:
    """Synchronously stage, commit, pull, push, and optionally apply chezmoi."""
    add_result = subprocess.run(
        ["git", "-C", git_root, "add", "--", file_path],
        capture_output=True,
        text=True,
        check=False,
    )
    if add_result.returncode != 0:
        return False, f"Git add failed: {_process_error_text(add_result)}"

    commit_result = subprocess.run(
        ["git", "-C", git_root, "commit", "-m", commit_message],
        capture_output=True,
        text=True,
        check=False,
    )
    if commit_result.returncode != 0:
        return False, f"Commit failed: {_process_error_text(commit_result)}"

    pull_result = subprocess.run(
        ["git", "-C", git_root, "pull", "--rebase"],
        capture_output=True,
        text=True,
        check=False,
    )
    if pull_result.returncode != 0:
        return False, f"Pull failed: {_process_error_text(pull_result)}"

    push_result = subprocess.run(
        ["git", "-C", git_root, "push"],
        capture_output=True,
        text=True,
        check=False,
    )
    if push_result.returncode != 0:
        return False, f"Push failed: {_process_error_text(push_result)}"

    from sase.config import get_use_chezmoi

    if not get_use_chezmoi():
        return True, "Committed and pushed to remote"

    try:
        chezmoi_result = subprocess.run(
            ["chezmoi", "apply"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False, "chezmoi not found on PATH"
    if chezmoi_result.returncode != 0:
        return False, f"chezmoi apply failed: {_process_error_text(chezmoi_result)}"
    return True, "Committed and pushed to remote; applied chezmoi changes"


def _process_error_text(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "command failed").strip()


def _short_display_path(path: str) -> str:
    home = str(Path.home())
    cwd = str(Path.cwd())
    if path.startswith(cwd + "/"):
        return "./" + path[len(cwd) + 1 :]
    if path.startswith(home + "/"):
        return "~" + path[len(home) :]
    return path


__all__ = ["PromptBarSaveXpromptMixin"]
