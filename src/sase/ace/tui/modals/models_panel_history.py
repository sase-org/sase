"""Resolve Launch Control rows into alias-history entry requests.

``H`` opens :class:`~sase.ace.tui.modals.alias_history_modal.AliasHistoryModal`
for the highlighted row without rebuilding or mutating the parent panel: an
alias resolves to itself, a bucket resolves to every member alias in stable
member order, and an alias-backed launch setting resolves to its referenced
alias. Scalar settings and a concrete (non-alias) launch setting are not
aliases, so they only produce a row-specific warning toast.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.llm_provider import AliasView, BucketView

from .alias_history_modal import AliasHistoryModal
from .alias_history_state import AliasHistoryEntryRequest
from .models_panel_rows import (
    BigEpicPhaseThresholdSettingRow,
    DefaultEffortSettingRow,
    LaunchModelSettingRow,
    ModelsPanelDisplayRow,
    RunnerLimitSettingRow,
)

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


class ModelsPanelHistoryMixin(_MixinBase):
    """Open per-alias agent-run history for the highlighted row."""

    if TYPE_CHECKING:

        def _selected_row(self) -> ModelsPanelDisplayRow | None: ...

    def action_alias_history(self) -> None:
        request = self._alias_history_entry_request()
        if request is None:
            return
        self.app.push_screen(AliasHistoryModal(request))  # type: ignore[attr-defined]

    def _alias_history_entry_request(self) -> AliasHistoryEntryRequest | None:
        row = self._selected_row()
        if isinstance(row, BucketView):
            return _bucket_history_request(row)
        if isinstance(row, AliasView):
            return _alias_history_request(row)
        if isinstance(row, LaunchModelSettingRow):
            return self._launch_setting_history_request(row)
        if isinstance(
            row,
            DefaultEffortSettingRow
            | RunnerLimitSettingRow
            | BigEpicPhaseThresholdSettingRow,
        ):
            self.notify(  # type: ignore[attr-defined]
                f"{row.label} is not an alias; it has no run history.",
                severity="warning",
            )
            return None
        return None

    def _launch_setting_history_request(
        self, row: LaunchModelSettingRow
    ) -> AliasHistoryEntryRequest | None:
        alias = row.snapshot.referenced_alias
        if alias is None:
            self.notify(  # type: ignore[attr-defined]
                f"{row.label} is a concrete model, not an alias; it has no "
                "recorded alias history.",
                severity="warning",
            )
            return None
        return AliasHistoryEntryRequest(
            aliases=(alias,),
            title_label=f"@{alias} · {row.label}",
            is_user_owned=False,
            effective_provider=row.snapshot.provider,
            effective_model=row.snapshot.model,
            effective_effort=row.snapshot.effort,
        )


def _alias_history_request(view: AliasView) -> AliasHistoryEntryRequest:
    return AliasHistoryEntryRequest(
        aliases=(view.name,),
        title_label=f"@{view.name}",
        is_user_owned=view.is_user_owned,
        effective_provider=view.provider,
        effective_model=view.model,
        effective_effort=view.effort,
    )


def _bucket_history_request(bucket: BucketView) -> AliasHistoryEntryRequest:
    return AliasHistoryEntryRequest(
        aliases=tuple(member.name for member in bucket.members),
        title_label=bucket.name,
        is_user_owned=bucket.is_user_owned,
    )


__all__ = ["ModelsPanelHistoryMixin"]
