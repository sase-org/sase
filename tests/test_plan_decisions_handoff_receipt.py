"""Receipt tests for Plan Decisions handoff.

Split from ``tests.test_plan_decisions_handoff``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

__all__ = [
    "test_auto_receipt_hook_wires_values_and_label",
    "test_receipt_only_posts_with_decisions",
]


def test_receipt_only_posts_with_decisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.sdd.plan_decision_handoff import RECEIPT_TAG, post_auto_approval_receipt

    notifications_dir = tmp_path / "notifications"
    notifications_file = notifications_dir / "notifications.jsonl"
    monkeypatch.setattr(
        "sase.notifications.store.NOTIFICATIONS_DIR", str(notifications_dir)
    )
    monkeypatch.setattr(
        "sase.notifications.store.NOTIFICATIONS_FILE", str(notifications_file)
    )

    assert (
        post_auto_approval_receipt(request_id="r1", plan_label="tale · x", sheet={})
        is False
    )
    assert (
        post_auto_approval_receipt(
            request_id="r1", plan_label="tale · x", sheet={"rows": []}
        )
        is False
    )
    sheet = {
        "count": 2,
        "memory_count": 1,
        "changed_count": 1,
        "review_revision": 0,
        "rows": [
            {
                "id": "grouping",
                "kind": "choice",
                "ask": "How group?",
                "why": "pane keeps order",
                "choices": [
                    {"key": "pane", "label": "By pane"},
                    {"key": "mode", "label": "By mode"},
                ],
                "default": "pane",
                "value": "pane",
                "changed": False,
            },
            {
                "id": "tui_note",
                "kind": "toggle",
                "ask": "Record?",
                "why": None,
                "choices": [],
                "default": True,
                "value": True,
                "changed": False,
                "memory": {
                    "selectors": ["tui.md"],
                    "provenance": "asked",
                    "quote": "and note the convention",
                },
            },
        ],
    }
    assert (
        post_auto_approval_receipt(
            request_id="req-1", plan_label="tale · keymap_help_overlay", sheet=sheet
        )
        is True
    )
    from sase.notifications.store import load_notifications

    rows = load_notifications()
    assert len(rows) == 1
    receipt = rows[0]
    assert RECEIPT_TAG in receipt.tags
    assert receipt.silent is True
    assert receipt.action is None
    assert receipt.dedup_key == "plan-decisions-receipt-req-1"
    assert receipt.notes[0] == "\U0001f916 Auto-approved tale · keymap_help_overlay"
    assert any("grouping = pane \u2605 (auto)" in note for note in receipt.notes)
    assert any("\U0001f9e0 tui.md" in note for note in receipt.notes)


def test_auto_receipt_hook_wires_values_and_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.notification_gates.adapter_plan import _post_plan_auto_receipt_best_effort

    bundle = tmp_path / "req-9"
    bundle.mkdir()
    envelope = {
        "payload": {
            "decisions": [{"id": "grouping"}],
            "original_plan_file": "/plans/keymap_help_overlay.md",
        }
    }
    response = {
        "source": "auto_resolution",
        "option_inputs": {
            "approve": {"decision_grouping": "mode"},
            "commit": {"decision_grouping": "mode"},
        },
    }
    calls: list[dict[str, object]] = []

    def fake_post(**kwargs: object) -> bool:
        calls.append(dict(kwargs))
        return True

    monkeypatch.setattr(
        "sase.sdd.plan_decision_handoff.post_auto_approval_receipt", fake_post
    )
    monkeypatch.setattr(
        "sase.sdd.plan_decisions.sheet_binding",
        lambda definitions, values: {"rows": [{"id": "grouping"}]},
    )

    _post_plan_auto_receipt_best_effort(
        "plan", bundle, envelope, response, ("approve", "commit")
    )
    assert len(calls) == 1
    assert calls[0]["request_id"] == "req-9"
    assert calls[0]["plan_label"] == "tale · keymap_help_overlay.md"

    calls.clear()
    manual = dict(response)
    manual["source"] = "plan_response"
    _post_plan_auto_receipt_best_effort(
        "plan", bundle, envelope, manual, ("approve", "commit")
    )
    assert calls == []

    calls.clear()
    nodecisions = {"payload": {}}
    _post_plan_auto_receipt_best_effort(
        "plan", bundle, nodecisions, response, ("approve", "commit")
    )
    assert calls == []
