"""Plan models shared by v2 import planning, rendering, and persistence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.names import ImportedV2RegistryClaim
from sase.agents_sync.v2_import_package import (
    ValidatedV2HoodPackage,
    ValidatedV2RunPayload,
)
from sase.agents_sync.v2_models import V2ContainerRecord
from sase.core.agent_identity_facade import AgentIdentitySnapshot


@dataclass(frozen=True, slots=True)
class PlannedRun:
    payload: ValidatedV2RunPayload
    localized_name: str
    destination_id: str
    artifact_dir: Path
    disposition: str
    previous_digest: str | None = None
    superseded_v1_name: str | None = None


@dataclass(frozen=True, slots=True)
class PlannedContainer:
    record: V2ContainerRecord
    localized_name: str


@dataclass(frozen=True, slots=True)
class HoodPlan:
    package: ValidatedV2HoodPackage
    identity: AgentIdentitySnapshot
    transaction_key: str
    runs: tuple[PlannedRun, ...]
    containers: tuple[PlannedContainer, ...]
    registry_claims: tuple[ImportedV2RegistryClaim, ...]
    relationships: tuple[Mapping[str, Any], ...]

    @property
    def changed_runs(self) -> tuple[PlannedRun, ...]:
        return tuple(run for run in self.runs if run.disposition != "observed")

    @property
    def is_unchanged(self) -> bool:
        return all(run.disposition in {"observed", "unchanged"} for run in self.runs)

    @property
    def is_refresh(self) -> bool:
        return any(run.disposition in {"refresh", "adopted"} for run in self.runs)

    @property
    def adopted_runs(self) -> tuple[PlannedRun, ...]:
        return tuple(run for run in self.runs if run.disposition == "adopted")

    @property
    def adopted_v1_artifact_dirs(self) -> frozenset[Path]:
        return frozenset(run.artifact_dir for run in self.adopted_runs)


__all__ = ["HoodPlan", "PlannedContainer", "PlannedRun"]
