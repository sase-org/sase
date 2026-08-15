"""AST conformance for the ACE proc-producer inventory."""

from __future__ import annotations

from sase.ace.tui.proc_producer_inventory import (
    INFRASTRUCTURE,
    PRODUCTION_PRODUCERS,
    compare_inventory_to_source,
)
from sase.ace.tui.proc_producer_inventory import (
    _scan_production_submit_calls,
)


def test_inventory_matches_live_production_source() -> None:
    unexpected, missing, duplicates = compare_inventory_to_source()

    assert not duplicates, f"duplicate inventory site ids: {duplicates}"
    assert not missing, f"stale inventory entries not found in source: {missing}"
    assert not unexpected, (
        "unlisted or structurally changed production producers: "
        f"{[item.site_key for item in unexpected]}"
    )


def test_inventory_allows_only_the_adapter_forwarding_edge() -> None:
    found = _scan_production_submit_calls()
    forwards = [item for item in found if item.kind == "adapter_forward"]

    assert len(forwards) == 1
    assert forwards[0].source_path.endswith("proc_actions.py")
    assert forwards[0].function == "_submit_proc"
    assert (
        sum(1 for site in PRODUCTION_PRODUCERS if site.kind == "adapter_forward") == 1
    )


def test_inventory_records_infrastructure_and_classifications() -> None:
    assert any(site.site_id == "infra.proc_queue" for site in INFRASTRUCTURE)
    assert any(site.site_id == "infra.proc_mirror" for site in INFRASTRUCTURE)
    assert any(site.function == "_submit_durable_proc" for site in INFRASTRUCTURE)
    assert any(
        site.classification == "ui_only" and site.site_id == "prompt.stash"
        for site in PRODUCTION_PRODUCERS
    )
    durable = [
        site for site in PRODUCTION_PRODUCERS if site.classification == "durable"
    ]
    assert durable
    assert len(PRODUCTION_PRODUCERS) == 54
