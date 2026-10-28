"""Tests for Footprint weekly export packs and replace-all import."""

from __future__ import annotations

import argparse
import getpass
import io
import json
import re
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase import __version__

TODAY = "2026-10-27"
WEEK_DAYS = [
    "2026-10-19",
    "2026-10-20",
    "2026-10-21",
    "2026-10-22",
    "2026-10-23",
    "2026-10-24",
    "2026-10-25",
]

PACK_KEYS = {
    "schema",
    "nonce",
    "week",
    "sase",
    "os",
    "observed",
    "features",
    "not_measured",
}
BUCKETS = {"1", "2-5", "6-20", "21+"}


def _forbidden_tokens(tmp_path: Path) -> list[str]:
    return [str(tmp_path), getpass.getuser(), socket.gethostname()]


def _spool_line(
    day: str,
    feature: str,
    *,
    via: str = "cli",
    actor: str = "human",
    options: list[str] | None = None,
) -> str:
    record: dict[str, Any] = {
        "s": 1,
        "d": day,
        "f": feature,
        "a": actor,
        "v": via,
        "o": "ok",
        "n": 1,
        "ver": __version__,
    }
    if options:
        record["opt"] = options
    else:
        record["ms"] = 5
    return json.dumps(record, separators=(",", ":")) + "\n"


def _build_home(home: Path) -> Path:
    """Ingest the real catalog, fold one complete week, return the store."""

    from sase.core.footprint_facade import footprint_fold, footprint_ingest_catalog
    from sase.footprint.catalog import catalog_path

    store = home / "footprint" / "footprint.sqlite"
    spool = home / "footprint" / "spool"
    spool.mkdir(parents=True, exist_ok=True)
    footprint_ingest_catalog(store, catalog_path(), {}, TODAY)
    for day in WEEK_DAYS:
        lines = [
            _spool_line(day, "cli:version"),
            _spool_line(day, "cli:bead.list"),
            _spool_line(day, "macro:coder", via="prompt"),
            _spool_line(day, "macro:~custom", via="prompt"),
            _spool_line(day, "config:ace.page_size"),
            _spool_line(day, "plugin:listen"),
        ]
        if day == WEEK_DAYS[0]:
            lines.append(_spool_line(day, "cli:version", options=["json"]))
        (spool / f"{day}.jsonl").write_text("".join(lines), encoding="utf-8")
    folded = footprint_fold(store, spool, TODAY, 90, 400)
    assert int(folded.get("records_folded", 0)) >= 20
    return store


def _fixed_packs() -> list[dict[str, Any]]:
    return [
        {
            "schema": "sase.footprint.export/1",
            "nonce": "r_fixed000000000000000000000001",
            "week": "2026-W42",
            "sase": "0.18",
            "os": "linux",
            "observed": {"cli": 5},
            "features": [
                {"id": "cli:version", "actor": "human", "days": 5, "n": "2-5"},
            ],
            "not_measured": [],
        },
        {
            "schema": "sase.footprint.export/1",
            "nonce": "r_fixed000000000000000000000002",
            "week": "2026-W43",
            "sase": "0.18",
            "os": "linux",
            "observed": {"cli": 3},
            "features": [
                {"id": "cli:bead.list", "actor": "human", "days": 1, "n": "1"},
            ],
            "not_measured": ["tui"],
        },
    ]


def test_preview_bytes_equal_file_bytes_and_mode_0600(
    monkeypatch: Any, tmp_path: Path
) -> None:
    from sase.core import footprint_facade as facade
    from sase.main import footprint_transfer_handler as handler
    from sase.footprint.transfer import render_packs

    packs = _fixed_packs()
    monkeypatch.setattr("sase.footprint.fold.fold_if_stale", lambda **kwargs: {})
    monkeypatch.setattr(
        facade,
        "footprint_export",
        lambda request, **kwargs: [dict(pack) for pack in packs],
    )
    stub = SimpleNamespace(buffer=io.BytesIO())
    monkeypatch.setattr(sys, "stdout", stub)
    preview_args = argparse.Namespace(output=None, preview=True, weeks=None)
    assert handler.handle_export(preview_args) == 0
    preview_bytes = stub.buffer.getvalue()
    assert preview_bytes == render_packs(packs)
    assert preview_bytes.endswith(b"\n")

    out = tmp_path / "packs.jsonl"
    stub2 = SimpleNamespace(
        buffer=io.BytesIO(), write=lambda text: len(text), flush=lambda: None
    )
    monkeypatch.setattr(sys, "stdout", stub2)
    file_args = argparse.Namespace(output=str(out), preview=False, weeks=None)
    assert handler.handle_export(file_args) == 0
    assert out.read_bytes() == preview_bytes
    assert (out.stat().st_mode & 0o777) == 0o600


def test_real_binding_round_trip_excludes_forbidden(
    monkeypatch: Any, tmp_path: Path
) -> None:
    home = tmp_path / "home1"
    monkeypatch.setenv("SASE_HOME", str(home))
    _build_home(home)

    from sase.core.footprint_facade import footprint_export
    from sase.footprint.transfer import build_export_request, render_packs

    request = build_export_request(None)
    packs = footprint_export(request)
    assert len(packs) >= 1
    for pack in packs:
        assert set(pack.keys()) == PACK_KEYS
        assert pack["schema"] == "sase.footprint.export/1"
        assert pack["os"] == request["os"]
        assert pack["sase"] == request["sase"]
        assert re.fullmatch(r"[0-9]{4}-W[0-9]{2}", str(pack["week"]))
        assert isinstance(pack["nonce"], str) and pack["nonce"]
        for feature in pack["features"]:
            assert feature["n"] in BUCKETS
            feature_id = str(feature["id"])
            assert "~" not in feature_id
            assert "#" not in feature_id
            assert not feature_id.startswith("config:")
            assert not feature_id.startswith("plugin:")
    data = render_packs(packs)
    text = data.decode("utf-8")
    assert text.endswith("\n")
    assert len(text.encode("utf-8")) == len(data)
    for token in _forbidden_tokens(tmp_path):
        assert token not in text


