"""Home-mode prompt context and xprompt loading for the prompt input bar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.patch.project_spec_path import preferred_project_spec_path
from sase.core.paths import sase_projects_dir

from ._types import (
    PromptContext,
    PromptOrigin,
    RelaunchOperation,
    begin_prompt_session,
    invalidate_prompt_session,
)

if TYPE_CHECKING:
    from sase.macro.models import InputArg
    from ...widgets.prompt_input_bar import PromptInputBar
    from ...widgets.prompt_stack import XPromptBinding, XPromptReadonlyTarget


class PromptBarHomeMixin:
    """Home-directory prompt context, bar mounting, and xprompt loading."""

    _prompt_context: PromptContext | None
    _active_prompt_bar: PromptInputBar | None

    def _setup_home_prompt_context(
        self,
        display_name: str = "~",
        history_sort_key: str = "home",
        *,
        relaunch_operation: RelaunchOperation | None = None,
        prompt_origin: PromptOrigin = "typed",
    ) -> None:
        """Set up prompt context for home directory mode without showing UI.

        Args:
            display_name: Display name shown in the prompt context.
            history_sort_key: Launch context label propagated to spawned agents.
        """
        from pathlib import Path

        from sase.core.time import generate_timestamp

        timestamp = generate_timestamp()
        workflow_name = f"ace(run)-{timestamp}"

        begin_prompt_session(
            self,
            PromptContext(
                project_name="home",
                cl_name=None,
                project_file=preferred_project_spec_path(
                    str(sase_projects_dir() / "home"), "home"
                ),
                workspace_dir=str(Path.home()),
                workspace_num=0,
                workflow_name=workflow_name,
                timestamp=timestamp,
                history_sort_key=history_sort_key,
                display_name=display_name,
                update_target="",
                is_home_mode=True,
            ),
            relaunch_operation=relaunch_operation,
            prompt_origin=prompt_origin,
        )

    def _load_editor_markdown_into_bar(self, markdown: str) -> None:
        """Reload the mounted prompt bar from cleaned editor markdown.

        Uses editor-file (xprompt markdown) semantics via
        :meth:`PromptInputBar.load_stack_from_xprompt_markdown`: leading xprompt
        frontmatter is lifted into the frontmatter panel and real ``---`` body
        separators split into one prompt pane per agent segment.  Used only for
        ` @`-marker editor returns and whole-stack editor returns — never for
        ordinary history loads, which keep their verbatim single-pane contract.
        """
        from ._prompt_bar_stash_store import mounted_prompt_bar

        bar = mounted_prompt_bar(self)
        if bar is None:
            return
        try:
            bar.load_stack_from_xprompt_markdown(markdown, preserve_target=True)
        except Exception:
            pass

    def _show_prompt_input_bar_for_home(
        self,
        initial_text: str = "",
        display_name: str = "~",
        history_sort_key: str = "home",
        *,
        as_xprompt_markdown: bool = False,
        frontmatter_inputs: list[InputArg] | None = None,
        binding: XPromptBinding | None = None,
        read_only_target: XPromptReadonlyTarget | None = None,
        initial_selected_pane: int | None = None,
        initial_cursor: tuple[int, int] | None = None,
    ) -> None:
        """Show prompt input bar for home directory mode.

        This skips Patch name and bug modals, running the agent from the user's
        home directory without version control or workspace management.

        Args:
            initial_text: Pre-populated text for the prompt input bar.
            display_name: Display name shown in the prompt context.
            history_sort_key: Launch context label propagated to spawned agents.
            as_xprompt_markdown: When True, seed the bar with editor-file
                semantics (lift leading frontmatter, split ``---`` into panes)
                rather than verbatim history-load semantics.  Used by the
                ` @`-marker editor-return remount path.
            frontmatter_inputs: Declared xprompt inputs to stage into the bar's
                prompt frontmatter before mount, so the frontmatter panel
                auto-shows on mount.  Used by the Config XPrompts child
                ``Ctrl+I`` load (parity with the Select XPrompt ``Ctrl+I`` path).
            initial_selected_pane: Optional zero-based pane to focus after
                parsing *initial_text*. Used by prompt-stash restore.
            initial_cursor: Optional zero-based ``(row, column)`` applied to
                the focused pane on mount. Used by prompt-stash restore.
        """
        from ...widgets import PromptInputBar

        # Remove any existing prompt bar before mounting a new one.
        # Must happen before overwriting _prompt_context so the old bar's
        # text is saved with the old context.
        self._unmount_prompt_bar()  # type: ignore[attr-defined]
        # Phase ``space-hot-spare``: every fresh home mount drops a leftover
        # spare first; only the plain ``<space>`` reveal path reuses it.
        try:
            self._discard_prompt_bar_spare()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - spare discard is best-effort.
            pass

        self._setup_home_prompt_context(
            display_name=display_name,
            history_sort_key=history_sort_key,
        )

        # Show prompt input bar
        if as_xprompt_markdown:
            bar = PromptInputBar(
                initial_xprompt_markdown=initial_text,
                initial_selected_pane=initial_selected_pane,
                initial_cursor=initial_cursor,
                id="prompt-input-bar",
            )
        else:
            bar = PromptInputBar(
                initial_value=initial_text,
                initial_selected_pane=initial_selected_pane,
                initial_cursor=initial_cursor,
                id="prompt-input-bar",
            )
        if binding is not None:
            bar.target_xprompt(binding, source_markdown=initial_text)
        elif read_only_target is not None:
            bar.mark_readonly_xprompt_target(read_only_target)
        # Stage declared inputs into the stack's frontmatter pre-mount: the
        # panel refresh is a no-op until the bar mounts, and ``on_mount`` then
        # auto-shows the frontmatter panel from the seeded stack.
        if frontmatter_inputs:
            bar.merge_frontmatter_inputs(frontmatter_inputs)
        self.mount(bar)  # type: ignore[attr-defined]

    def load_xprompt_into_home_prompt_bar(
        self,
        expanded_text: str,
        *,
        display_name: str,
        inputs: list[InputArg] | None = None,
    ) -> None:
        """Close the Admin Center and load an inline-expanded xprompt into a bar.

        Drives the Config XPrompts child ``Ctrl+I`` load: the selected row
        was already rendered via :func:`expand_inline_xprompt`, so this pops the
        Admin Center modal and opens a fresh home-mode prompt bar carrying the
        rendered *expanded_text* for editing/submission.  Declared *inputs* are
        staged into prompt frontmatter (parity with the Select XPrompt
        ``Ctrl+I`` path), which needs no project/Patch selection.

        Mounting is deferred until after the modal pops so the new bar's
        on-mount focus lands on the revealed main screen rather than fighting
        the closing modal.
        """
        from textual.screen import ModalScreen

        if isinstance(self.screen, ModalScreen):  # type: ignore[attr-defined]
            self.pop_screen()  # type: ignore[attr-defined]

        def _mount() -> None:
            self._show_prompt_input_bar_for_home(
                initial_text=expanded_text,
                display_name=display_name,
                history_sort_key="home",
                frontmatter_inputs=inputs,
            )

        self.call_after_refresh(_mount)  # type: ignore[attr-defined]

    def load_xprompt_definition_into_home_prompt_bar(
        self,
        markdown: str,
        *,
        display_name: str,
        binding: XPromptBinding | None,
        read_only: bool = False,
        read_only_path: str | None = None,
        has_comments: bool = False,
    ) -> None:
        """Close the browser and author a raw simple xprompt definition."""
        from textual.screen import ModalScreen

        from ...widgets.prompt_stack import XPromptReadonlyTarget

        if isinstance(self.screen, ModalScreen):  # type: ignore[attr-defined]
            self.pop_screen()  # type: ignore[attr-defined]

        read_only_target = (
            XPromptReadonlyTarget(reference=display_name, path=read_only_path)
            if read_only
            else None
        )

        def _mount() -> None:
            self._show_prompt_input_bar_for_home(
                initial_text=markdown,
                display_name=display_name,
                history_sort_key="home",
                as_xprompt_markdown=True,
                binding=binding,
                read_only_target=read_only_target,
            )
            if read_only:
                self.notify("Read-only source — gw will save-as", severity="warning")  # type: ignore[attr-defined]
            if has_comments:
                self.notify(  # type: ignore[attr-defined]
                    "Frontmatter comments cannot survive structured save; inspect raw mode",
                    severity="warning",
                )

        self.call_after_refresh(_mount)  # type: ignore[attr-defined]

    def _select_and_open_editor_for_home(
        self,
        initial_text: str = "",
        display_name: str = "~",
        history_sort_key: str = "home",
    ) -> None:
        """Set up home-mode prompt context and open editor directly.

        Combines ``_show_prompt_input_bar_for_home`` + ``ctrl+g`` into a
        single step so the user never sees the prompt input bar.

        Args:
            initial_text: Pre-populated text for the editor.
            display_name: Display name shown in the prompt context.
            history_sort_key: Launch context label propagated to spawned agents.
        """
        from ._prompt_bar_mount_markers import strip_editor_review_markers

        self._setup_home_prompt_context(
            display_name=display_name,
            history_sort_key=history_sort_key,
        )

        prompt = self._open_editor_for_agent_prompt(initial_text)  # type: ignore[attr-defined]
        if prompt:
            marked, cleaned = strip_editor_review_markers(prompt)
            if marked:
                # A ` @` review marker requests review instead of launch:
                # remount the bar with the caller's display/history context (not
                # the generic home labels) and editor-file semantics so a
                # multi-agent markdown buffer re-stacks into panes with its
                # frontmatter.
                self._show_prompt_input_bar_for_home(
                    initial_text=cleaned,
                    display_name=display_name,
                    history_sort_key=history_sort_key,
                    as_xprompt_markdown=True,
                )
            else:
                self._finish_agent_launch(prompt)  # type: ignore[attr-defined]
        else:
            if initial_text.strip():
                from ._types import current_prompt_session as _current_session

                try:
                    _session = _current_session(self)
                    _origin = (
                        _session.prompt_origin if _session is not None else "typed"
                    )
                except Exception:
                    _origin = "typed"
                if _origin != "generated":
                    from sase.history.prompt import add_or_update_prompt

                    add_or_update_prompt(
                        initial_text.strip(), cancelled=True, origin="typed"
                    )
            self.notify("No prompt from editor - cancelled", severity="warning")  # type: ignore[attr-defined]
            invalidate_prompt_session(self)
