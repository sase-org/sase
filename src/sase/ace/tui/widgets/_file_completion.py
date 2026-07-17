"""Manual completion mixin for PromptTextArea."""

from __future__ import annotations

from sase.ace.tui.widgets._file_completion_open import FileCompletionOpenMixin


class FileCompletionMixin(FileCompletionOpenMixin):
    """Mixin providing manual completion for PromptTextArea.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """
