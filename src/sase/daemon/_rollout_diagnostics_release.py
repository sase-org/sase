"""Release checklist payloads for daemon rollout diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.daemon.release_contract import release_contract_payload
from sase.daemon.rollout_gates import GateCoverage, milestone_gate_records
from sase.daemon.rollout_registry import rollout_surface_records
from sase.daemon._rollout_diagnostics_status import milestone_payloads
from sase.daemon._rollout_diagnostics_utils import lookup, mapping


def provider_host_payload() -> dict[str, Any]:
    from sase.host.manifest import (
        discover_host_manifests,
        resource_policy_diagnostics,
    )
    from sase.host.routing import host_routing_diagnostics

    discovery = discover_host_manifests()
    return {
        "routing": host_routing_diagnostics(),
        "resource_policy": resource_policy_diagnostics(),
        "manifest_discovery": {
            "diagnostics": list(discovery.diagnostics),
            "records": [
                {
                    "plugin_id": record.manifest.plugin_id,
                    "version": record.manifest.version,
                    "source": record.source,
                    "compatibility_mode": record.compatibility_mode,
                    "daemon_authoritative": record.daemon_authoritative,
                    "operation_families": list(record.manifest.operation_families),
                    "capabilities": list(record.manifest.capabilities),
                    "network_mode": record.manifest.network.mode,
                    "spawn_allowed": record.manifest.process.spawn_allowed,
                    "timeout_hints_ms": dict(record.manifest.timeout_hints_ms),
                    "warm_host_eligible": record.manifest.warm_host_eligible,
                    "diagnostics": list(record.diagnostics),
                }
                for record in discovery.records
            ],
        },
    }


def release_checklist_payload(
    config: Mapping[str, Any],
    coverage: GateCoverage,
    *,
    surfaces: list[dict[str, Any]],
) -> dict[str, Any]:
    records = tuple(rollout_surface_records())
    milestone_payload_list = milestone_payloads(coverage)
    fallback_commands = sorted(
        {
            command
            for surface in surfaces
            for command in (mapping(surface.get("fallback")).get("command"),)
            if isinstance(command, str) and command
        }
        | {"SASE_NO_DAEMON=1"}
    )
    return {
        "current_defaults": _release_defaults(config),
        "supported_schema_ranges": release_contract_payload(),
        "migration_rebuild_steps": [
            "sase daemon doctor",
            "sase daemon rebuild --surface all",
            "sase daemon verify --surface all",
            "sase daemon diff --surface all --limit 100",
            "sase daemon backup",
        ],
        "rollback_commands": fallback_commands,
        "known_opt_in_surfaces": [
            record.surface_id for record in records if record.default_policy == "opt_in"
        ],
        "required_ci_perf_soak_evidence": _required_evidence(milestone_payload_list),
        "authoritative_migration_guidance": [
            {
                "surface_id": record.surface_id,
                "minimum_milestone": record.minimum_milestone,
                "parity_gates": list(record.parity_gates),
                "recovery_commands": list(record.recovery_commands),
                "direct_fallback_available": record.direct_fallback_available,
            }
            for record in records
            if record.minimum_milestone in {"M3", "M4", "M5"}
        ],
    }


def _release_defaults(config: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "reads": {
            "enabled": lookup(config, "daemon.reads.enabled"),
            "force_direct": lookup(config, "daemon.reads.force_direct"),
            "enabled_surfaces": sorted(
                surface
                for surface, enabled in mapping(
                    lookup(config, "daemon.reads.surfaces")
                ).items()
                if enabled is True
            ),
            "disabled_surfaces": sorted(
                surface
                for surface, enabled in mapping(
                    lookup(config, "daemon.reads.surfaces")
                ).items()
                if enabled is not True
            ),
        },
        "scheduler": dict(mapping(lookup(config, "daemon.scheduler"))),
        "provider_host": {
            "default_mode": lookup(config, "daemon.provider_host.default_mode"),
            "modes": dict(mapping(lookup(config, "daemon.provider_host.modes"))),
        },
        "milestones": dict(mapping(lookup(config, "daemon.rollout.milestones"))),
    }


def _required_evidence(
    milestone_payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records_by_milestone = {
        record.milestone: record for record in milestone_gate_records()
    }
    return [
        {
            "milestone": payload["milestone"],
            "covered": payload["covered"],
            "docs_links": sorted(
                records_by_milestone[payload["milestone"]].required_docs_links
            ),
            "missing_by_kind": payload["missing_by_kind"],
        }
        for payload in milestone_payloads
    ]


__all__ = [
    "provider_host_payload",
    "release_checklist_payload",
]
