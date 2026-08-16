"""Result and error types for plan-file bead work."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

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
class _EpicLaunchResultView:
    """Plan-file view of an epic launch result or legacy boolean test double."""

    launched: bool
    launch_state: str
    launched_agent_names: tuple[str, ...] = ()
    preserved_agent_names: tuple[str, ...] = ()
    workspace_num: int | None = None


class _StructuredEpicLaunchResult(Protocol):
    launched: bool
    launch_state: str
    launched_agent_names: tuple[str, ...]
    preserved_agent_names: tuple[str, ...]
    workspace_num: int | None


def normalize_epic_launch_result(
    result: object,
    *,
    fallback_launched_agent_names: tuple[str, ...],
) -> _EpicLaunchResultView:
    """Adapt structured epic launch results and legacy boolean callers."""
    if isinstance(result, bool):
        return _EpicLaunchResultView(
            launched=result,
            launch_state="launched" if result else "declined",
            launched_agent_names=fallback_launched_agent_names if result else (),
        )
    structured = cast(_StructuredEpicLaunchResult, result)
    launched = bool(structured.launched)
    return _EpicLaunchResultView(
        launched=launched,
        launch_state=structured.launch_state,
        launched_agent_names=tuple(structured.launched_agent_names),
        preserved_agent_names=tuple(structured.preserved_agent_names),
        workspace_num=structured.workspace_num,
    )


@dataclass(frozen=True)
class PlanFileWorkResult:
    """Stable result envelope for human and JSON callers."""

    archived_plan_path: Path
    authored_phase_ids: tuple[str, ...]
    dry_run: bool
    epic_id: str | None = None
    parent_id: str | None = None
    preview_epic_id: str | None = None
    replaced_stale_epic_id: str | None = None
    phase_bead_ids: tuple[str, ...] = ()
    launched_agent_names: tuple[str, ...] = ()
    preserved_agent_names: tuple[str, ...] = ()
    launch_state: str = ""
    launched: bool = False
    resumed: bool = False
    waves: tuple[tuple[str, ...], ...] = ()

    def to_json(self) -> dict[str, object]:
        return {
            "ok": True,
            "mode": "plan_file",
            "dry_run": self.dry_run,
            "epic_id": self.epic_id,
            "parent_id": self.parent_id,
            "preview_epic_id": self.preview_epic_id,
            "replaced_stale_epic_id": self.replaced_stale_epic_id,
            "phase_bead_ids": list(self.phase_bead_ids),
            "authored_phase_ids": list(self.authored_phase_ids),
            "archived_plan_path": str(self.archived_plan_path),
            "launched_agent_names": list(self.launched_agent_names),
            "preserved_agent_names": list(self.preserved_agent_names),
            "launch_state": self.launch_state,
            "launched": self.launched,
            "resumed": self.resumed,
            "waves": [list(wave) for wave in self.waves],
        }
