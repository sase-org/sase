"""Result and error types for plan-file bead work."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.sdd.plan_validate import PlanValidationResult


class PlanFileWorkError(RuntimeError):
    """A recoverable plan-file launch failure with an optional resume command."""

    def __init__(
        self,
        message: str,
        *,
        resume_command: str | None = None,
        validation: PlanValidationResult | None = None,
    ) -> None:
        super().__init__(message)
        self.resume_command = resume_command
        self.validation = validation


@dataclass(frozen=True)
class PlanFileWorkResult:
    """Stable result envelope for human and JSON callers."""

    archived_plan_path: Path
    authored_phase_ids: tuple[str, ...]
    dry_run: bool
    epic_id: str | None = None
    phase_bead_ids: tuple[str, ...] = ()
    launched_agent_names: tuple[str, ...] = ()
    launched: bool = False
    resumed: bool = False
    waves: tuple[tuple[str, ...], ...] = ()

    def to_json(self) -> dict[str, object]:
        return {
            "ok": True,
            "mode": "plan_file",
            "dry_run": self.dry_run,
            "epic_id": self.epic_id,
            "phase_bead_ids": list(self.phase_bead_ids),
            "authored_phase_ids": list(self.authored_phase_ids),
            "archived_plan_path": str(self.archived_plan_path),
            "launched_agent_names": list(self.launched_agent_names),
            "launched": self.launched,
            "resumed": self.resumed,
            "waves": [list(wave) for wave in self.waves],
        }
