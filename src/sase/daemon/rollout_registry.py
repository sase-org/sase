"""Central registry for daemon rollout surfaces and default policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.daemon.constants import LOCAL_DAEMON_SCHEMA_VERSION
from sase.daemon.read_config import (
    ACE_DAEMON_SURFACE_GROUPS,
    DEFAULT_ENABLED_SURFACE_GROUPS,
    SURFACE_GROUP_BY_READ_SURFACE,
)
from sase.daemon.write_facade import CAPABILITY_BY_WRITE_SURFACE
from sase.host.wire import (
    HOST_CAP_IPC_V1,
    HOST_CAP_LLM_INVOKE,
    HOST_CAP_LLM_METADATA,
    HOST_CAP_MANIFEST_V1,
    HOST_CAP_RESOURCE_POLICY_DIAGNOSTICS,
    HOST_CAP_VCS_QUERY,
    HOST_CAP_WORKFLOW_STEP,
    HOST_CAP_WORKSPACE_METADATA,
    HOST_CAP_WORKSPACE_RESOLVE_REF,
    HOST_CAP_XPROMPT_CATALOG,
)

RolloutFamily = Literal[
    "milestone",
    "process",
    "read",
    "read_diagnostics",
    "write",
    "scheduler",
    "provider_host",
    "mobile_gateway",
    "recovery",
]
Milestone = Literal["M0", "M1", "M2", "M3", "M4", "M5"]
DefaultPolicy = Literal[
    "default_off",
    "default_on",
    "opt_in",
    "direct_only",
    "future_authoritative",
]

TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV = "SASE_NO_DAEMON"

PROVIDER_HOST_GLOBAL_ENV_OVERRIDES = (
    TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV,
    "SASE_DAEMON_FORCE_DIRECT",
    "SASE_PROVIDER_HOST_MODE",
    "SASE_PROVIDER_HOST_QUERIES",
    "SASE_DISABLE_PROVIDER_HOST_ROUTING",
)

SCHEDULER_LAUNCH_MODES = ("direct", "shadow", "daemon")
SCHEDULER_AXE_MODES = ("direct", "daemon")
PROVIDER_HOST_MODES = ("direct", "shadow", "host-preferred", "host-required")


@dataclass(frozen=True)
class RolloutSurfaceRecord:
    """One rollout surface, its knobs, prerequisites, and default policy."""

    surface_id: str
    family: RolloutFamily
    title: str
    owner_epic: str
    minimum_milestone: Milestone
    config_keys: tuple[str, ...] = ()
    env_overrides: tuple[str, ...] = ()
    allowed_modes: tuple[str, ...] = ()
    daemon_capabilities: tuple[str, ...] = ()
    schema_versions: tuple[tuple[str, int], ...] = ()
    direct_fallback_available: bool = True
    parity_gates: tuple[str, ...] = ()
    perf_gates: tuple[str, ...] = ()
    recovery_commands: tuple[str, ...] = ()
    default_policy: DefaultPolicy = "default_off"
    default_enablement_allowed: bool = False


def rollout_surface_records() -> tuple[RolloutSurfaceRecord, ...]:
    """Return every known daemon rollout surface."""

    return _ROLLOUT_SURFACE_RECORDS


def rollout_records_by_id() -> dict[str, RolloutSurfaceRecord]:
    """Return rollout records keyed by stable surface id."""

    return {record.surface_id: record for record in _ROLLOUT_SURFACE_RECORDS}


def rollout_records_by_family(
    family: RolloutFamily,
) -> tuple[RolloutSurfaceRecord, ...]:
    """Return rollout records for one family."""

    return tuple(
        record for record in _ROLLOUT_SURFACE_RECORDS if record.family == family
    )


def _surface_env_name(group: str) -> str:
    token = "".join(ch if ch.isalnum() else "_" for ch in group.upper())
    return f"SASE_DAEMON_{token}_READS"


def _provider_host_env_name(operation_key: str) -> str:
    return f"SASE_PROVIDER_HOST_{operation_key.upper()}_MODE"


_READ_PARITY_GATE_BY_WRITE_CAPABILITY = {
    "agents.write": "daemon_read.parity.agents",
    "beads.write": "daemon_read.parity.beads",
    "changespecs.write": "daemon_read.parity.changespecs",
    "notifications.write": "daemon_read.parity.notifications",
}


def _read_surface_record(group: str) -> RolloutSurfaceRecord:
    ace_surface = group in ACE_DAEMON_SURFACE_GROUPS
    default_on = group in DEFAULT_ENABLED_SURFACE_GROUPS
    gate_prefix = "ace_daemon_read" if ace_surface else "daemon_read"
    return RolloutSurfaceRecord(
        surface_id=f"read.{group}",
        family="read",
        title=f"{group.replace('_', ' ').title()} read projections",
        owner_epic="epic9" if ace_surface else "epic5",
        minimum_milestone="M2" if ace_surface else "M1",
        config_keys=(f"daemon.reads.surfaces.{group}",),
        env_overrides=(
            TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV,
            "SASE_DAEMON_READS",
            "SASE_DAEMON_FORCE_DIRECT",
            _surface_env_name(group),
        ),
        daemon_capabilities=(f"{group}.read",),
        schema_versions=(("local_daemon", LOCAL_DAEMON_SCHEMA_VERSION),),
        parity_gates=(f"{gate_prefix}.parity.{group}",),
        perf_gates=(f"{gate_prefix}.perf.{group}",),
        recovery_commands=(
            f"sase daemon verify --surface {group}",
            f"sase daemon diff --surface {group}",
            f"sase daemon rebuild --surface {group}",
        ),
        default_policy="default_on"
        if default_on
        else ("opt_in" if ace_surface else "default_off"),
        default_enablement_allowed=default_on,
    )


def _write_surface_record(surface: str, capability: str) -> RolloutSurfaceRecord:
    read_parity_gate = _READ_PARITY_GATE_BY_WRITE_CAPABILITY.get(capability)
    parity_gates = (
        *((read_parity_gate,) if read_parity_gate is not None else ()),
        f"daemon_write.parity.{surface}",
        f"daemon_write.idempotency.{surface}",
        f"daemon_write.stale_source_conflict.{surface}",
        f"daemon_write.source_export_repair.{surface}",
    )
    return RolloutSurfaceRecord(
        surface_id=f"write.{surface}",
        family="write",
        title=f"{surface.replace('.', ' ').replace('_', ' ').title()} writes",
        owner_epic="epic6",
        minimum_milestone="M3",
        env_overrides=(TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV,),
        daemon_capabilities=(capability,),
        schema_versions=(("local_daemon", LOCAL_DAEMON_SCHEMA_VERSION),),
        parity_gates=parity_gates,
        recovery_commands=(
            "sase daemon doctor",
            "sase daemon rebuild --surface all",
        ),
        default_policy="default_off",
    )


def _provider_host_record(
    operation_key: str,
    operation: str,
    *,
    default_on: bool,
) -> RolloutSurfaceRecord:
    operation_capabilities = _PROVIDER_HOST_CAPABILITIES_BY_OPERATION.get(
        operation,
        (),
    )
    return RolloutSurfaceRecord(
        surface_id=f"provider_host.{operation_key}",
        family="provider_host",
        title=f"{operation.replace('.', ' ').title()} provider host routing",
        owner_epic="epic8",
        minimum_milestone="M5",
        config_keys=(f"daemon.provider_host.modes.{operation_key}",),
        env_overrides=(
            *PROVIDER_HOST_GLOBAL_ENV_OVERRIDES,
            _provider_host_env_name(operation_key),
        ),
        allowed_modes=PROVIDER_HOST_MODES,
        daemon_capabilities=(
            "host.call",
            HOST_CAP_IPC_V1,
            HOST_CAP_MANIFEST_V1,
            HOST_CAP_RESOURCE_POLICY_DIAGNOSTICS,
            *operation_capabilities,
        ),
        schema_versions=(("local_daemon", LOCAL_DAEMON_SCHEMA_VERSION),),
        parity_gates=(f"provider_host.parity.{operation}",),
        perf_gates=(f"provider_host.perf.{operation}",),
        recovery_commands=("SASE_PROVIDER_HOST_MODE=direct",),
        default_policy="default_on" if default_on else "default_off",
        default_enablement_allowed=default_on,
    )


_READ_SURFACE_GROUPS = tuple(sorted(set(SURFACE_GROUP_BY_READ_SURFACE.values())))

_PROVIDER_HOST_OPERATIONS = (
    ("llm_metadata", "llm.metadata", True),
    ("xprompt_catalog", "xprompt.catalog", True),
    ("vcs_query", "vcs.query", True),
    ("workspace_metadata", "workspace.metadata", True),
    ("workspace_resolve_ref", "workspace.resolve_ref", True),
    ("llm_invoke", "llm.invoke", False),
    ("workflow_step", "workflow.step", False),
    ("vcs_mutation", "vcs.mutation", False),
)

_PROVIDER_HOST_CAPABILITIES_BY_OPERATION = {
    "llm.metadata": (HOST_CAP_LLM_METADATA,),
    "xprompt.catalog": (HOST_CAP_XPROMPT_CATALOG,),
    "vcs.query": (HOST_CAP_VCS_QUERY,),
    "workspace.metadata": (HOST_CAP_WORKSPACE_METADATA,),
    "workspace.resolve_ref": (HOST_CAP_WORKSPACE_RESOLVE_REF,),
    "llm.invoke": (HOST_CAP_LLM_INVOKE,),
    "workflow.step": (HOST_CAP_WORKFLOW_STEP,),
}

_ROLLOUT_SURFACE_RECORDS = (
    RolloutSurfaceRecord(
        surface_id="milestone.m0_shadow_indexing",
        family="milestone",
        title="M0 shadow indexing readiness",
        owner_epic="epic11",
        minimum_milestone="M0",
        config_keys=("daemon.rollout.milestones.m0_shadow_indexing",),
        env_overrides=(
            TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV,
            "SASE_DAEMON_M0_SHADOW_INDEXING",
        ),
        allowed_modes=("disabled", "shadow"),
        daemon_capabilities=(
            "indexing.rebuild",
            "indexing.verify",
            "indexing.diff",
        ),
        schema_versions=(("local_daemon", LOCAL_DAEMON_SCHEMA_VERSION),),
        parity_gates=("daemon_shadow.parity.rebuild_verify_diff",),
        recovery_commands=(
            "sase daemon rebuild --surface all",
            "sase daemon verify --surface all",
            "sase daemon diff --surface all",
        ),
        default_policy="default_on",
        default_enablement_allowed=True,
    ),
    RolloutSurfaceRecord(
        surface_id="milestone.m1_read_through",
        family="milestone",
        title="M1 selected CLI/editor read-through readiness",
        owner_epic="epic11",
        minimum_milestone="M1",
        config_keys=("daemon.rollout.milestones.m1_read_through",),
        env_overrides=(
            TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV,
            "SASE_DAEMON_M1_READ_THROUGH",
        ),
        allowed_modes=("disabled", "read_through"),
        schema_versions=(("local_daemon", LOCAL_DAEMON_SCHEMA_VERSION),),
        recovery_commands=("SASE_DAEMON_M1_READ_THROUGH=0",),
        default_policy="default_on",
        default_enablement_allowed=True,
    ),
    RolloutSurfaceRecord(
        surface_id="daemon.process",
        family="process",
        title="Local daemon process lifecycle",
        owner_epic="epic3",
        minimum_milestone="M0",
        config_keys=(
            "daemon.command",
            "daemon.sase_home",
            "daemon.run_root",
            "daemon.socket_path",
            "daemon.disable_mobile_http",
            "daemon.startup_timeout_seconds",
        ),
        env_overrides=(TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV,),
        schema_versions=(("local_daemon", LOCAL_DAEMON_SCHEMA_VERSION),),
        recovery_commands=("sase daemon status", "sase daemon doctor"),
        default_policy="default_off",
    ),
    RolloutSurfaceRecord(
        surface_id="read.global",
        family="read",
        title="Global daemon read routing",
        owner_epic="epic5",
        minimum_milestone="M1",
        config_keys=("daemon.reads.enabled", "daemon.reads.force_direct"),
        env_overrides=(
            TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV,
            "SASE_DAEMON_READS",
            "SASE_DAEMON_FORCE_DIRECT",
        ),
        schema_versions=(("local_daemon", LOCAL_DAEMON_SCHEMA_VERSION),),
        parity_gates=("daemon_read.parity.global",),
        perf_gates=("daemon_read.perf.global",),
        recovery_commands=("SASE_NO_DAEMON=1",),
        default_policy="default_on",
        default_enablement_allowed=True,
    ),
    RolloutSurfaceRecord(
        surface_id="read.fallback_diagnostics",
        family="read_diagnostics",
        title="Read fallback diagnostics",
        owner_epic="epic5",
        minimum_milestone="M0",
        config_keys=("daemon.reads.fallback_diagnostics",),
        env_overrides=("SASE_DAEMON_FALLBACK_DIAGNOSTICS",),
        parity_gates=("daemon_read.diagnostics.fallback_metadata",),
        recovery_commands=("sase daemon diff --surface all",),
        default_policy="default_off",
    ),
    *(_read_surface_record(group) for group in _READ_SURFACE_GROUPS),
    *(
        _write_surface_record(surface, capability)
        for surface, capability in sorted(CAPABILITY_BY_WRITE_SURFACE.items())
    ),
    RolloutSurfaceRecord(
        surface_id="scheduler.launch",
        family="scheduler",
        title="Agent launch scheduler routing",
        owner_epic="epic7",
        minimum_milestone="M4",
        config_keys=("daemon.scheduler.launch_mode",),
        env_overrides=(
            TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV,
            "SASE_DAEMON_SCHEDULER_LAUNCH_MODE",
            "SASE_SCHEDULER_LAUNCH_MODE",
            "SASE_DAEMON_SCHEDULER_HOST_BRIDGE",
        ),
        allowed_modes=SCHEDULER_LAUNCH_MODES,
        daemon_capabilities=("scheduler.submit",),
        schema_versions=(("local_daemon", LOCAL_DAEMON_SCHEMA_VERSION),),
        parity_gates=("scheduler.launch.parity",),
        perf_gates=("scheduler.launch.perf",),
        recovery_commands=("SASE_DAEMON_SCHEDULER_LAUNCH_MODE=direct",),
        default_policy="default_off",
    ),
    RolloutSurfaceRecord(
        surface_id="scheduler.lifecycle",
        family="scheduler",
        title="Agent lifecycle scheduler routing",
        owner_epic="epic7",
        minimum_milestone="M4",
        config_keys=("daemon.scheduler.lifecycle_mode",),
        env_overrides=(
            TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV,
            "SASE_DAEMON_SCHEDULER_LIFECYCLE_MODE",
            "SASE_SCHEDULER_LIFECYCLE_MODE",
            "SASE_DAEMON_SCHEDULER_HOST_BRIDGE",
        ),
        allowed_modes=SCHEDULER_LAUNCH_MODES,
        daemon_capabilities=("scheduler.submit",),
        schema_versions=(("local_daemon", LOCAL_DAEMON_SCHEMA_VERSION),),
        parity_gates=("scheduler.lifecycle.parity",),
        perf_gates=("scheduler.lifecycle.perf",),
        recovery_commands=("SASE_DAEMON_SCHEDULER_LIFECYCLE_MODE=direct",),
        default_policy="default_off",
    ),
    RolloutSurfaceRecord(
        surface_id="scheduler.axe",
        family="scheduler",
        title="Axe scheduler routing",
        owner_epic="epic7",
        minimum_milestone="M4",
        config_keys=("daemon.scheduler.axe_mode",),
        env_overrides=(
            TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV,
            "SASE_DAEMON_SCHEDULER_AXE_MODE",
            "SASE_DAEMON_SCHEDULER_AXE_HOST_BRIDGE",
        ),
        allowed_modes=SCHEDULER_AXE_MODES,
        daemon_capabilities=("scheduler.submit",),
        schema_versions=(("local_daemon", LOCAL_DAEMON_SCHEMA_VERSION),),
        parity_gates=("scheduler.axe.parity",),
        perf_gates=("scheduler.axe.perf",),
        recovery_commands=("SASE_DAEMON_SCHEDULER_AXE_MODE=direct",),
        default_policy="default_off",
    ),
    RolloutSurfaceRecord(
        surface_id="provider_host.global",
        family="provider_host",
        title="Global provider host routing",
        owner_epic="epic8",
        minimum_milestone="M5",
        config_keys=(
            "daemon.provider_host.default_mode",
            "daemon.provider_host.shadow_compare",
        ),
        env_overrides=PROVIDER_HOST_GLOBAL_ENV_OVERRIDES,
        allowed_modes=PROVIDER_HOST_MODES,
        daemon_capabilities=(
            "host.call",
            HOST_CAP_IPC_V1,
            HOST_CAP_MANIFEST_V1,
            HOST_CAP_RESOURCE_POLICY_DIAGNOSTICS,
        ),
        schema_versions=(("local_daemon", LOCAL_DAEMON_SCHEMA_VERSION),),
        parity_gates=("provider_host.parity.global",),
        perf_gates=("provider_host.perf.global",),
        recovery_commands=("SASE_PROVIDER_HOST_MODE=direct",),
        default_policy="default_off",
    ),
    *(
        _provider_host_record(key, operation, default_on=default_on)
        for key, operation, default_on in _PROVIDER_HOST_OPERATIONS
    ),
    RolloutSurfaceRecord(
        surface_id="mobile_gateway.contract",
        family="mobile_gateway",
        title="Mobile gateway contract surface",
        owner_epic="mobile_mvp",
        minimum_milestone="M1",
        config_keys=(
            "mobile_gateway.bind_address",
            "mobile_gateway.port",
            "mobile_gateway.state_dir",
            "mobile_gateway.allow_non_loopback",
            "mobile_gateway.command",
            "mobile_gateway.startup_timeout_seconds",
            "daemon.disable_mobile_http",
        ),
        daemon_capabilities=("mobile.http",),
        schema_versions=(("local_daemon", LOCAL_DAEMON_SCHEMA_VERSION),),
        direct_fallback_available=False,
        parity_gates=("mobile_gateway.contract_snapshot",),
        perf_gates=("mobile_gateway.startup.perf",),
        recovery_commands=("sase mobile gateway start", "sase daemon start"),
        default_policy="default_off",
    ),
    RolloutSurfaceRecord(
        surface_id="recovery.projections",
        family="recovery",
        title="Projection recovery and rebuild operations",
        owner_epic="epic10",
        minimum_milestone="M0",
        schema_versions=(("local_daemon", LOCAL_DAEMON_SCHEMA_VERSION),),
        direct_fallback_available=False,
        parity_gates=("daemon_recovery.no_source_store_mutation",),
        recovery_commands=(
            "sase daemon doctor",
            "sase daemon verify --surface all",
            "sase daemon diff --surface all",
            "sase daemon rebuild --surface all",
            "sase daemon backup",
            "sase daemon restore <backup.sqlite>",
        ),
        default_policy="direct_only",
    ),
)

__all__ = [
    "DefaultPolicy",
    "Milestone",
    "PROVIDER_HOST_MODES",
    "RolloutFamily",
    "RolloutSurfaceRecord",
    "SCHEDULER_AXE_MODES",
    "SCHEDULER_LAUNCH_MODES",
    "TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV",
    "rollout_records_by_family",
    "rollout_records_by_id",
    "rollout_surface_records",
]