def test_import_replace_all_dry_run_and_bad_file(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    home1 = tmp_path / "home1"
    monkeypatch.setenv("SASE_HOME", str(home1))
    _build_home(home1)

    from sase.core.footprint_facade import footprint_export, footprint_import
    from sase.footprint.query import build_report_request, fetch_report
    from sase.footprint.transfer import build_export_request, render_packs

    packs = footprint_export(build_export_request(None))
    assert packs
    src = tmp_path / "packs.jsonl"
    src.write_bytes(render_packs(packs))

    home2 = tmp_path / "home2"
    store2 = home2 / "footprint" / "footprint.sqlite"
    (home2 / "footprint" / "spool").mkdir(parents=True, exist_ok=True)
    from sase.footprint.catalog import catalog_path
    from sase.core.footprint_facade import footprint_ingest_catalog

    footprint_ingest_catalog(store2, catalog_path(), {}, TODAY)

    def _header() -> dict[str, Any]:
        report = fetch_report(
            build_report_request(
                lens="map",
                actor="everyone",
                window_days=60,
                store_path=store2,
                today=TODAY,
            )
        )
        return dict(report.get("header", {}))

    result = footprint_import(store2, packs, TODAY)
    assert int(result["packs_imported"]) == len(packs)
    header = _header()
    assert int(header.get("imported_pack_count", 0)) == len(packs)
    assert header.get("imported_day")

    reread = footprint_import(store2, packs, TODAY)
    assert int(reread["packs_imported"]) == len(packs)
    assert int(_header().get("imported_pack_count", 0)) == len(packs)

    dry = footprint_import(store2, packs, TODAY, dry_run=True)
    assert dry["dry_run"] is True
    assert int(_header().get("imported_pack_count", 0)) == len(packs)

    bad = tmp_path / "bad.jsonl"
    bad.write_text(
        '{"schema": "sase.footprint.export/1"}\nnot json\n', encoding="utf-8"
    )
    monkeypatch.setenv("SASE_HOME", str(home2))
    from sase.main import footprint_transfer_handler as handler

    args = argparse.Namespace(files=[str(bad)], dry_run=False)
    assert handler.handle_import(args) == 1
    err = capsys.readouterr().err
    assert f"{bad}:2" in err
    assert int(_header().get("imported_pack_count", 0)) == len(packs)


def test_imported_note_renders_only_when_imported() -> None:
    from rich.console import Console

    from sase.footprint.render import (
        card_markdown,
        card_panel,
        header_text,
        report_markdown,
    )

    base = {
        "actor": "everyone",
        "window_days": 60,
        "window_start": "2026-08-28",
        "window_end": TODAY,
        "observed_active_days": {"cli": 35},
        "recording_since": "2026-08-01",
        "gate_met": True,
        "gate_active_days": 35,
        "gate_required_days": 30,
    }
    card: dict[str, Any] = {
        "row": {
            "id": "cli:version",
            "label": "Version",
            "area": "cli.version",
            "kind": "command",
            "ns": "cli",
            "state": "used",
            "days_used": 3,
            "last_used_day": TODAY,
            "uses": {"human": 3},
            "via": {"cli": 3},
        }
    }
    tiles = {
        "used": 1,
        "total": 10,
        "candidates": 0,
        "rare_by_design": 0,
        "agent_only": 0,
        "not_measured": 0,
    }
    empty_headers = [
        dict(base),
        dict(base, imported_pack_count=0, imported_day=None),
    ]
    full = dict(base, imported_pack_count=2, imported_day=TODAY)

    def _console_text(renderable: Any) -> str:
        console = Console(width=200, record=True)
        console.print(renderable)
        return str(console.export_text())

    for header in empty_headers:
        assert "+2 imported" not in _console_text(header_text({"header": header}))
        assert "+2 imported" not in report_markdown(
            {"header": header, "tiles": tiles}, "map"
        )
        assert "+2 imported" not in card_markdown(card, header)
        assert "+2 imported" not in _console_text(card_panel(card, header))
    assert _console_text(header_text({"header": dict(base)})) == _console_text(
        header_text({"header": dict(base, imported_pack_count=0)})
    )

    note = f"+2 imported packs (imported {TODAY})"
    assert note in _console_text(header_text({"header": full}))
    assert note in report_markdown({"header": full, "tiles": tiles}, "map")
    assert note in card_markdown(card, full)
    assert note in _console_text(card_panel(card, full))

    single = dict(base, imported_pack_count=1, imported_day=TODAY)
    assert f"+1 imported pack (imported {TODAY})" in card_markdown(card, single)


def test_build_export_request_rejects_unknown_platform(monkeypatch: Any) -> None:
    import pytest

    from sase.footprint.transfer import build_export_request

    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(ValueError, match="linux and darwin"):
        build_export_request(None)
