"""Notes rendered for the enriched usage-limit disable notification.

``usage_limit_drain_report_notes`` reads the exact JSON envelope
``sase agent drain --json`` prints (see ``tests/test_agent_drain_cli.py``),
so these fixtures mirror ``_move_json``/``_skip_json``/``_result_json``
shapes rather than constructing the dataclasses directly.
"""

from __future__ import annotations

from typing import Any

from sase.agents._drain_render import usage_limit_drain_report_notes


def _move(name: str, target_provider: str = "codex") -> dict[str, Any]:
    return {
        "name": name,
        "presented_name": name,
        "project": "gh_sase-org__sase",
        "project_display": None,
        "status": "RUNNING",
        "route": {
            "kind": "reroute",
            "target_provider": target_provider,
            "target_model": "gpt-5",
        },
    }


def _result(name: str, status: str = "ok") -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "stopped": {},
        "launched": None,
        "recovery_dir": None,
        "recovery_command": None,
        "renamed_to": None,
        "error": None,
    }


def _skip(name: str, reason: str, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "presented_name": name,
        "status": "FAILED",
        "reason": reason,
        "detail": detail,
    }


def test_missing_payload_reports_that_the_drain_did_not_finish() -> None:
    assert usage_limit_drain_report_notes(None) == [
        "Drain did not finish; see the drain proc log for details."
    ]


def test_empty_moves_and_skips_reports_nothing_found() -> None:
    payload = {"moves": [], "skips": [], "results": []}
    assert usage_limit_drain_report_notes(payload) == [
        "Drain found no agents on this provider to relaunch or leave alone."
    ]


def test_relaunched_line_groups_by_target_provider_and_lists_names() -> None:
    payload = {
        "moves": [_move("sase-mf"), _move("ace-01", target_provider="gemini")],
        "skips": [],
        "results": [_result("sase-mf"), _result("ace-01")],
    }
    notes = usage_limit_drain_report_notes(payload)
    assert notes == ["Relaunched 2 agent(s) on CODEX and GEMINI: sase-mf, ace-01"]


def test_relaunched_line_truncates_long_name_lists() -> None:
    names = [f"agent-{i}" for i in range(7)]
    payload = {
        "moves": [_move(name) for name in names],
        "skips": [],
        "results": [_result(name) for name in names],
    }
    notes = usage_limit_drain_report_notes(payload)
    assert len(notes) == 1
    assert "agent-0, agent-1, agent-2, agent-3, agent-4, +2 more" in notes[0]
    assert "Relaunched 7 agent(s) on CODEX" in notes[0]


def test_relaunched_line_when_no_move_completed() -> None:
    payload = {
        "moves": [_move("sase-mf")],
        "skips": [],
        "results": [_result("sase-mf", status="kill_failed")],
    }
    notes = usage_limit_drain_report_notes(payload)
    assert notes == ["Relaunch attempted for 1 agent(s); none completed."]


def test_left_alone_line_groups_by_reason_and_sorts() -> None:
    payload = {
        "moves": [],
        "skips": [
            _skip(
                "nine",
                "stranded",
                "pinned to claude/opus; not reachable from any enabled provider",
            ),
            _skip("rq.3", "pending_question", "holding a pending question; a restart"),
        ],
        "results": [],
    }
    notes = usage_limit_drain_report_notes(payload)
    assert notes == [
        "Left alone: 1 waiting on a question (rq.3), 1 pinned to claude/opus (nine)"
    ]


def test_left_alone_line_uses_known_reason_labels() -> None:
    payload = {
        "moves": [],
        "skips": [
            _skip("mon-1", "monitor", "monitor rows supervise a shell command"),
            _skip("mon-2", "monitor", "monitor rows supervise a shell command"),
            _skip("cap-1", "capped", "dropped by --limit 20"),
        ],
        "results": [],
    }
    notes = usage_limit_drain_report_notes(payload)
    assert notes == [
        "Left alone: 1 dropped by --limit (cap-1), 2 supervising a command "
        "(mon-1, mon-2)"
    ]


def test_both_relaunched_and_left_alone_lines_are_reported() -> None:
    payload = {
        "moves": [_move("sase-mf")],
        "skips": [
            _skip(
                "nine",
                "stranded",
                "pinned to claude/opus; not reachable from any enabled provider",
            )
        ],
        "results": [_result("sase-mf")],
    }
    notes = usage_limit_drain_report_notes(payload)
    assert notes == [
        "Relaunched 1 agent(s) on CODEX: sase-mf",
        "Left alone: 1 pinned to claude/opus (nine)",
    ]
