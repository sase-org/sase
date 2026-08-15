"""Persistent big-epic threshold planning, preview, and commit helpers."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from sase.bead.config import (
    DEFAULT_BIG_EPIC_PHASE_THRESHOLD,
    get_big_epic_phase_threshold,
)
from sase.config import (
    AppliedResult,
    ConfigEditError,
    ConfigEditOp,
    ConfigInventory,
    EditPlanResult,
    build_config_inventory,
    plan_config_edit,
)

from .config_commit import ConfigCommitOffer, build_config_commit_offer
from .config_edit_types import _ACCENT, _MOD_COLOR, _MUTED
from .models_panel_edit import AliasEditPreviewModal
from .models_panel_rendering import format_phase_threshold

BIG_EPIC_PHASE_THRESHOLD_FIELD_PATH = "bead.big_epic_phase_threshold"


@dataclass(frozen=True)
class BigEpicPhaseThresholdEditOutcome:
    """Successful persistent threshold write and its reloaded effective value."""

    requested_threshold: int | None
    effective_threshold: int
    applied: AppliedResult


def _writable_user_base(inv: ConfigInventory) -> str:
    target = next(
        (
            source.name
            for source in inv.sources
            if source.name == "user" and source.writable
        ),
        None,
    )
    if target is None:
        raise ConfigEditError("no writable user base config layer available")
    return target


def _plan_big_epic_phase_threshold_edit(
    op: ConfigEditOp,
    *,
    inventory: ConfigInventory | None = None,
    use_chezmoi: bool | None = None,
) -> EditPlanResult:
    """Plan an edit against the writable user-base ``sase.yml`` layer."""
    inv = inventory if inventory is not None else build_config_inventory()
    return plan_config_edit(
        inv,
        BIG_EPIC_PHASE_THRESHOLD_FIELD_PATH,
        _writable_user_base(inv),
        op,
        use_chezmoi=use_chezmoi,
    )


def build_big_epic_phase_threshold_commit_offer(
    target_path: str,
) -> ConfigCommitOffer | None:
    """Build the standard tracked commit offer for a dirty written file."""
    return build_config_commit_offer(
        target_path,
        subject="chore: update big epic phase threshold",
    )


class BigEpicPhaseThresholdEditPreviewModal(AliasEditPreviewModal):
    """Preview and confirm one persistent ``big_epic_phase_threshold`` write."""

    def __init__(self, threshold: int | None, *, reset: bool = False) -> None:
        self._threshold = threshold
        self._reset = reset
        super().__init__(
            "big epic starts at",
            ConfigEditOp.unset() if reset else ConfigEditOp.set_value(threshold),
            path=BIG_EPIC_PHASE_THRESHOLD_FIELD_PATH,
            action_label="Reset" if reset else "Edit",
            target_kind="Launch Setting",
            target_label="big epic starts at",
        )

    def _title_text(self) -> Text:
        label = "Reset" if self._reset else "Edit"
        text = Text(f"{label} Big Epic Threshold", style="bold")
        text.append("  persistent", style=_MUTED)
        return text

    def _append_operation(self, text: Text) -> None:
        text.append("Operation\n", style="bold")
        text.append(
            f"  {BIG_EPIC_PHASE_THRESHOLD_FIELD_PATH}",
            style=f"bold {_ACCENT}",
        )
        if self._reset:
            text.append("  reset", style=f"bold {_MOD_COLOR}")
            text.append("  (removes the configured key)\n", style=_MUTED)
            return
        text.append("  →  ", style=_MUTED)
        assert self._threshold is not None
        text.append(format_phase_threshold(self._threshold), style="bold cyan")
        text.append("\n")

    @staticmethod
    def _append_effective(text: Text, plan: EditPlanResult) -> None:
        preview = plan.effective_preview
        text.append("\nEffective Threshold\n", style="bold")
        before = _format_threshold(preview.has_before, preview.before)
        after = _format_threshold(preview.has_after, preview.after)
        text.append("  ")
        text.append(before, style=_MUTED)
        text.append("  →  ", style=_MUTED)
        text.append(
            after,
            style=f"bold {_MOD_COLOR if preview.changed else _MUTED}",
        )
        text.append("\n")

    def _preview_text(self, plan: EditPlanResult) -> Text:
        text = super()._preview_text(plan)
        text.append("\nBoundary\n", style="bold")
        text.append(
            "  epics at or above this authored phase count use the big epic lander\n",
            style=_MUTED,
        )
        return text

    def _plan_edit(self) -> EditPlanResult:
        op = (
            ConfigEditOp.unset()
            if self._reset
            else ConfigEditOp.set_value(self._threshold)
        )
        return _plan_big_epic_phase_threshold_edit(op)

    def _build_outcome(self, applied: AppliedResult) -> object:
        return BigEpicPhaseThresholdEditOutcome(
            requested_threshold=None if self._reset else self._threshold,
            effective_threshold=get_big_epic_phase_threshold(),
            applied=applied,
        )


def _format_threshold(has_value: bool, value: object) -> str:
    if not has_value:
        return format_phase_threshold(DEFAULT_BIG_EPIC_PHASE_THRESHOLD)
    if isinstance(value, int):
        threshold = value
    elif isinstance(value, str):
        try:
            threshold = int(value, 10)
        except ValueError:
            return value
    else:
        return str(value)
    return format_phase_threshold(threshold)


__all__ = [
    "BIG_EPIC_PHASE_THRESHOLD_FIELD_PATH",
    "BigEpicPhaseThresholdEditOutcome",
    "BigEpicPhaseThresholdEditPreviewModal",
    "_plan_big_epic_phase_threshold_edit",
    "build_big_epic_phase_threshold_commit_offer",
]
