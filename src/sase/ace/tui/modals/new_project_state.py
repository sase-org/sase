"""Small state machine for the New Project wizard stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from typing import TYPE_CHECKING

from .new_project_source_model import SourceRow

if TYPE_CHECKING:
    from .new_project_configure_model import ConfigureDraft

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
    draft: ConfigureDraft | None = None

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

    def set_draft(self, draft: ConfigureDraft | None) -> None:
        """Replace the editable draft; transitions never drop it implicitly."""
        self.draft = draft

    def to_configure(self) -> None:
        """Move to Configure, keeping the draft seeded from the source row."""
        self.stage = "configure"

    def to_review(self) -> None:
        """Advance a valid draft to Review."""
        self.stage = "review"

    def back_to_configure(self) -> None:
        """Return from Review to Configure with the draft intact."""
        self.stage = "configure"

    def to_progress(self) -> None:
        """Start applying a confirmed review."""
        self.stage = "progress"

    def finish_ready(self) -> None:
        """Finish Progress on Ready."""
        self.stage = "ready"

    def finish_failed(self) -> None:
        """Finish Progress on Failed, keeping the checklist and draft."""
        self.stage = "failed"

    def back_to_review(self) -> None:
        """Return from Failed to Review with the last plan and draft."""
        self.stage = "review"

    def replan(self) -> None:
        """Return from Failed to Review to run the check again."""
        self.stage = "review"

    def set_stage(self, stage: NewProjectStage) -> None:
        """Move to a later wizard stage."""
        self.stage = stage


__all__ = ["NewProjectStage", "NewProjectStateMachine", "SourceOutcome"]
