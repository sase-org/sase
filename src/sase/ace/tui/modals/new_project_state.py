"""Small state machine for the New Project wizard stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from typing import TYPE_CHECKING

from .new_project_source_model import SourceRow

if TYPE_CHECKING:
    from .new_project_configure_model import ConfigureDraft
    from .new_project_create import CreateDraft

NewProjectStage = Literal[
    "source",
    "configure",
    "create-configure",
    "review",
    "progress",
    "ready",
    "failed",
]
SourceOutcome = Literal["configure", "show-project", "jump-resume", "resume", "create"]
WizardMode = Literal["add", "create"]


@dataclass
class NewProjectStateMachine:
    """Track the current wizard stage and the source selected to configure."""

    stage: NewProjectStage = "source"
    workflow_type: str = ""
    selected: SourceRow | None = None
    draft: ConfigureDraft | None = None
    wizard_mode: WizardMode = "add"
    create_draft: CreateDraft | None = None

    def select_source(self, row: SourceRow) -> SourceOutcome:
        """Choose a source row, preserving its specialized hand-off behavior."""
        self.selected = row
        if row.group == "create":
            return "create"
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

    def set_create_draft(self, draft: CreateDraft | None) -> None:
        """Replace the editable create draft; add drafts stay intact."""
        self.create_draft = draft

    def to_create_configure(self, draft: CreateDraft) -> None:
        """Move to create Configure, keeping the per-owner create draft."""
        self.wizard_mode = "create"
        self.create_draft = draft
        self.stage = "create-configure"

    def to_add_configure(self) -> None:
        """Return to existing-repo Configure after an explicit add-instead."""
        self.wizard_mode = "add"
        self.stage = "configure"

    def to_configure(self) -> None:
        """Move to Configure, keeping the draft seeded from the source row."""
        self.stage = "configure"

    def to_review(self) -> None:
        """Advance a valid draft to Review."""
        self.stage = "review"

    def back_to_configure(self) -> None:
        """Return from Review to the matching Configure stage."""
        self.stage = "create-configure" if self.wizard_mode == "create" else "configure"

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


__all__ = [
    "NewProjectStage",
    "NewProjectStateMachine",
    "SourceOutcome",
    "WizardMode",
]
