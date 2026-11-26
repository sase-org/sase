"""Clipboard and copy-panel behavior for the user-question modal."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.core.question_copy_facade import (
    QuestionCopyDisplay,
    display_question_copy_items,
)

from ..actions.clipboard import schedule_copy_delivery
from ..actions.clipboard._delivery import CopyDeliveryOutcome
from .copy_as_types import CopyAsRow
from .question_copy_items import (
    QuestionCopySnapshot,
    build_question_copy_context,
    toast_label_for_target,
)
from .question_pane_cues import (
    build_also_copyable_text,
    build_copy_border_subtitle,
    build_question_prose_text,
    missing_copy_items,
    pane_keys_for_items,
)
from .question_copy_modal import QuestionCopyModal

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


class UserQuestionCopyingMixin(_MixinBase):
    """Open the copy panel and dispatch its rows through ordered delivery."""

    if TYPE_CHECKING:
        _questions: list[dict[str, Any]]
        _current_idx: int
        _input_mode: str | None
        _copy_bundle_key: str | None
        _local_copied_texts: set[str]

        def _save_current_answer(self) -> None: ...
        def _build_qa_markdown(self, include_copy_items: bool = ...) -> str: ...

    def _question_copy_bundle_key(self) -> str | None:
        """Return the progress-map key for this modal, if any."""
        return getattr(self, "_copy_bundle_key", None)

    def _question_copied_texts(self) -> set[str]:
        """Return the live copied-text set for this question bundle."""
        key = self._question_copy_bundle_key()
        if key is None:
            local = getattr(self, "_local_copied_texts", None)
            if local is None:
                local = set()
                self._local_copied_texts = local  # type: ignore[attr-defined]
            return local
        try:
            app = self.app  # type: ignore[attr-defined]
        except Exception:
            return set()
        progress = getattr(app, "_question_copy_progress", None)
        if progress is None:
            progress = {}
            try:
                app._question_copy_progress = progress  # type: ignore[attr-defined]
            except Exception:
                return set()
        texts = progress.get(key)
        if texts is None:
            texts = set()
            progress[key] = texts
        return texts

    def _mark_question_copied(self, texts: set[str]) -> None:
        """Record copied snippet texts for this question bundle."""
        if not texts:
            return
        key = self._question_copy_bundle_key()
        if key is None:
            local = self._question_copied_texts()
            local.update(texts)
        else:
            self._question_copied_texts().update(texts)
        self._refresh_question_pane_cues()

    def _refresh_question_pane_cues(self) -> None:
        """Rebuild the prose underlines, also-copyable block, and subtitle.

        Every widget lookup is guarded so progress callbacks on a dismissed
        modal stay silent no-ops.
        """
        try:
            questions = self._questions
            idx = self._current_idx
        except AttributeError:
            return
        if not 0 <= idx < len(questions):
            return
        question = questions[idx]
        question_text = question.get("question", "") or ""
        try:
            display = display_question_copy_items(question)
        except Exception:
            return
        copied = self._question_copied_texts()
        try:
            from textual.containers import VerticalScroll
            from textual.widgets import Static

            prose = build_question_prose_text(
                question_text, display.items, frozenset(copied)
            )
            self.query_one("#user-question-text", Static).update(prose)  # type: ignore[attr-defined]
            keys = pane_keys_for_items(len(display.items))
            missing = tuple(
                (key, item)
                for key, item in zip(keys, display.items, strict=True)
                if item.text not in question_text
            )
            also = self.query_one("#user-question-also-copyable", Static)  # type: ignore[attr-defined]
            if missing:
                also.update(build_also_copyable_text(missing))
                also.remove_class("hidden")
            else:
                also.update("")
                also.add_class("hidden")
            total = len(display.items)
            copied_count = sum(1 for item in display.items if item.text in copied)
            scroll = self.query_one("#user-question-text-scroll", VerticalScroll)  # type: ignore[attr-defined]
            scroll.border_subtitle = build_copy_border_subtitle(
                total, copied_count, display.unavailable
            )
        except Exception:
            return

    def _highlighted_question_option(self) -> tuple[str | None, str | None, bool]:
        """Return ``(label, description, is_other)`` for the highlighted option."""
        try:
            from textual.widgets import SelectionList

            sel_list = self.query_one("#user-question-options", SelectionList)  # type: ignore[attr-defined]
        except Exception:
            return None, None, False
        try:
            highlighted = sel_list.highlighted
        except Exception:
            highlighted = None
        if highlighted is None:
            return None, None, False
        try:
            option = sel_list.get_option_at_index(highlighted)
        except Exception:
            return None, None, False
        value = getattr(option, "value", None)
        if value == "__other__":
            return None, None, True
        if not isinstance(value, str):
            return None, None, False
        question = self._questions[self._current_idx]
        for opt in question.get("options", []):
            if opt.get("label") == value:
                desc = opt.get("description") or None
                return value, desc, False
        return value, None, False

    def _build_question_copy_snapshot(self) -> QuestionCopySnapshot:
        """Capture everything the copy panel needs for the current question."""
        question = self._questions[self._current_idx]
        display: QuestionCopyDisplay = display_question_copy_items(question)
        label, desc, is_other = self._highlighted_question_option()
        qa_value = self._build_qa_markdown(include_copy_items=True)
        return QuestionCopySnapshot(
            question_index=self._current_idx,
            total_questions=len(self._questions),
            header=question.get("header", "") or "",
            question_text=question.get("question", "") or "",
            highlighted_label=label,
            highlighted_description=desc,
            highlighted_is_other=is_other,
            has_options=bool(question.get("options")),
            items=display.items,
            unavailable=display.unavailable,
            copied_texts=frozenset(self._question_copied_texts()),
            qa_value=qa_value,
        )

    def action_open_copy_panel(self) -> None:
        """Open the copy-from-question panel for the current question."""
        if getattr(self, "_input_mode", None):
            return
        try:
            app = self.app  # type: ignore[attr-defined]
            if bool(getattr(app, "_copy_mode_active", False)):
                return
        except Exception:
            pass
        self._save_current_answer()
        snapshot = self._build_question_copy_snapshot()
        context = build_question_copy_context(snapshot)

        def on_dismiss(row: CopyAsRow | None) -> None:
            if row is None:
                return
            if row.disabled_reason is not None:
                self.notify(row.disabled_reason, severity="warning")
                return
            self._dispatch_question_copy_row(row, snapshot)

        try:
            self.app.push_screen(QuestionCopyModal(context), callback=on_dismiss)  # type: ignore[attr-defined]
        except Exception:
            return

    def _dispatch_question_copy_row(
        self, row: CopyAsRow, snapshot: QuestionCopySnapshot
    ) -> None:
        """Copy one dismissed panel row through the ordered delivery seam."""
        value = row.value if row.value is not None else row.preview
        label = toast_label_for_target(row.target, snapshot, row)
        task = schedule_copy_delivery(
            self,
            value,
            copied_label=label,
            task_name="sase-copy-question-panel",
            ordered=True,
        )
        if task is None:
            return

        if row.target.startswith("snippet:"):
            marked = {row.target[len("snippet:") :]}
        elif row.target == "all":
            marked = {item.text for item in snapshot.items}
        else:
            return

        def _mark_outcome(completed: Any) -> None:
            try:
                outcome = completed.result()
            except Exception:
                return
            if outcome is not CopyDeliveryOutcome.VERIFIED and (
                outcome is not CopyDeliveryOutcome.OSC52_ONLY
            ):
                return
            try:
                mounted = self.is_mounted  # type: ignore[attr-defined]
            except Exception:
                mounted = True
            if not mounted:
                return
            self._mark_question_copied(marked)

        try:
            task.add_done_callback(_mark_outcome)
        except Exception:
            pass


__all__ = ["UserQuestionCopyingMixin"]
