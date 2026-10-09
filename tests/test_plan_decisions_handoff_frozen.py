"""Frozen-definition tests for Plan Decisions handoff.

Split from ``tests.test_plan_decisions_handoff``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FROZEN_MEMORY_TALE = """---
tier: tale
title: Frozen memory tale
goal: Cover frozen rendering.
size: small
decisions:
  tui_note:
    ask: Record conventions in the tui memory note?
    memory: [tui.md]
    requested: "please also update the tui memory note"
    default: true
    answer: true
decided_by: reviewer
decided_via: tui
---
# Plan

Body mentions tui_note.
"""

__all__ = [
    "FROZEN_MEMORY_TALE",
    "test_accepted_frozen_definitions_ignore_reader_env",
    "test_accepted_synthetic_fallback_uses_authored_default",
    "test_frozen_resolved_path_survives_tmp_load",
]


def _write_frozen_sibling(plan_path: Path, definitions: list[dict]) -> None:
    import json as _json

    sibling = plan_path.parent / f"{plan_path.stem}.plan-decisions.json"
    sibling.write_text(
        _json.dumps({"schema": 1, "definitions": definitions}, indent=2) + "\n",
        encoding="utf-8",
    )


def _frozen_memory_definitions() -> list[dict]:
    return [
        {
            "id": "tui_note",
            "kind": "toggle",
            "ask": "Record conventions in the tui memory note?",
            "default": True,
            "effective_default": True,
            "memory": {"selectors": ["tui.md"]},
            "provenance": "asked",
            "requested_verified": True,
            "resolved": [
                {
                    "selector": "tui.md",
                    "kind": "note",
                    "scope": "project",
                    "path": "sase/memory/tui.md",
                    "type": "reference",
                    "exists": True,
                }
            ],
            "quote": "please also update the tui memory note",
        }
    ]


def test_accepted_frozen_definitions_ignore_reader_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.sdd._plan_display_decisions import (
        accepted_decisions_text,
        decision_text_lines,
    )
    from sase.sdd.plan_decision_handoff import load_stamped_decisions

    plan_path = tmp_path / "frozen.md"
    plan_path.write_text(FROZEN_MEMORY_TALE, encoding="utf-8")
    _write_frozen_sibling(plan_path, _frozen_memory_definitions())
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.chdir("/tmp")
    stamped = load_stamped_decisions(plan_path)
    assert stamped is not None
    rows = stamped.sheet.get("rows")
    assert isinstance(rows, list) and len(rows) == 1
    memory = rows[0].get("memory")
    assert isinstance(memory, dict)
    assert memory.get("provenance") == "asked"
    resolved = memory.get("resolved")
    assert isinstance(resolved, list) and resolved
    assert resolved[0].get("path") == "sase/memory/tui.md"
    assert rows[0].get("value") is True
    assert rows[0].get("changed") is False
    lines = decision_text_lines(
        accepted_decisions_text(stamped.sheet, stamped.decided_by, stamped.decided_via)
    )
    from sase.sdd._plan_display_decisions import provenance_chip as _chip

    assert _chip("asked") == "you asked"
    assert any("\u2605" in line for line in lines)


def test_accepted_synthetic_fallback_uses_authored_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.sdd.plan_decision_handoff import load_stamped_decisions

    plan_path = tmp_path / "synthetic.md"
    plan_path.write_text(FROZEN_MEMORY_TALE, encoding="utf-8")
    sibling = plan_path.parent / f"{plan_path.stem}.plan-decisions.json"
    assert not sibling.exists()
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.chdir("/tmp")
    stamped = load_stamped_decisions(plan_path)
    assert stamped is not None
    rows = stamped.sheet.get("rows")
    assert isinstance(rows, list) and len(rows) == 1
    assert rows[0].get("value") is True
    assert rows[0].get("changed") is False
    text = str(stamped.sheet)
    assert "quote_not_found" not in text
    assert "quote not found" not in text.lower()


def test_frozen_resolved_path_survives_tmp_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.sdd.plan_decision_handoff import load_stamped_decisions

    plan_path = tmp_path / "kept.md"
    plan_path.write_text(FROZEN_MEMORY_TALE, encoding="utf-8")
    _write_frozen_sibling(plan_path, _frozen_memory_definitions())
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.chdir("/tmp")
    stamped = load_stamped_decisions(plan_path)
    assert stamped is not None
    rows = stamped.sheet.get("rows")
    assert isinstance(rows, list)
    memory = rows[0].get("memory")
    assert isinstance(memory, dict)
    resolved = memory.get("resolved")
    assert isinstance(resolved, list)
    assert any(
        isinstance(item, dict) and item.get("path") == "sase/memory/tui.md"
        for item in resolved
    )
