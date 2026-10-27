"""Binding smoke tests for the Footprint ledger facade."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from sase.core.footprint_facade import (
    FOOTPRINT_WIRE_SCHEMA_VERSION,
    footprint_catalog_status,
    footprint_clear,
    footprint_fold,
    footprint_ingest_catalog,
    footprint_prune,
    footprint_status,
    footprint_upsert_derived,
    footprint_validate_overlay,
    footprint_wire_schema_version,
)
from sase.core.rust import require_rust_binding


def _catalog(path: Path, entries: list[dict[str, object]]) -> None:
    body = "".join(json.dumps(entry, separators=(",", ":")) + "\n" for entry in entries)
    rev = sha256(body.encode("utf-8")).hexdigest()[:12]
    header = {
        "schema": "sase.footprint.catalog/1",
        "rev": rev,
        "count": len(entries),
    }
    path.write_text(json.dumps(header) + "\n" + body, encoding="utf-8")


def test_schema_version_matches_binding() -> None:
    assert FOOTPRINT_WIRE_SCHEMA_VERSION == 1
    assert footprint_wire_schema_version() == FOOTPRINT_WIRE_SCHEMA_VERSION
    binding = require_rust_binding("footprint_wire_schema_version")
    assert int(binding()) == FOOTPRINT_WIRE_SCHEMA_VERSION


def test_ingest_fold_status_derived_prune_clear(tmp_path: Path) -> None:
    store = tmp_path / "footprint.sqlite"
    spool = tmp_path / "spool"
    spool.mkdir()
    catalog = tmp_path / "catalog.jsonl"
    _catalog(
        catalog,
        [
            {
                "id": "cli:bead.list",
                "ns": "cli",
                "area": "cli.bead",
                "kind": "command",
                "label": "List beads",
                "parent": None,
                "src": "sase/main/bead_handler.py:handle_list",
            }
        ],
    )
    status = footprint_catalog_status(store, catalog)
    assert status["known"] is False
    ingested = footprint_ingest_catalog(
        store, catalog, {"cli:bead.list": 40}, "2026-10-27"
    )
    assert ingested["known"] is True
    (spool / "2026-10-26.jsonl").write_text(
        '{"s":1,"d":"2026-10-26","f":"cli:bead.list","a":"human","v":"cli","o":"ok","n":1,"ms":8,"ver":"0.18.1"}\n',
        encoding="utf-8",
    )
    folded = footprint_fold(store, spool, "2026-10-27", 7, 30)
    assert folded["records_folded"] == 1
    snapshot = footprint_status(store, spool, "2026-10-27")
    assert snapshot["schema_version"] == FOOTPRINT_WIRE_SCHEMA_VERSION
    assert snapshot["catalog_count"] == 1
    assert snapshot["generation"] == 0
    footprint_upsert_derived(
        store,
        "derived.macros",
        ["2026-10-20"],
        [
            {
                "day": "2026-10-20",
                "feature_id": "macro:research",
                "actor": "human",
                "via": "prompt",
                "outcome": "ok",
                "n": 2,
                "dur_ms_sum": 0,
                "dur_ms_max": 0,
            }
        ],
        [
            {
                "day": "2026-10-20",
                "surface": "macro",
                "measured": 1,
                "human_active": 1,
                "records": 2,
                "torn": 0,
                "dropped": 0,
                "unknown_ids": 0,
                "incomplete": 0,
            }
        ],
    )
    pruned = footprint_prune(store, "2026-10-27", 400)
    assert pruned["daily_deleted"] == 0
    footprint_validate_overlay({"schema": "sase.footprint.overlay/1", "features": {}})
    cleared = footprint_clear(store, spool)
    assert cleared["generation"] == 1
    assert list(spool.glob("*.jsonl")) == []
