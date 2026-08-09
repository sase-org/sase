"""Lightweight shared types for project selection modals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class SelectionItem:
    """An item that can be selected in the modal."""

    display_name: str
    item_type: Literal["project", "cl", "home", "all"]
    project_name: str
    cl_name: str | None
    project_label: str | None = None
    selection_label: str | None = None

    @property
    def option_id(self) -> str:
        """Return a canonical identity for the interactive option row."""
        if self.item_type == "cl":
            return f"cl:{self.project_name}:{self.cl_name or ''}"
        return f"{self.item_type}:{self.project_name}"


@dataclass
class ProjectSelectResult:
    """Result from the project selection modal."""

    selection: SelectionItem | str
    open_in_editor: bool = False


__all__ = ["ProjectSelectResult", "SelectionItem"]
