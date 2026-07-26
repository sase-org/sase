"""Prompt stack local-xprompt conversion actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets._local_xprompt_conversion import (
    build_local_xprompt,
    infer_local_xprompt_inputs,
    local_xprompt_invocation_skeleton,
)
from sase.xprompt.prompt_frontmatter import PromptFrontmatter

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.widgets.prompt_stack import PromptStackState
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
    from sase.xprompt.models import InputArg, XPrompt
else:
    _MixinBase = object


class PromptInputBarLocalXPromptActionsMixin(_MixinBase):
    """Prompt pane conversion to frontmatter-local xprompts."""

    if TYPE_CHECKING:
        _mode: str
        _stack: PromptStackState

        def _clear_active_completion_state(self) -> None: ...
        def _schedule_height_update(self) -> None: ...
        def _sync_state_from_widgets(self) -> None: ...
        def active_text_area(self) -> PromptTextArea: ...
        def local_xprompts(self) -> dict[str, XPrompt]: ...
        def refresh_frontmatter_panel_from_stack(self) -> None: ...

    def convert_active_pane_to_local_xprompt(
        self, *, target_mode: str = "normal"
    ) -> None:
        """Convert the active pane into a local xprompt (the ``gX`` keymap).

        Prompt mode only.  Captures the active pane's body, infers its inputs
        from undeclared Jinja variables, opens a prefilled ghost row, and on a
        valid name stores the body as a local ``xprompts:`` helper in the bar's
        shared frontmatter and rewrites the pane into an invocation of it.  A
        blank pane or invalid Jinja in the body leaves everything unchanged and
        notifies; cancelling or naming a duplicate is a no-op too.

        ``target_mode`` is the mode the rewritten pane should end in for a
        no-argument invocation (``Ctrl+G X`` from INSERT keeps INSERT); an
        invocation with generated argument slots always lands in INSERT so the
        user can fill them straight away.
        """
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        body = self._stack.selected_item.text.strip()
        if not body:
            self.app.notify(
                "Active prompt pane is empty — nothing to save.",
                severity="warning",
            )
            return
        conversion = infer_local_xprompt_inputs(body)
        if conversion is None:
            self.app.notify(
                "Active pane has invalid Jinja — fix it before saving as a "
                "local xprompt.",
                severity="warning",
            )
            return
        self._clear_active_completion_state()
        panel = self._frontmatter_panel()  # type: ignore[attr-defined]
        if panel is None:
            return
        self._show_frontmatter_panel(focus=False)  # type: ignore[attr-defined]
        xprompt = build_local_xprompt(
            "_",
            conversion.body,
            conversion.inputs,
        )

        def _on_commit(saved: XPrompt) -> None:
            skeleton = local_xprompt_invocation_skeleton(saved)
            enter_insert = bool(saved.inputs) or target_mode == "insert"
            self._replace_active_pane_with_skeleton(skeleton, enter_insert=enter_insert)

        panel.begin_prefilled_xprompt("xprompts", xprompt, on_commit=_on_commit)

    def _store_local_xprompt_and_replace_pane(
        self,
        name: str,
        body: str,
        inputs: list[InputArg],
        *,
        target_mode: str,
    ) -> None:
        """Persist the new local xprompt and rewrite the active pane to invoke it.

        The helper is merged into the shared frontmatter (so any pane can
        reference it) and the active pane's whole body is replaced with the
        invocation skeleton expanded through the snippet engine.
        """
        xprompt = build_local_xprompt(name, body, inputs)
        try:
            model = PromptFrontmatter.parse(self._stack.frontmatter)
        except Exception:
            model = PromptFrontmatter()
        model.set_xprompt(xprompt)
        self._stack.set_frontmatter_model(model)
        self.refresh_frontmatter_panel_from_stack()

        skeleton = local_xprompt_invocation_skeleton(xprompt)
        enter_insert = bool(inputs) or target_mode == "insert"
        self._replace_active_pane_with_skeleton(skeleton, enter_insert=enter_insert)

    def _replace_active_pane_with_skeleton(
        self, skeleton: str, *, enter_insert: bool
    ) -> None:
        """Replace the active pane's whole body with an expanded snippet skeleton.

        The snippet engine edits through the keyboard path, which is inert while
        the pane is read-only (NORMAL mode), so the pane is switched to INSERT
        first; a skeleton carrying argument tabstops stays in INSERT (dropping to
        NORMAL would discard the pending tabstops), while a bare ``#_name``
        invocation honors *enter_insert* to preserve the caller's target mode.
        """
        try:
            text_area = self.active_text_area()
        except Exception:
            return
        text_area.focus()
        text_area._enter_insert_mode()
        document = text_area.document
        last_row = document.line_count - 1
        end = (last_row, len(document.get_line(last_row)))
        text_area._expand_snippet_template_at_range(skeleton, (0, 0), end)
        if not enter_insert:
            text_area._enter_normal_mode()
        text_area.focus()
        self._sync_state_from_widgets()
        self._schedule_height_update()
