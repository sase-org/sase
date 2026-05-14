"""Inventory tests for daemon rollout surface defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.ace.tui.util.perf_gates import ACE_M2_SURFACE_GATES
from sase.daemon.read_config import (
    ACE_DAEMON_SURFACE_GROUPS,
    DEFAULT_ENABLED_SURFACE_GROUPS,
    SURFACE_GROUP_BY_READ_SURFACE,
)
from sase.daemon.rollout_registry import (
    SCHEDULER_AXE_MODES,
    SCHEDULER_LAUNCH_MODES,
    TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV,
    RolloutSurfaceRecord,
    rollout_records_by_family,
    rollout_records_by_id,
    rollout_surface_records,
)
from sase.daemon.write_facade import CAPABILITY_BY_WRITE_SURFACE


def test_rollout_registry_has_stable_unique_ids() -> None:
    records = rollout_surface_records()

    assert records
    assert len({record.surface_id for record in records}) == len(records)


def test_registry_config_keys_exist_in_default_config() -> None:
    config = _default_config()

    missing = [
        (record.surface_id, key)
        for record in rollout_surface_records()
        for key in record.config_keys
        if _lookup(config, key) is _MISSING
    ]

    assert missing == []


def test_read_surface_registry_matches_config_and_helper_constants() -> None:
    config_surfaces = set(_lookup(_default_config(), "daemon.reads.surfaces"))
    helper_surfaces = set(SURFACE_GROUP_BY_READ_SURFACE.values())
    registry_surfaces = {
        record.surface_id.removeprefix("read.")
        for record in rollout_records_by_family("read")
        if record.config_keys
        and record.config_keys[0].startswith("daemon.reads.surfaces.")
    }

    assert registry_surfaces == config_surfaces == helper_surfaces

    default_on = {
        record.surface_id.removeprefix("read.")
        for record in rollout_records_by_family("read")
        if record.default_policy == "default_on"
        and record.config_keys
        and record.config_keys[0].startswith("daemon.reads.surfaces.")
    }
    assert default_on == DEFAULT_ENABLED_SURFACE_GROUPS


def test_ace_read_surfaces_stay_opt_in_until_registry_allows_default() -> None:
    config = _default_config()
    records = rollout_records_by_id()

    for surface in ACE_DAEMON_SURFACE_GROUPS:
        record = records[f"read.{surface}"]
        default_enabled = bool(_lookup(config, f"daemon.reads.surfaces.{surface}"))
        assert record.default_policy == "opt_in"
        assert record.parity_gates
        assert record.perf_gates
        assert not default_enabled or record.default_enablement_allowed


def test_m2_ace_read_surfaces_have_independent_gate_records() -> None:
    records = rollout_records_by_id()

    for surface, gate in ACE_M2_SURFACE_GATES.items():
        record = records[f"read.{surface}"]
        assert record.minimum_milestone == "M2"
        assert record.default_policy == "opt_in"
        assert record.default_enablement_allowed is False
        assert record.parity_gates == (gate.parity_gate,)
        assert record.perf_gates == (gate.perf_gate,)
        assert record.direct_fallback_available is True


def test_default_enabled_read_surfaces_have_gate_records() -> None:
    config = _default_config()

    for surface, enabled in _lookup(config, "daemon.reads.surfaces").items():
        if not enabled:
            continue
        record = rollout_records_by_id()[f"read.{surface}"]
        assert record.default_policy == "default_on"
        assert record.default_enablement_allowed
        assert record.parity_gates
        assert record.perf_gates


def test_scheduler_inventory_matches_default_config_modes() -> None:
    config_scheduler = _lookup(_default_config(), "daemon.scheduler")
    registry_by_key = {
        record.config_keys[0].removeprefix("daemon.scheduler."): record
        for record in rollout_records_by_family("scheduler")
    }

    assert set(registry_by_key) == {"launch_mode", "lifecycle_mode", "axe_mode"}
    assert set(registry_by_key) == set(config_scheduler)
    assert config_scheduler["launch_mode"] in SCHEDULER_LAUNCH_MODES
    assert config_scheduler["lifecycle_mode"] in SCHEDULER_LAUNCH_MODES
    assert config_scheduler["axe_mode"] in SCHEDULER_AXE_MODES

    for mode_key, record in registry_by_key.items():
        assert config_scheduler[mode_key] in record.allowed_modes
        assert record.default_policy == "default_off"


def test_provider_host_inventory_matches_operation_modes() -> None:
    config_modes = _lookup(_default_config(), "daemon.provider_host.modes")
    registry_modes = {
        record.config_keys[0].removeprefix("daemon.provider_host.modes."): record
        for record in rollout_records_by_family("provider_host")
        if record.config_keys
        and record.config_keys[0].startswith("daemon.provider_host.modes.")
    }

    assert set(registry_modes) == set(config_modes)
    for operation_key, mode in config_modes.items():
        record = registry_modes[operation_key]
        assert mode in record.allowed_modes
        if mode == "host-preferred":
            assert record.default_policy == "default_on"
            assert record.default_enablement_allowed
            assert record.parity_gates
            assert record.perf_gates
        else:
            assert record.default_policy == "default_off"


def test_write_surface_inventory_matches_capability_helper() -> None:
    write_records = {
        record.surface_id.removeprefix("write."): record
        for record in rollout_records_by_family("write")
    }

    assert set(write_records) == set(CAPABILITY_BY_WRITE_SURFACE)
    for surface, capability in CAPABILITY_BY_WRITE_SURFACE.items():
        record = write_records[surface]
        assert record.daemon_capabilities == (capability,)
        assert record.default_policy == "default_off"


def test_m3_write_surfaces_require_reversible_hardening_gates() -> None:
    records = rollout_records_by_family("write")

    for record in records:
        surface = record.surface_id.removeprefix("write.")
        assert record.minimum_milestone == "M3"
        assert f"daemon_write.parity.{surface}" in record.parity_gates
        assert f"daemon_write.idempotency.{surface}" in record.parity_gates
        assert f"daemon_write.stale_source_conflict.{surface}" in record.parity_gates
        assert f"daemon_write.source_export_repair.{surface}" in record.parity_gates
        assert "sase daemon doctor" in record.recovery_commands
        assert "sase daemon rebuild --surface all" in record.recovery_commands
        assert record.direct_fallback_available is True


def test_m3_write_surfaces_with_matching_reads_require_read_parity() -> None:
    records = rollout_records_by_family("write")
    read_parity_by_capability = {
        "agents.write": "daemon_read.parity.agents",
        "beads.write": "daemon_read.parity.beads",
        "changespecs.write": "daemon_read.parity.changespecs",
        "notifications.write": "daemon_read.parity.notifications",
    }

    for record in records:
        expected = read_parity_by_capability.get(record.daemon_capabilities[0])
        if expected is not None:
            assert expected in record.parity_gates


def test_no_daemon_escape_hatch_covers_fallbackable_runtime_surfaces() -> None:
    runtime_families = {"read", "write", "scheduler", "provider_host"}

    missing = [
        record.surface_id
        for record in rollout_surface_records()
        if record.family in runtime_families
        and record.direct_fallback_available
        and TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV not in record.env_overrides
    ]

    assert missing == []


def test_registry_includes_shadow_diff_and_recovery_surfaces() -> None:
    records = rollout_records_by_id()

    assert records["milestone.m0_shadow_indexing"].config_keys == (
        "daemon.rollout.milestones.m0_shadow_indexing",
    )
    assert records["milestone.m1_read_through"].config_keys == (
        "daemon.rollout.milestones.m1_read_through",
    )
    assert (
        "SASE_DAEMON_M0_SHADOW_INDEXING"
        in records["milestone.m0_shadow_indexing"].env_overrides
    )
    assert (
        "SASE_DAEMON_M1_READ_THROUGH"
        in records["milestone.m1_read_through"].env_overrides
    )
    assert records["read.fallback_diagnostics"].config_keys == (
        "daemon.reads.fallback_diagnostics",
    )
    assert records["recovery.projections"].recovery_commands
    assert records["mobile_gateway.contract"].direct_fallback_available is False


def test_rollout_records_are_runtime_agnostic() -> None:
    runtime_names = ("claude", "gemini", "codex", "qwen", "opencode")

    offenders = [
        record.surface_id
        for record in rollout_surface_records()
        if any(runtime in _record_text(record).lower() for runtime in runtime_names)
    ]

    assert offenders == []


def _record_text(record: RolloutSurfaceRecord) -> str:
    parts: list[str] = [
        record.surface_id,
        record.title,
        record.owner_epic,
        *record.config_keys,
        *record.env_overrides,
        *record.allowed_modes,
        *record.daemon_capabilities,
        *record.parity_gates,
        *record.perf_gates,
        *record.recovery_commands,
    ]
    return "\n".join(parts)


_MISSING = object()


def _default_config() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    with open(root / "src" / "sase" / "default_config.yml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict)
    return data


def _lookup(config: dict[str, Any], path: str) -> Any:
    current: Any = config
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current
