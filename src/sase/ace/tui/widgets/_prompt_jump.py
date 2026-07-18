"""PromptTextArea jump-to-definition command mixin."""

from __future__ import annotations

import asyncio
import shlex
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.ace.tui.graphics import is_supported_image_path, view_artifact_file
from sase.ace.tui.graphics._viewer_tmux_common import is_tmux_session
from sase.ace.tui.util.external_tool import suspend_for_external_tool
from sase.ace.tui.widgets._prompt_jump_target import (
    JumpError,
    JumpTarget,
    JumpToken,
    build_jump_editor_argv,
    detect_jump_target_at_cursor,
    resolve_jump_target,
)
from sase.workflows.commit.editor_utils import get_editor

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase

    from sase.ace.tui.modals.jump_action_modal import JumpChoice
else:
    _MixinBase = object
    JumpChoice = str


class PromptJumpMixin(_MixinBase):
    """Normal-mode jump-to-definition command for prompt references."""

    if TYPE_CHECKING:
        _prompt_jump_request_id: int

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _find_prompt_bar(self) -> Any: ...
        def _known_slash_skills_for_action(
            self, cursor_offset: int
        ) -> frozenset[str] | None: ...
        def _preview_context(self) -> tuple[str | None, str]: ...
        def _refocus_if_needed(self) -> None: ...

    def _jump_to_definition_under_cursor(self, *, prefer_load: bool = False) -> None:
        """Resolve and present jump actions for the token under the cursor."""
        offset = self._absolute_offset(self.cursor_location)
        known_skills = self._known_slash_skills_for_action(offset)
        if known_skills is None:
            return
        token = detect_jump_target_at_cursor(
            self.text,
            offset,
            known_skills=known_skills,
        )
        if token is None:
            self.notify(
                "Move the cursor onto an xprompt, skill, or file path to jump to its definition",
                severity="warning",
            )
            return

        project, base_dir = self._preview_context()
        self._prompt_jump_request_id += 1
        request_id = self._prompt_jump_request_id
        self.run_worker(
            self._resolve_jump_async(
                token,
                project=project,
                base_dir=base_dir,
                request_id=request_id,
                prefer_load=prefer_load,
            ),
            name=f"prompt-jump:{request_id}",
        )

    async def _resolve_jump_async(
        self,
        token: JumpToken,
        *,
        project: str | None,
        base_dir: str,
        request_id: int,
        prefer_load: bool = False,
    ) -> None:
        try:
            payload = await asyncio.to_thread(
                resolve_jump_target,
                token,
                project=project,
                base_dir=base_dir,
            )
        except JumpError as exc:
            if request_id == self._prompt_jump_request_id and self.is_mounted:
                self.notify(str(exc), severity="warning")
            return
        except Exception as exc:
            if request_id == self._prompt_jump_request_id and self.is_mounted:
                self.notify(f"Could not jump to {token.raw}: {exc}", severity="error")
            return

        if request_id != self._prompt_jump_request_id or not self.is_mounted:
            return
        if prefer_load:
            if payload.loadable_markdown is None:
                self.notify(
                    "This workflow definition is preview/editor-only",
                    severity="warning",
                )
                return
            self._load_jump_target_into_prompt(payload)
            return
        self._present_jump_actions(payload)

    def _edit_definition_under_cursor(self) -> None:
        """Resolve ``gd`` directly into the in-place authoring surface."""
        self._jump_to_definition_under_cursor(prefer_load=True)

    def _present_jump_actions(self, payload: JumpTarget) -> None:
        if payload.kind_label == "file" and is_supported_image_path(
            payload.source_path
        ):
            self._view_jump_image(payload)
            return

        choices = self._jump_action_choices(payload)
        if len(choices) == 1:
            self._perform_jump_action(choices[0], payload)
            return

        from sase.ace.tui.modals.jump_action_modal import JumpActionModal

        def _on_result(choice: JumpChoice | None) -> None:
            self._refocus_if_needed()
            if choice is not None:
                self._perform_jump_action(choice, payload)

        self.app.push_screen(
            JumpActionModal(
                title=payload.title,
                kind_label=payload.kind_label,
                icon=payload.icon,
                source_display=_source_display(payload),
                choices=choices,
            ),
            _on_result,
        )

    def _view_jump_image(self, payload: JumpTarget) -> None:
        """Display a resolved image target with the terminal artifact viewer."""
        try:
            with suspend_for_external_tool(
                self.app,
                action="jump_to_definition",
                tool_kind="artifact_file_viewer",
                path_count=1,
                status_message="Opening image…",
            ):
                result = view_artifact_file(payload.source_path)
            if result.warning is not None:
                self.notify(result.warning, severity="warning")
        finally:
            self._refocus_if_needed()

    def _jump_action_choices(self, payload: JumpTarget) -> list[JumpChoice]:
        choices: list[JumpChoice] = []
        if is_tmux_session():
            choices.append("tmux")
        choices.append("editor")
        if payload.loadable_markdown is not None and self._can_load_jump_into_prompt():
            choices.append("load")
        return choices

    def _can_load_jump_into_prompt(self) -> bool:
        bar = self._find_prompt_bar()
        return bar is not None and getattr(bar, "_mode", None) == "prompt"

    def _perform_jump_action(self, choice: JumpChoice, payload: JumpTarget) -> None:
        if choice == "tmux":
            self.run_worker(
                self._open_jump_target_in_tmux_pane_async(payload),
                name=f"prompt-jump-tmux:{payload.source_path}",
            )
        elif choice == "editor":
            self._open_jump_target_in_this_pane(payload)
        elif choice == "load":
            self._load_jump_target_into_prompt(payload)

    async def _open_jump_target_in_tmux_pane_async(
        self,
        payload: JumpTarget,
    ) -> None:
        error = await asyncio.to_thread(_open_jump_target_in_tmux_pane, payload)
        if error and self.is_mounted:
            self.notify(error, severity="error")

    def _open_jump_target_in_this_pane(self, payload: JumpTarget) -> None:
        editor = get_editor()
        argv = build_jump_editor_argv(
            editor,
            payload.source_path,
            payload.line,
            payload.col,
        )
        try:
            with suspend_for_external_tool(
                self.app,
                action="jump_to_definition",
                tool_kind="editor",
                command=editor,
                path_count=1,
                status_message="Opening definition...",
            ):
                subprocess.run(argv, check=False)
        except OSError as exc:
            self.notify(f"Could not open editor: {exc}", severity="error")
        finally:
            self._refocus_if_needed()

    def _load_jump_target_into_prompt(self, payload: JumpTarget) -> None:
        if payload.loadable_markdown is None:
            self.notify(
                "This target cannot be loaded into the prompt", severity="warning"
            )
            return
        bar = self._find_prompt_bar()
        if bar is None:
            self.notify("No prompt input bar is available", severity="warning")
            return
        load = getattr(bar, "stash_all_and_load_xprompt_markdown", None)
        if not callable(load):
            self.notify("Prompt input bar cannot load this target", severity="error")
            return
        from sase.ace.tui.widgets.prompt_stack import XPromptBinding
        from sase.xprompt.prompt_frontmatter import PromptFrontmatter

        binding = None
        if payload.is_editable:
            try:
                if (
                    payload.source_id
                    and payload.source_id
                    in {
                        "config",
                        "local_config",
                        "default_config",
                    }
                    or (
                        payload.source_id
                        and payload.source_id.startswith(
                            (
                                "config_overlay:",
                                "project_local_config:",
                                "plugin_config:",
                            )
                        )
                    )
                ):
                    binding = XPromptBinding.for_config(
                        payload.source_path, payload.definition_name or ""
                    )
                else:
                    binding = XPromptBinding.for_file(payload.source_path)
            except OSError:
                binding = None
        load(payload.loadable_markdown, binding=binding)
        if not payload.is_editable:
            self.notify("Read-only source — gw will save-as", severity="warning")
        if PromptFrontmatter.parse(payload.loadable_markdown).has_comments:
            self.notify(
                "Frontmatter comments cannot survive structured save; inspect raw mode",
                severity="warning",
            )
        self._refocus_if_needed()


def _source_display(payload: JumpTarget) -> str:
    suffix = ""
    if payload.line is not None:
        suffix = f":{payload.line}"
        if payload.col is not None:
            suffix += f":{payload.col}"
    return f"{payload.source_path}{suffix}"


def _open_jump_target_in_tmux_pane(payload: JumpTarget) -> str | None:
    editor = get_editor()
    argv = build_jump_editor_argv(
        editor,
        payload.source_path,
        payload.line,
        payload.col,
    )
    command = [
        "tmux",
        "split-window",
        "-h",
        "-c",
        str(Path(payload.source_path).parent),
        "-P",
        "-F",
        "#{pane_id}",
        shlex.join(argv),
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return "tmux executable not found"
    except OSError as exc:
        return f"Could not open tmux pane: {exc}"

    if result.returncode == 0:
        return None

    stderr = result.stderr.strip()
    suffix = f": {stderr}" if stderr else ""
    return f"tmux split-window failed with exit code {result.returncode}{suffix}"


__all__ = ["PromptJumpMixin"]
