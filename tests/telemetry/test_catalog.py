"""Tests for the telemetry metric catalog."""

from sase.telemetry.catalog import (
    SUBSYSTEM_ORDER,
    MetricInfo,
    get_catalog,
    get_subsystems,
)
from sase.telemetry.metrics import METRIC_DEFS


def test_catalog_length_matches_metric_defs() -> None:
    catalog = get_catalog()
    assert len(catalog) == len(METRIC_DEFS)


def test_catalog_entries_are_metric_info() -> None:
    catalog = get_catalog()
    for entry in catalog:
        assert isinstance(entry, MetricInfo)


def test_catalog_attr_names_match_metric_defs() -> None:
    catalog = get_catalog()
    expected_attrs = [attr for attr, *_ in METRIC_DEFS]
    actual_attrs = [m.attr for m in catalog]
    assert actual_attrs == expected_attrs


def test_catalog_kinds_are_valid() -> None:
    valid_kinds = {"counter", "gauge", "histogram"}
    catalog = get_catalog()
    for m in catalog:
        assert m.kind in valid_kinds, f"{m.attr} has invalid kind: {m.kind}"


def test_catalog_all_have_subsystem() -> None:
    catalog = get_catalog()
    for m in catalog:
        assert m.subsystem, f"{m.attr} has empty subsystem"
        assert m.subsystem != "Other", f"{m.attr} unmapped to a subsystem"


def test_catalog_subsystem_derivation() -> None:
    catalog = get_catalog()
    by_attr = {m.attr: m for m in catalog}

    assert by_attr["AGENT_RUNS"].subsystem == "Agent Lifecycle"
    assert by_attr["LLM_INVOCATIONS"].subsystem == "LLM Provider"
    assert by_attr["AXE_CYCLES"].subsystem == "Axe Orchestrator"
    assert by_attr["HOOK_EXECUTIONS"].subsystem == "Hooks / Mentors / Workflows"
    assert by_attr["MENTOR_EXECUTIONS"].subsystem == "Hooks / Mentors / Workflows"
    assert by_attr["BEAD_OPERATIONS"].subsystem == "Beads"
    assert by_attr["VCS_COMMITS"].subsystem == "VCS / Workspace"
    assert by_attr["WORKSPACE_ACTIVE"].subsystem == "VCS / Workspace"
    assert by_attr["NOTIFICATIONS_SENT"].subsystem == "Notifications"


def test_get_subsystems_returns_all_metrics() -> None:
    subsystems = get_subsystems()
    total = sum(len(v) for v in subsystems.values())
    assert total == len(METRIC_DEFS)


def test_get_subsystems_order_matches_constant() -> None:
    subsystems = get_subsystems()
    keys = list(subsystems.keys())
    # All keys should appear in SUBSYSTEM_ORDER and in the same relative order.
    for key in keys:
        assert key in SUBSYSTEM_ORDER, f"Unexpected subsystem: {key}"
    # Verify the order is preserved.
    order_indices = [SUBSYSTEM_ORDER.index(k) for k in keys]
    assert order_indices == sorted(order_indices)


def test_metric_info_is_frozen() -> None:
    catalog = get_catalog()
    m = catalog[0]
    try:
        m.attr = "CHANGED"  # type: ignore[misc]
        raise AssertionError("Expected FrozenInstanceError")
    except AttributeError:
        pass
