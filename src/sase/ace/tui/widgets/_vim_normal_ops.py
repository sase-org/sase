"""Vim normal-mode operator execution and state management helpers."""

from __future__ import annotations

from sase.ace.tui.widgets._vim_normal_operator_exec import (
    VimNormalOperatorExecutionMixin,
)


class VimNormalOpsMixin(VimNormalOperatorExecutionMixin):
    """Compatibility facade for vim normal-mode operation helpers.

    Mixed into :class:`VimNormalModeMixin` which is then mixed into
    :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """


__all__ = ["VimNormalOpsMixin"]
