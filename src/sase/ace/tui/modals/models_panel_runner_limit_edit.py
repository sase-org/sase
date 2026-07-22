"""Persistent runner-limit planning, preview, and commit helpers."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from sase.config import (
    AppliedResult,
    ConfigEditError,
    ConfigEditOp,
    ConfigInventory,
    EditPlanResult,
    build_config_inventory,
    get_configured_max_running_agents,
    plan_config_edit,
)

from .config_commit import ConfigCommitOffer, build_config_commit_offer
from .config_edit_types import _ACCENT, _MOD_COLOR, _MUTED
from .models_panel_edit import AliasEditPreviewModal

MAX_RUNNING_AGENTS_FIELD_PATH = "max_running_agents"


@dataclass(frozen=True)
class RunnerLimitEditOutcome:
    """Successful persistent runner-limit write and its reloaded value."""

    requested_limit: int
    configured_limit: int
    applied: AppliedResult


def _plan_runner_limit_edit(
    limit: int,
    *,
    inventory: ConfigInventory | None = None,
    use_chezmoi: bool | None = None,
) -> EditPlanResult:
    """Plan an edit against the writable user-base ``sase.yml`` layer."""
    inv = inventory if inventory is not None else build_config_inventory()
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
    return plan_config_edit(
        inv,
        MAX_RUNNING_AGENTS_FIELD_PATH,
        target,
        ConfigEditOp.set_value(limit),
        use_chezmoi=use_chezmoi,
    )


def build_runner_limit_commit_offer(
    target_path: str,
) -> ConfigCommitOffer | None:
    """Build the standard tracked commit offer for a dirty written file."""
    return build_config_commit_offer(
        target_path,
        subject="chore: update max running agents",
    )


class RunnerLimitEditPreviewModal(AliasEditPreviewModal):
    """Preview and confirm one persistent ``max_running_agents`` write."""

    def __init__(self, limit: int, *, override_active: bool) -> None:
        self._limit = limit
        self._override_active = override_active
        super().__init__(
            "max running agents",
            ConfigEditOp.set_value(limit),
            path=MAX_RUNNING_AGENTS_FIELD_PATH,
        )

    def _title_text(self) -> Text:
        text = Text("Edit Max Running Agents", style="bold")
        text.append("  persistent", style=_MUTED)
        return text

    def _append_operation(self, text: Text) -> None:
        text.append("Operation\n", style="bold")
        text.append(f"  {MAX_RUNNING_AGENTS_FIELD_PATH}", style=f"bold {_ACCENT}")
        text.append("  →  ", style=_MUTED)
        text.append(str(self._limit), style="bold cyan")
        text.append("\n")

    @staticmethod
    def _append_effective(text: Text, plan: EditPlanResult) -> None:
        preview = plan.effective_preview
        text.append("\nConfigured\n", style="bold")
        before = str(preview.before) if preview.has_before else "10"
        after = str(preview.after) if preview.has_after else "10"
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
        if self._override_active:
            text.append("\nTemporary override\n", style="bold")
            text.append(
                "  remains admission-effective until it expires or is cleared\n",
                style=_MUTED,
            )
        return text

    def _plan_edit(self) -> EditPlanResult:
        return _plan_runner_limit_edit(self._limit)

    def _build_outcome(self, applied: AppliedResult) -> object:
        return RunnerLimitEditOutcome(
            requested_limit=self._limit,
            configured_limit=get_configured_max_running_agents(),
            applied=applied,
        )


__all__ = [
    "MAX_RUNNING_AGENTS_FIELD_PATH",
    "RunnerLimitEditOutcome",
    "RunnerLimitEditPreviewModal",
    "build_runner_limit_commit_offer",
]
