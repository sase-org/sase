"""Small state machine for the New Project wizard stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .new_project_source_model import SourceRow

NewProjectStage = Literal[
    "source", "configure", "review", "progress", "ready", "failed"
]
SourceOutcome = Literal["configure", "show-project", "jump-resume", "resume"]


@dataclass
class NewProjectStateMachine:
    """Track the current wizard stage and the source selected to configure."""

    stage: NewProjectStage = "source"
    workflow_type: str = ""
    selected: SourceRow | None = None

    def select_source(self, row: SourceRow) -> SourceOutcome:
        """Choose a source row, preserving its specialized hand-off behavior."""
        self.selected = row
        if row.group == "search_only" and row.hidden_reason == "enabled_project":
            return "show-project"
        if row.group == "resume":
            status = str(row.data.get("status") or row.data.get("journal_status") or "")
            if status == "running":
                return "jump-resume"
            self.stage = "review"
            return "resume"
        self.stage = "configure"
        return "configure"

    def back_to_source(self) -> None:
        """Return to Source without dropping the selected row or provider."""
        self.stage = "source"

    def set_stage(self, stage: NewProjectStage) -> None:
        """Move to a later wizard stage."""
        self.stage = stage


__all__ = ["NewProjectStage", "NewProjectStateMachine", "SourceOutcome"]
