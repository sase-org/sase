"""Persistent default-effort edit planning, preview, and commit helpers."""

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
    plan_config_edit,
)

from .config_commit import ConfigCommitOffer, build_config_commit_offer
from .config_edit_types import _ACCENT, _MOD_COLOR, _MUTED, _OK_COLOR
from .models_panel_edit import AliasEditPreviewModal

DEFAULT_EFFORT_FIELD_PATH = "llm_provider.default_effort"


@dataclass(frozen=True)
class DefaultEffortEditOutcome:
    """Successful persistent default-effort write."""

    effort: str | None
    applied: AppliedResult


def _plan_default_effort_edit(
    effort: str | None,
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
    # The schema's empty string is the explicit provider-default sentinel.  A
    # set (rather than unset) masks lower-precedence package/plugin values.
    op = ConfigEditOp.set_value(effort or "")
    return plan_config_edit(
        inv,
        DEFAULT_EFFORT_FIELD_PATH,
        target,
        op,
        use_chezmoi=use_chezmoi,
    )


def build_default_effort_commit_offer(
    target_path: str,
) -> ConfigCommitOffer | None:
    """Build the standard tracked commit offer for a dirty written file."""
    return build_config_commit_offer(
        target_path,
        subject="chore: update default model effort",
    )


class DefaultEffortEditPreviewModal(AliasEditPreviewModal):
    """Preview and confirm one persistent ``default_effort`` scalar write."""

    def __init__(self, effort: str | None, *, override_active: bool) -> None:
        self._effort = effort
        self._override_active = override_active
        super().__init__(
            "default effort",
            ConfigEditOp.set_value(effort or ""),
            path=DEFAULT_EFFORT_FIELD_PATH,
        )

    def _title_text(self) -> Text:
        text = Text("Edit Default Effort", style="bold")
        text.append("  persistent", style=_MUTED)
        return text

    def _append_operation(self, text: Text) -> None:
        text.append("Operation\n", style="bold")
        text.append(f"  {DEFAULT_EFFORT_FIELD_PATH}", style=f"bold {_ACCENT}")
        text.append("  →  ", style=_MUTED)
        text.append(
            self._effort or "provider default",
            style=f"bold {_OK_COLOR}",
        )
        text.append("\n")

    @staticmethod
    def _append_effective(text: Text, plan: EditPlanResult) -> None:
        preview = plan.effective_preview
        text.append("\nConfigured\n", style="bold")
        before = _format_effort(preview.has_before, preview.before)
        after = _format_effort(preview.has_after, preview.after)
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
                "  remains launch-effective until it expires or is cleared\n",
                style=_MUTED,
            )
        return text

    def _plan_edit(self) -> EditPlanResult:
        return _plan_default_effort_edit(self._effort)

    def _build_outcome(self, applied: AppliedResult) -> object:
        return DefaultEffortEditOutcome(effort=self._effort, applied=applied)


def _format_effort(has_value: bool, value: object) -> str:
    if not has_value or value in (None, ""):
        return "provider default"
    return f"@ {value}"


__all__ = [
    "DEFAULT_EFFORT_FIELD_PATH",
    "DefaultEffortEditOutcome",
    "DefaultEffortEditPreviewModal",
    "build_default_effort_commit_offer",
]
