"""Tests for human-facing axe chop command rendering."""

from __future__ import annotations

from rich.console import Console

from sase.axe.chop_render import render_chop_run_result


def test_chop_run_result_reuses_structured_report_renderer() -> None:
    console = Console(record=True, width=80)
    result = {
        "status": "ok",
        "summary": "one warning",
        "counters": {"warnings": 1},
        "report": {
            "title": "AUDIT",
            "blocks": [
                {"kind": "headline", "text": "Review one finding", "tone": "warn"}
            ],
        },
    }

    render_chop_run_result(
        result,
        [],
        dry_run=True,
        verbose=False,
        console=console,
    )

    output = console.export_text()
    assert "AUDIT" in output
    assert "Review one finding" in output
