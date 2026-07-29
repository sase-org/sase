"""Tests for the universal AXE chop RESULT card and composition cache."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.widgets import _axe_chop_result_card as result_card
from sase.ace.tui.widgets._axe_dashboard_output import AxeOutputSection

from ._axe_dashboard_helpers import _entry


def test_result_card_renders_counters_launches_evidence_and_report() -> None:
    entry = _entry("rich")
    entry.dry_run = True
    entry.source = "manual"
    entry.result = {
        "summary": "one fix proposed",
        "reason": "CI was red",
        "counters": {"green": 4, "red": 1},
        "evidence": ["reports/ci.json"],
        "report": {
            "title": "CI WATCH",
            "blocks": [{"kind": "headline", "text": "4 green", "tone": "ok"}],
        },
    }
    entry.proposals = [{"index": 0, "agent_name": "ci_fix", "clan": "ci"}]
    entry.launches = [{"index": 0, "agent_name": "ci_fix", "clan": "ci"}]

    plain = result_card.render_cached_chop_card_and_report(
        "hooks", "fast", entry, width=80
    ).plain

    for expected in (
        "RESULT",
        "✓ success",
        "1 proposal",
        "1 launch",
        "dry run",
        "manual",
        "one fix proposed",
        "green 4",
        "red 1",
        "ci_fix · ci",
        "ci.json",
        "CI WATCH",
        "4 green",
    ):
        assert expected in plain


def test_check_error_card_surfaces_error_and_traceback() -> None:
    entry = _entry("failed", status="check_error")
    entry.error = "validation failed"
    entry.traceback = "Traceback: bad result"

    plain = result_card.render_cached_chop_card_and_report("hooks", "fast", entry).plain

    assert "! check error" in plain
    assert "validation failed" in plain
    assert "Traceback: bad result" in plain


def test_card_cache_key_changes_when_run_status_changes() -> None:
    result_card._card_report_cache.clear()
    entry = _entry("live", status="running", finished_at=None)

    running = result_card.render_cached_chop_card_and_report("hooks", "fast", entry)
    entry.status = "success"
    entry.finished_at = "2026-05-11T12:35:00"
    finished = result_card.render_cached_chop_card_and_report("hooks", "fast", entry)

    assert "running" in running.plain
    assert "success" in finished.plain
    assert len(result_card._card_report_cache) == 2


def test_output_composition_without_report_has_result_and_ansi_output() -> None:
    entry = _entry("plain")
    entry.result = {"summary": "plain chop"}
    captured: dict[str, Text] = {}

    class _Section:
        def update(self, content: Text) -> None:
            captured["content"] = content

    AxeOutputSection.update_chop_run(
        _Section(),  # type: ignore[arg-type]
        "hooks",
        "fast",
        entry,
        "\x1b[32mall good\x1b[0m\n",
        width=70,
    )

    rendered = captured["content"]
    assert "RESULT" in rendered.plain
    assert "OUTPUT · 1 line" in rendered.plain
    assert "all good" in rendered.plain
    assert "\x1b" not in rendered.plain
    assert "REPORT" not in rendered.plain
