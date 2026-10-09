"""Launch input types for run-agent directive metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.bead.work import (
    SASE_EPIC_BEAD_ID_ENV,
    SASE_EPIC_CLAN_TRIBE_ENV,
    SASE_EPIC_PLAN_REF_ENV,
    SASE_EPIC_PLAN_SNAPSHOT_ENV,
    SASE_PHASE_BEAD_ID_ENV,
)


EPIC_WORK_ENV_METADATA_NAMES = (
    (SASE_EPIC_PLAN_REF_ENV, "epic_plan_ref"),
    (SASE_EPIC_PLAN_SNAPSHOT_ENV, "epic_plan_snapshot"),
    (SASE_EPIC_BEAD_ID_ENV, "epic_bead_id"),
    (SASE_PHASE_BEAD_ID_ENV, "phase_bead_id"),
    (SASE_EPIC_CLAN_TRIBE_ENV, "clan_tribe"),
)
DEFAULT_QUEUE_WEIGHT = 1.0


@dataclass(frozen=True)
class AgentMetadataInputs:
    """Resolved launch values used to assemble ``agent_meta.json``."""

    workspace_dir: str
    workspace_num: int
    output_path: str | None
    bead_id: str | None
    wait_names: list[str]
    wait_identity_deps: list[dict[str, Any]]
    wait_fork_sources: list[dict[str, str]]
    wait_beads: list[str]
    wait_hoods: list[str]
    model: str | None
    llm_provider: str | None
    reasoning_effort: str | None
    model_alias: str | None
    model_alias_trail: list[str]
    model_alias_origin: str | None
    model_alias_reservation: dict[str, Any] | None
    model_alias_overrides: dict[str, str]
    vcs_provider: str | None
    auto_dismiss: str | None
    preserved: dict[str, Any]
    epic_work: dict[str, Any]
    cl_name: str | None
    vcs_ref: tuple[str, str] | None = None
    wait_for_epics_of: list[str] | None = None
