"""Agent-ready rendering of locally marked Footprint review decisions."""

from __future__ import annotations

from sase.footprint.render import review_markdown


def test_review_markdown_carries_keep_reason_and_cut_evidence() -> None:
    report = {
        "header": {"window_start": "2026-08-28", "window_end": "2026-10-27"},
        "rows": [
            {
                "id": "cli:keep",
                "label": "Keep command",
                "area": "cli.demo",
                "kind": "command",
                "state": "no_recorded_use",
                "decision": "keep",
                "decision_reason": "rare_by_design",
                "uses": {"human": 0, "agent": 1, "automation": 0},
                "days_used": 1,
                "last_used_day": "2026-10-20",
                "loc": 42,
            },
            {
                "id": "cli:later",
                "label": "Later command",
                "area": "cli.demo",
                "kind": "command",
                "state": "no_recorded_use",
                "decision": "later",
                "uses": {"human": 0, "agent": 0, "automation": 0},
                "days_used": 0,
                "loc": None,
            },
            {
                "id": "cli:cut",
                "label": "Cut command",
                "area": "cli.demo",
                "kind": "command",
                "state": "no_recorded_use",
                "decision": "cut",
                "uses": {"human": 0, "agent": 0, "automation": 0},
                "days_used": 0,
                "loc": 17,
            },
        ],
    }

    markdown = review_markdown(report)

    assert "1 keep · 1 later · 1 cut" in markdown
    assert "Keep reason: `rare_by_design`" in markdown
    assert "## `cli:cut` — Cut command" in markdown
    assert "## `cli:later` — Later command" in markdown
