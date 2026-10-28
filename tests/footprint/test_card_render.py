"""Rust-free coverage for the Footprint evidence card panels."""

from __future__ import annotations

from rich.console import Console

from sase.footprint.render import area_card_panel, card_panel


def _plain(renderable: object) -> str:
    console = Console(width=100, color_system=None)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def _feature_card() -> dict[str, object]:
    return {
        "row": {
            "id": "cli:bead.list",
            "label": "bead list",
            "ns": "cli",
            "area": "cli.bead",
            "kind": "command",
            "state": "used",
            "uses": {"human": 9, "agent": 4, "automation": 0},
            "days_used": 5,
            "last_used_day": "2026-10-27",
            "last_used_actor": "human",
            "via": {"cli": 13},
            "loc": 520,
            "protected": None,
            "decision": None,
            "decision_reason": None,
            "coverage_incomplete": False,
        },
        "daily_series": [{"day": "2026-10-27", "n": 3, "measured": True}],
        "first_in_catalog": "2026-08-01",
        "last_in_catalog": "2026-10-27",
        "parent": None,
        "children": [],
        "retire_with": [],
        "area_summary": None,
    }


def _area_summary() -> dict[str, object]:
    return {
        "area": "cli.bead",
        "ns": "cli",
        "total": 10,
        "used": 6,
        "used_pct": 60,
        "recency_7d": 2,
        "recency_30d": 2,
        "recency_window": 2,
        "recency_none": 3,
        "recency_not_measured": 1,
        "unused_by_loc": [
            {
                "id": "cli:bead.close",
                "label": "bead close",
                "ns": "cli",
                "area": "cli.bead",
                "kind": "command",
                "loc": 210,
            },
        ],
    }


def test_area_card_panel_shows_totals_and_largest_unused() -> None:
    rendered = _plain(area_card_panel(_area_summary(), {}))
    assert "6/10 used · 60%" in rendered
    assert "recency ≤7d 2" in rendered
    assert "Largest unused by LOC" in rendered
    assert "cli:bead.close" in rendered
    assert "210 LOC" in rendered


def test_area_card_panel_empty_area_has_honest_copy() -> None:
    summary = _area_summary()
    summary["unused_by_loc"] = []
    rendered = _plain(area_card_panel(summary, {}))
    assert "No unused features in this area." in rendered


def test_feature_card_panel_renders_evidence_and_carries() -> None:
    rendered = _plain(card_panel(_feature_card(), {"actor": "you"}))
    assert "bead list" in rendered
    assert "cli:bead.list" in rendered
    assert "○ undecided" in rendered
