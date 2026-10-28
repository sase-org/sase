"""Tests for the Footprint report commands and shared render layer."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from sase.footprint.query import (
    build_card_request,
    build_report_request,
    fetch_card,
    fetch_report,
    parse_range_days,
)
from sase.footprint.render import (
    activity_strip,
    evidence_sentence,
    heat_strip,
)

TODAY = "2026-10-27"
OLD_DAY = "2026-08-01"

_OVERLAY = {
    "schema": "sase.footprint.overlay/1",
    "features": {"cli:demo.rare": {"protected": "recovery", "why": "test seed"}},
    "retire_with": [],
}


def _write_catalog(path: Path, entries: list[dict[str, Any]]) -> None:
    body = "".join(json.dumps(entry, separators=(",", ":")) + "\n" for entry in entries)
    rev = sha256(body.encode("utf-8")).hexdigest()[:12]
    path.write_text(
        json.dumps(
            {"schema": "sase.footprint.catalog/1", "rev": rev, "count": len(entries)}
        )
        + "\n"
        + body,
        encoding="utf-8",
    )


def _entry(feature_id: str, ns: str, area: str) -> dict[str, Any]:
    return {
        "id": feature_id,
        "ns": ns,
        "area": area,
        "kind": "command",
        "label": feature_id,
        "parent": None,
        "src": None,
    }


def _ledger(tmp_path: Path) -> Path:
    """Build a gate-met ledger: 35 active days, catalog since August."""
    from sase.core.footprint_facade import footprint_fold, footprint_ingest_catalog

    store = tmp_path / "footprint.sqlite"
    if store.exists():
        return store
    spool = tmp_path / "spool"
    spool.mkdir(exist_ok=True)
    catalog = tmp_path / "catalog.jsonl"
    _write_catalog(
        catalog,
        [
            _entry("cli:demo.alpha", "cli", "cli.demo"),
            _entry("cli:demo.beta", "cli", "cli.demo"),
            _entry("cli:demo.rare", "cli", "cli.demo"),
            _entry("plugin:listen", "plugin", "plugins"),
        ],
    )
    footprint_ingest_catalog(store, catalog, {"cli:demo.alpha": 40}, OLD_DAY)
    start = date.fromisoformat("2026-09-20")
    for offset in range(35):
        day = (start + timedelta(days=offset)).isoformat()
        (spool / f"{day}.jsonl").write_text(
            json.dumps(
                {
                    "s": 1,
                    "d": day,
                    "f": "cli:demo.alpha",
                    "a": "human",
                    "v": "cli",
                    "o": "ok",
                    "n": 1,
                    "ms": 5,
                    "ver": "0.18.1",
                }
            )
            + "\n",
            encoding="utf-8",
        )
    folded = footprint_fold(store, spool, TODAY, 90, 400)
    assert folded["records_folded"] == 35
    # A late catalog addition stays too new for the candidate gate.
    _write_catalog(
        catalog,
        [
            _entry("cli:demo.alpha", "cli", "cli.demo"),
            _entry("cli:demo.beta", "cli", "cli.demo"),
            _entry("cli:demo.rare", "cli", "cli.demo"),
            _entry("plugin:listen", "plugin", "plugins"),
            _entry("cli:demo.newbie", "cli", "cli.demo"),
        ],
    )
    footprint_ingest_catalog(store, catalog, {"cli:demo.alpha": 40}, "2026-10-20")
    return store


def _report(tmp_path: Path, lens: str, **kwargs: Any) -> dict[str, Any]:
    store = _ledger(tmp_path)
    return fetch_report(
        build_report_request(
            lens=lens,
            actor="you",
            window_days=60,
            store_path=store,
            today=TODAY,
            overlay=_OVERLAY,
            **kwargs,
        )
    )


def test_parse_range_days() -> None:
    assert parse_range_days("60d") == 60
    assert parse_range_days("4w") == 28
    assert parse_range_days("all") is None
    assert parse_range_days(None) == 60
    for bad in ("0d", "-3d", "soon", "10x", ""):
        with pytest.raises(ValueError):
            parse_range_days(bad)


@pytest.mark.parametrize(
    "lens",
    [
        "map",
        "cold",
        "fading",
        "agent-only",
        "dead-paths",
        "friction",
        "hot",
        "coverage",
        "decisions",
    ],
)
def test_each_lens_returns_wire_shape(tmp_path: Path, lens: str) -> None:
    report = _report(tmp_path, lens)
    assert report["schema_version"] == 1
    assert report["header"]["actor"] == "you"
    assert report["header"]["window_days"] == 60
    assert isinstance(report["tiles"], dict)
    assert isinstance(report["areas"], list)
    assert isinstance(report["rows"], list)
    assert isinstance(report["coverage"], list)
    if lens == "map":
        assert report["areas"]
    if lens == "coverage":
        assert report["coverage"]


def test_cold_lens_finds_candidate_and_skips_decided(tmp_path: Path) -> None:
    from sase.core.footprint_facade import footprint_decide

    store = _ledger(tmp_path)
    cold = fetch_report(
        build_report_request(
            lens="cold", store_path=store, today=TODAY, overlay=_OVERLAY
        )
    )
    assert cold["header"]["gate_met"] is True
    ids = [row["id"] for row in cold["rows"]]
    assert "cli:demo.beta" in ids
    assert "cli:demo.rare" not in ids
    assert "plugin:listen" not in ids

    footprint_decide(store, "cli:demo.beta", "keep", "agent_facing", TODAY)
    cold_after = fetch_report(
        build_report_request(
            lens="cold", store_path=store, today=TODAY, overlay=_OVERLAY
        )
    )
    assert "cli:demo.beta" not in [row["id"] for row in cold_after["rows"]]
    decisions = fetch_report(
        build_report_request(
            lens="decisions", store_path=store, today=TODAY, overlay=_OVERLAY
        )
    )
    assert "cli:demo.beta" in [row["id"] for row in decisions["rows"]]


def test_evidence_states_cover_fixture(tmp_path: Path) -> None:
    report = _report(tmp_path, "hot")
    by_id = {row["id"]: row for row in report["rows"]}
    assert by_id["cli:demo.alpha"]["state"] == "used"
    cold = _report(tmp_path, "cold")
    assert cold["rows"] and all(
        row["state"] == "no_recorded_use" for row in cold["rows"]
    )
    demo_rows = _report(tmp_path, "map", area="cli.demo")["rows"]
    plugin_rows = _report(tmp_path, "map", area="plugins")["rows"]
    states = {row["state"] for row in demo_rows + plugin_rows}
    assert {"not_measured", "too_new", "rare_by_design"} <= states


def test_heat_strip_scales_with_width() -> None:
    area = {
        "area": "cli.demo",
        "total": 21,
        "used": 3,
        "recency_7d": 2,
        "recency_30d": 1,
        "recency_window": 0,
        "recency_none": 18,
        "recency_not_measured": 0,
    }
    for width in (12, 24, 48):
        assert len(heat_strip(area, width=width).plain) == width
    narrow = heat_strip(area, width=12).plain
    assert "█" in narrow and "▓" in narrow
    single = {
        "area": "cli.demo",
        "total": 221,
        "used": 1,
        "recency_7d": 1,
        "recency_30d": 0,
        "recency_window": 0,
        "recency_none": 220,
        "recency_not_measured": 0,
    }
    assert heat_strip(single, width=36).plain.startswith("█")


def test_activity_strip_keeps_final_day() -> None:
    series = [
        {"day": f"2026-10-{day:02d}", "n": 0, "measured": day % 2 == 0}
        for day in range(1, 28)
    ]
    series.append({"day": "2026-10-28", "n": 4, "measured": True})
    assert activity_strip(series, width=52).plain.endswith("█")
    assert activity_strip(series[:60], width=52).plain.count("·") >= 1


def test_evidence_sentence_states_its_denominator() -> None:
    header = {
        "actor": "you",
        "gate_active_days": 35,
        "gate_required_days": 30,
        "observed_active_days": {"cli": 41, "plugin": 0},
    }
    cases = [
        (
            {
                "id": "cli:a",
                "ns": "cli",
                "state": "used",
                "days_used": 5,
                "last_used_day": "2026-10-20",
            },
            "5 of 41 observed active days",
        ),
        (
            {"id": "cli:b", "ns": "cli", "state": "no_recorded_use"},
            "across 41 observed active days",
        ),
        (
            {
                "id": "cli:c",
                "ns": "cli",
                "state": "rare_by_design",
                "protected": "recovery",
            },
            "Rare by design (recovery)",
        ),
        (
            {"id": "cli:d", "ns": "cli", "state": "too_new"},
            "Too new",
        ),
        (
            {"id": "plugin:listen", "ns": "plugin", "state": "not_measured"},
            "Not measured",
        ),
        (
            {"id": "cli:e", "ns": "cli", "state": "retired"},
            "Retired",
        ),
    ]
    for row, fragment in cases:
        assert fragment in evidence_sentence(row, header)
    qualified = evidence_sentence(
        {
            "id": "cli:b",
            "ns": "cli",
            "state": "no_recorded_use",
            "coverage_incomplete": True,
            "decision": "keep",
            "decision_reason": "agent_facing",
        },
        header,
    )
    assert "incomplete" in qualified and "Decision: keep (agent_facing)" in qualified


def test_decide_round_trips_through_facade(tmp_path: Path) -> None:
    from sase.footprint.query import record_decision

    store = tmp_path / "footprint.sqlite"
    kept = record_decision(
        "cli:demo.beta",
        "keep",
        "agent_facing",
        store_path=store,
        today=TODAY,
    )
    assert kept["decision"] == "keep"
    card = fetch_card(
        build_card_request(
            target="cli:demo.beta", store_path=store, today=TODAY, overlay=_OVERLAY
        )
    )
    assert card["row"]["decision"] == "keep"
    cleared = record_decision(
        "cli:demo.beta", "clear", None, store_path=store, today=TODAY
    )
    assert cleared["decision"] is None


def test_list_renders_all_formats(monkeypatch, tmp_path: Path, capsys) -> None:
    from sase.main.footprint_handler import _handle_list
    import sase.footprint.query as query

    store = _ledger(tmp_path)
    monkeypatch.setattr("sase.footprint.fold.fold_if_stale", lambda *args, **kwargs: {})

    real_build = query.build_report_request
    monkeypatch.setattr(
        query,
        "build_report_request",
        lambda **kwargs: real_build(
            store_path=store, today=TODAY, overlay=_OVERLAY, **kwargs
        ),
    )
    for fmt, lens in (("json", "cold"), ("markdown", "cold"), ("rich", "map")):
        args = argparse.Namespace(
            format=fmt, lens=lens, actor="you", range="60d", area=None
        )
        assert _handle_list(args) == 0
        output = capsys.readouterr().out
        if fmt == "json":
            assert json.loads(output)["header"]["actor"] == "you"
        elif fmt == "markdown":
            assert output.startswith("# Footprint") and "`cli:demo.beta`" in output
        else:
            assert "FOOTPRINT" in output
            assert "PREVIEW" in output or "READY" in output


def test_show_renders_all_formats(monkeypatch, tmp_path: Path, capsys) -> None:
    from sase.main.footprint_handler import _handle_show
    import sase.footprint.query as query

    store = _ledger(tmp_path)
    monkeypatch.setattr("sase.footprint.fold.fold_if_stale", lambda *args, **kwargs: {})
    real_card = query.build_card_request
    real_build = query.build_report_request
    monkeypatch.setattr(
        query,
        "build_card_request",
        lambda **kwargs: real_card(
            store_path=store, today=TODAY, overlay=_OVERLAY, **kwargs
        ),
    )
    monkeypatch.setattr(
        query,
        "build_report_request",
        lambda **kwargs: real_build(
            store_path=store, today=TODAY, overlay=_OVERLAY, **kwargs
        ),
    )
    for fmt in ("json", "markdown", "rich"):
        args = argparse.Namespace(
            format=fmt, actor="you", range="60d", feature_id="cli:demo.alpha"
        )
        assert _handle_show(args) == 0
        output = capsys.readouterr().out
        if fmt == "json":
            assert json.loads(output)["row"]["id"] == "cli:demo.alpha"
        elif fmt == "markdown":
            assert output.startswith("# `cli:demo.alpha`")
        else:
            assert "cli:demo.alpha" in output


def test_show_area_card_and_unknown_feature(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    from sase.main.footprint_handler import _handle_show
    import sase.footprint.query as query

    store = _ledger(tmp_path)
    monkeypatch.setattr("sase.footprint.fold.fold_if_stale", lambda *args, **kwargs: {})
    real_card = query.build_card_request
    real_build = query.build_report_request
    monkeypatch.setattr(
        query,
        "build_card_request",
        lambda **kwargs: real_card(
            store_path=store, today=TODAY, overlay=_OVERLAY, **kwargs
        ),
    )
    monkeypatch.setattr(
        query,
        "build_report_request",
        lambda **kwargs: real_build(
            store_path=store, today=TODAY, overlay=_OVERLAY, **kwargs
        ),
    )
    area_args = argparse.Namespace(
        format="json", actor="you", range="60d", feature_id="cli.demo"
    )
    assert _handle_show(area_args) == 0
    assert json.loads(capsys.readouterr().out)["area_summary"]["area"] == "cli.demo"
    missing = argparse.Namespace(
        format="rich", actor="you", range="60d", feature_id="cli:nope.missing"
    )
    assert _handle_show(missing) == 1
    assert "Could not read Footprint card" in capsys.readouterr().err


def test_decide_handler_rejects_bad_id(capsys) -> None:
    from sase.main.footprint_handler import _handle_decide

    args = argparse.Namespace(feature_id="NOT VALID", decision="keep", reason=None)
    assert _handle_decide(args) == 2
    assert "invalid feature ID" in capsys.readouterr().err


def test_report_options_are_registered() -> None:
    from sase.main.parser import create_parser

    parser = create_parser()
    listed = parser.parse_args(
        [
            "footprint",
            "list",
            "-a",
            "agents",
            "-A",
            "cli.bead",
            "-f",
            "json",
            "-l",
            "cold",
            "-r",
            "all",
        ]
    )
    assert (listed.actor, listed.area, listed.format, listed.lens) == (
        "agents",
        "cli.bead",
        "json",
        "cold",
    )
    assert listed.range == "all"
    shown = parser.parse_args(["footprint", "show", "cli:bead.list", "-r", "4w"])
    assert (shown.feature_id, shown.range) == ("cli:bead.list", "4w")
    decided = parser.parse_args(
        ["footprint", "decide", "cli:bead.list", "cut", "-r", "other"]
    )
    assert (decided.feature_id, decided.decision, decided.reason) == (
        "cli:bead.list",
        "cut",
        "other",
    )
    assert create_parser().parse_args(["footprint"]).footprint_subcommand == "list"
