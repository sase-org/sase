"""Delete handlers for durable manual prompt completion entries."""

from __future__ import annotations

from sase.ace.tui.widgets._file_completion_accept_kinds import (
    FileCompletionAcceptKindsMixin,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
    HistoryWordCompletionPlaceholder,
)
from sase.ace.tui.widgets.placeholder_completion import (
    PLACEHOLDER_COMPLETION_KIND,
    PlaceholderCompletionMetadata,
)


class FileCompletionAcceptDeleteMixin(FileCompletionAcceptKindsMixin):
    """Mixin providing deletion of durable completion entries."""

    def _delete_selected_file_completion(self) -> bool:
        """Delete the highlighted durable completion entry."""
        if (
            not self._file_completion_active
            or not self._file_completion_candidates
            or not self._completion_supports_delete()
        ):
            return False

        idx = self._file_completion_index
        if idx >= len(self._file_completion_candidates):
            return False
        selected = self._file_completion_candidates[idx]

        if self._completion_kind == "file_history":
            return self._delete_selected_file_history_completion(idx, selected)
        if self._completion_kind == HISTORY_WORD_COMPLETION_KIND:
            return self._delete_selected_history_word_completion(idx, selected)
        if self._completion_kind == PLACEHOLDER_COMPLETION_KIND:
            return self._delete_selected_placeholder_completion(idx, selected)
        return False

    def _completion_supports_delete(self) -> bool:
        """Return whether the active completion kind handles ``Ctrl+D``."""
        return self._completion_kind in {
            "file_history",
            HISTORY_WORD_COMPLETION_KIND,
            PLACEHOLDER_COMPLETION_KIND,
        }

    def _delete_selected_file_history_completion(
        self,
        idx: int,
        selected: CompletionCandidate,
    ) -> bool:
        """Delete one recent-file completion synchronously."""
        from sase.history.file_references import remove_file_reference

        victim = selected.insertion
        remove_file_reference(victim)
        self._remove_completion_candidate_locally(idx)
        self._notify_completion_delete(f"Deleted recent file: {victim}")
        return True

    def _delete_selected_history_word_completion(
        self,
        idx: int,
        selected: CompletionCandidate,
    ) -> bool:
        """Optimistically suppress one prompt-history word."""
        if isinstance(selected.metadata, HistoryWordCompletionPlaceholder):
            return False

        from sase.ace.tui.util.io_async import schedule_persist
        from sase.history.prompt_word_deletions import delete_prompt_word

        word = selected.name
        forget = getattr(self.app, "forget_history_prompt_word", None)
        if callable(forget):
            forget(word)
        else:
            self._remove_completion_candidate_locally(idx)
        self._notify_completion_delete(f"Deleted history word: {word}")

        warm = getattr(self.app, "warm_history_prompt_words", None)
        schedule_persist(
            self.app,
            delete_prompt_word,
            word,
            error_label="Deleting history word",
            on_error=(lambda _exc: warm()) if callable(warm) else None,
        )
        return True

    def _delete_selected_placeholder_completion(
        self,
        idx: int,
        selected: CompletionCandidate,
    ) -> bool:
        """Optimistically remove one saved common placeholder."""
        metadata = selected.metadata
        if not (
            isinstance(metadata, PlaceholderCompletionMetadata)
            and metadata.source == "common"
        ):
            self._notify_completion_delete(
                "This placeholder comes from the current prompt, not the saved list"
            )
            return True

        from sase.ace.tui.util.io_async import schedule_persist
        from sase.history.prompt_placeholders import remove_common_placeholder

        text = selected.insertion
        forget = getattr(self.app, "forget_common_placeholder", None)
        if callable(forget):
            forget(text)
        else:
            self._remove_completion_candidate_locally(idx)
        self._notify_completion_delete(f"Deleted saved placeholder: <{text}>")

        warm = getattr(self.app, "warm_common_placeholders", None)
        schedule_persist(
            self.app,
            remove_common_placeholder,
            text,
            error_label="Deleting saved placeholder",
            on_error=(lambda _exc: warm()) if callable(warm) else None,
        )
        return True

    def _remove_completion_candidate_locally(self, idx: int) -> None:
        """Remove one row and repaint when no app-level cache hook exists."""
        del self._file_completion_candidates[idx]
        if not self._file_completion_candidates:
            self._clear_file_completion()
            return
        self._file_completion_index = min(
            idx, len(self._file_completion_candidates) - 1
        )
        self._update_file_completion_panel("")

    def _notify_completion_delete(self, message: str) -> None:
        """Show an informational deletion toast without risking the action."""
        try:
            self.app.notify(message, severity="information", markup=False)
        except Exception:
            pass
