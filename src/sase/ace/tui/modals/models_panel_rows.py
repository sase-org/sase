"""Typed row snapshots for the ACE Models panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.config import EffectiveRunnerLimitSnapshot
from sase.bead.config import DEFAULT_BIG_EPIC_PHASE_THRESHOLD
from sase.llm_provider import AliasView, BucketView, EffectiveDefaultEffortSnapshot
from sase.llm_provider.config import (
    BIG_EPIC_LANDER_MODEL_FIELD,
    DEFAULT_MODEL_FIELD,
    EPIC_LANDER_MODEL_FIELD,
    LaunchModelSettingSnapshot,
    build_launch_model_setting_snapshot,
)
from sase.llm_provider.model_launch_settings import LaunchModelField
from sase.llm_provider.provider_disable import TemporaryProviderDisable

ScalarSettingKind = Literal[
    "default_effort", "runner_limit", "big_epic_phase_threshold"
]


@dataclass(frozen=True)
class LaunchModelSettingRow:
    """One resolved scalar launch-model setting row."""

    field: LaunchModelField
    label: str
    detail: str
    snapshot: LaunchModelSettingSnapshot

    @property
    def row_id(self) -> str:
        return f"launch:{self.field}"

    @property
    def override_key(self) -> str:
        return self.snapshot.override_key

    @property
    def config_path(self) -> str:
        return self.snapshot.config_path

    @property
    def raw_value(self) -> str:
        return self.snapshot.raw_value

    @property
    def is_overridden(self) -> bool:
        return self.snapshot.override is not None and not self.is_override_paused

    @property
    def is_override_paused(self) -> bool:
        return self.snapshot.override_paused_by_provider_disable is not None


@dataclass(frozen=True)
class DefaultEffortSettingRow:
    """Captured global default-effort row."""

    snapshot: EffectiveDefaultEffortSnapshot

    row_id: str = "setting:default_effort"
    label: str = "default effort"
    kind: ScalarSettingKind = "default_effort"


@dataclass(frozen=True)
class RunnerLimitSettingRow:
    """Captured global running-agent limit row."""

    snapshot: EffectiveRunnerLimitSnapshot

    row_id: str = "setting:runner_limit"
    label: str = "max runners"
    kind: ScalarSettingKind = "runner_limit"


@dataclass(frozen=True)
class BigEpicPhaseThresholdSettingRow:
    """Captured big-epic authored-phase threshold row."""

    threshold: int = DEFAULT_BIG_EPIC_PHASE_THRESHOLD

    row_id: str = "setting:big_epic_phase_threshold"
    label: str = "big epic starts at"
    kind: ScalarSettingKind = "big_epic_phase_threshold"
    config_path: str = "bead.big_epic_phase_threshold"


ModelsPanelDisplayRow = (
    LaunchModelSettingRow
    | DefaultEffortSettingRow
    | RunnerLimitSettingRow
    | BigEpicPhaseThresholdSettingRow
    | AliasView
    | BucketView
)

_LAUNCH_SETTING_ORDER: tuple[tuple[LaunchModelField, str], ...] = (
    (DEFAULT_MODEL_FIELD, "default model"),
    (EPIC_LANDER_MODEL_FIELD, "epic lander"),
    (BIG_EPIC_LANDER_MODEL_FIELD, "big epic lander"),
)


def build_launch_model_setting_rows(
    *,
    provider_disables: dict[str, TemporaryProviderDisable],
    big_epic_phase_threshold: int,
) -> tuple[LaunchModelSettingRow | BigEpicPhaseThresholdSettingRow, ...]:
    """Build display-ready launch-setting rows."""
    details = {
        DEFAULT_MODEL_FIELD: "Used when a launch has no explicit %model directive.",
        EPIC_LANDER_MODEL_FIELD: (
            "Used by epic land agents for epics with fewer than "
            f"{big_epic_phase_threshold} authored phases."
        ),
        BIG_EPIC_LANDER_MODEL_FIELD: (
            "Used by epic land agents for epics with "
            f"{big_epic_phase_threshold} or more authored phases."
        ),
    }
    rows: tuple[LaunchModelSettingRow, ...] = tuple(
        LaunchModelSettingRow(
            field=field,
            label=label,
            detail=details[field],
            snapshot=build_launch_model_setting_snapshot(
                field,
                consume=False,
                provider_disables=provider_disables,
            ),
        )
        for field, label in _LAUNCH_SETTING_ORDER
    )
    return (*rows, BigEpicPhaseThresholdSettingRow(big_epic_phase_threshold))


__all__ = [
    "BigEpicPhaseThresholdSettingRow",
    "DefaultEffortSettingRow",
    "LaunchModelSettingRow",
    "ModelsPanelDisplayRow",
    "RunnerLimitSettingRow",
    "build_launch_model_setting_rows",
]
