"""Presentation for durable ToolRun failure triage (``sase-18j.10.1``)."""

from __future__ import annotations

from sase.tool.triage_display import footer_triage_lines, show_triage_lines


def test_stage_line_renders_continued_and_stopped() -> None:
    triage = {
        "triaged": True,
        "stages": [
            {
                "stage_key": "lint (mypy)",
                "extraction_status": "parsed",
                "decision": {"decision": "continue"},
            },
            {
                "stage_key": "test (scoped)",
                "extraction_status": "parsed",
                "decision": {"decision": "stop"},
            },
        ],
        "items": [],
    }
    lines, _verdict = footer_triage_lines(triage, exit_code=1)
    assert lines[0] == "triage lint (mypy): parsed continued"
    assert lines[1] == "triage test (scoped): parsed stopped"
    assert "stopd" not in "\n".join(lines)


def test_show_and_footer_surface_run_facts_diagnostics() -> None:
    triage = {
        "triaged": False,
        "run_facts": {"diagnostics": ["triage owner candidates timed out"]},
        "diagnostics": [],
        "stages": [],
        "items": [],
    }
    footer, verdict = footer_triage_lines(triage, exit_code=1)
    assert footer == ["triage unavailable: triage owner candidates timed out"]
    assert verdict is None
    shown = show_triage_lines(triage)
    assert "  DIAG     triage owner candidates timed out" in shown
