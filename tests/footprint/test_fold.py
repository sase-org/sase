"""Tests for the Footprint fold driver and carrying-cost enrichment."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.footprint import carrying_cost, fold
from sase.footprint.catalog import CatalogEntry


def test_carrying_cost_parses_each_handler_file_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_root = tmp_path / "src"
    source = source_root / "sase" / "handlers.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "@decorator\n"
        "def handle():\n"
        "    value = 1\n"
        "    return value\n"
        "\n"
        "class Handler:\n"
        "    def run(self):\n"
        "        return True\n",
        encoding="utf-8",
    )
    calls: list[Path] = []
    parse_file = carrying_cost._parse_file

    def count_parse(path: Path):
        calls.append(path)
        return parse_file(path)

    monkeypatch.setattr(carrying_cost, "_parse_file", count_parse)
    entries = [
        _entry("cli:first", "sase/handlers.py:handle"),
        _entry("cli:second", "sase/handlers.py:Handler.run"),
    ]

    enrichment = carrying_cost.carrying_cost_enrichment(
        entries, source_root=source_root
    )

    assert enrichment == {"cli:first": 4, "cli:second": 2}
    assert calls == [source.resolve()]


def test_fold_if_stale_only_folds_old_pending_bytes(
    monkeypatch, tmp_path: Path
) -> None:
    recent = {
        "spool_bytes_pending": 5,
        "last_fold_at": datetime.now(UTC).isoformat(),
    }
    monkeypatch.setattr(fold, "_read_status", lambda *_args: recent)
    monkeypatch.setattr(
        fold,
        "fold_ledger",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected fold")),
    )
    assert fold.fold_if_stale(sase_home=tmp_path) == recent

    stale = {
        "spool_bytes_pending": 5,
        "last_fold_at": (datetime.now(UTC) - timedelta(minutes=20)).isoformat(),
    }
    expected = {"spool_bytes_pending": 0, "folded": True}
    monkeypatch.setattr(fold, "_read_status", lambda *_args: stale)
    monkeypatch.setattr(
        fold,
        "fold_ledger",
        lambda **kwargs: {
            "status": expected,
            "initial_status": kwargs["initial_status"],
        },
    )
    assert fold.fold_if_stale(sase_home=tmp_path) == expected


def test_fold_ledger_ingests_loc_folds_prunes_and_discloses_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    entry = _entry("cli:bead.list", "sase/main/bead_handler.py:handle_list")
    before = {"first_record_day": None}
    after = {"first_record_day": "2026-10-27"}
    snapshots = iter((before, after))
    calls: dict[str, Any] = {}
    monkeypatch.setattr(fold, "_read_status", lambda *_args: next(snapshots))
    monkeypatch.setattr(fold, "_footprint_settings", lambda: fold._DEFAULTS.copy())
    monkeypatch.setattr(fold, "catalog_path", lambda: tmp_path / "catalog.jsonl")
    monkeypatch.setattr(
        fold,
        "load_catalog",
        lambda _path: (SimpleNamespace(rev="catalog-rev"), [entry]),
    )
    monkeypatch.setattr(
        fold,
        "carrying_cost_enrichment",
        lambda _entries: {"cli:bead.list": 17},
    )
    monkeypatch.setattr(
        fold,
        "footprint_catalog_status",
        lambda *_args, **_kwargs: {"known": False},
    )

    def ingest(_store, _catalog, enrichment, _day, **_kwargs):
        calls["enrichment"] = enrichment
        return {"known": True}

    monkeypatch.setattr(fold, "footprint_ingest_catalog", ingest)
    monkeypatch.setattr(
        fold,
        "footprint_fold",
        lambda *_args, **_kwargs: {
            "files_folded": 1,
            "records_folded": 2,
            "torn": 0,
        },
    )
    monkeypatch.setattr(
        fold,
        "footprint_prune",
        lambda *_args, **_kwargs: {"daily_deleted": 0, "coverage_deleted": 0},
    )
    notifications: list[bool] = []
    monkeypatch.setattr(
        fold, "_upsert_disclosure_notification", lambda: notifications.append(True)
    )

    outcome = fold.fold_ledger(sase_home=tmp_path, today="2026-10-27")

    assert outcome["folded"] is True
    assert outcome["status"] == after
    assert calls["enrichment"] == {"cli:bead.list": 17}
    assert notifications == [True]


def test_fold_ledger_does_not_repeat_disclosure_after_first_record(
    monkeypatch,
    tmp_path: Path,
) -> None:
    after = {"first_record_day": "2026-10-27"}
    monkeypatch.setattr(fold, "_footprint_settings", lambda: fold._DEFAULTS.copy())
    monkeypatch.setattr(
        fold,
        "footprint_catalog_status",
        lambda *_args, **_kwargs: {"known": True},
    )
    monkeypatch.setattr(
        fold,
        "footprint_fold",
        lambda *_args, **_kwargs: {"files_folded": 1, "records_folded": 1},
    )
    monkeypatch.setattr(
        fold,
        "footprint_prune",
        lambda *_args, **_kwargs: {"daily_deleted": 0, "coverage_deleted": 0},
    )
    monkeypatch.setattr(fold, "_read_status", lambda *_args: after)
    monkeypatch.setattr(
        fold,
        "_upsert_disclosure_notification",
        lambda: (_ for _ in ()).throw(AssertionError("duplicate disclosure")),
    )

    outcome = fold.fold_ledger(
        sase_home=tmp_path,
        today="2026-10-27",
        initial_status=after,
    )

    assert outcome["status"] == after


def test_clear_ledger_writes_the_generation_file(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.setattr(
        fold,
        "footprint_clear",
        lambda *_args, **_kwargs: {"generation": 9},
    )

    assert fold.clear_ledger() == {"generation": 9}
    assert (home / "footprint" / "generation").read_text() == "9\n"


def _entry(feature_id: str, source: str) -> CatalogEntry:
    return CatalogEntry(
        id=feature_id,
        ns="cli",
        area="cli.test",
        kind="command",
        label=feature_id,
        src=source,
    )
