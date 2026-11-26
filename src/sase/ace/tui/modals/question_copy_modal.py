"""Thin palette subclass for the question copy panel."""

from __future__ import annotations

from .copy_as_modal import CopyAsModal
from .copy_as_types import CopyAsContext, CopyAsRow


class QuestionCopyModal(CopyAsModal):
    """Copy-from-question palette with its own width and catalog entry."""

    def __init__(self, context: CopyAsContext) -> None:
        super().__init__(context)


__all__ = ["QuestionCopyModal", "CopyAsRow", "CopyAsContext"]
