"""Typed wizard result for the New Project modal."""

from __future__ import annotations

from .new_project_source_model import SourceRow


class NewProjectSelection:
    """Typed result for source rows and Ready outcomes that leave the wizard."""

    def __init__(
        self,
        outcome: str,
        workflow_type: str = "",
        row: SourceRow | None = None,
        project_key: str = "",
        operation_id: str = "",
    ) -> None:
        self.outcome = outcome
        self.workflow_type = workflow_type
        self.row = row
        self.project_key = project_key
        self.operation_id = operation_id


__all__ = ["NewProjectSelection"]
