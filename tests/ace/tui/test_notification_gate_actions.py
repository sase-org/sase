"""The plan edit round trip ACE actually performs, against a real bundle.

These tests exist because the ACE edit action used to open the *bundle copy*
of the plan and then overwrite the durable file on approval. What is asserted
here is the corrected contract: the editor opens the file under
``~/.sase/plans/``, the edit is accepted only when the plan validates, and a
rejected edit stays in the durable file as a reported draft.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._notification_gate_actions import (
    NotificationGateActionRunner,
    load_gate_actions,
)
from sase.notification_gates import paths
from sase.notification_gates.service import create_gate
from sase.notifications import pending_actions
from sase.notifications.store import load_notifications
from sase.plan_gate import PLAN_EDIT_OPERATION_ID, build_plan_approval_gate_spec
from tests.plan_validation_helpers import VALID_TALE_PLAN


@pytest.fixture()
def gate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from sase.notifications import store

    monkeypatch.setattr(paths, "INTERACTION_REQUESTS_DIR", tmp_path / "requests")
    monkeypatch.setattr(store, "NOTIFICATIONS_DIR", str(tmp_path / "notifications"))
    monkeypatch.setattr(
        store,
        "NOTIFICATIONS_FILE",
        str(tmp_path / "notifications" / "notifications.jsonl"),
    )
    monkeypatch.setattr(
        pending_actions, "PENDING_ACTIONS_PATH", tmp_path / "pending.json"
    )
    monkeypatch.setattr(
        pending_actions,
        "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH",
        tmp_path / "legacy.json",
    )
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    store._LOAD_CACHE.clear()
    return tmp_path


class _SuspendingApp:
    """The two things a gate action runner uses from the app."""

    def __init__(self) -> None:
        self.suspended = 0

    def suspend(self) -> Any:
        app = self

        class _Suspension:
            def __enter__(self) -> None:
                app.suspended += 1

            def __exit__(self, *_exc: object) -> bool:
                return False

        return _Suspension()


def _edited_by(monkeypatch: pytest.MonkeyPatch, replacement: str) -> list[list[str]]:
    """Stand in for ``$EDITOR``, recording what it opened and rewriting it."""
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(list(argv))
        Path(argv[-1]).write_text(replacement, encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_gate_actions.subprocess.run",
        fake_run,
    )
    return calls


def _plan_gate(gate_home: Path) -> tuple[Path, Path, Any]:
    plan = gate_home / "tale.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    create_gate(build_plan_approval_gate_spec(plan, "gate-actions-ace"))
    [notification] = load_notifications()
    bundle = Path(str(notification.action_data["bundle_path"]))
    return plan, bundle, notification


def _runner(
    app: object, notification: Any, bundle: Path
) -> NotificationGateActionRunner:
    envelope = json.loads((bundle / "request.json").read_text())
    actions = load_gate_actions(bundle, envelope)
    return NotificationGateActionRunner(
        app=app,
        notification=notification,
        bundle_path=bundle,
        operations=actions.operations,
    )


def test_plan_gate_declares_its_edit_action_with_no_draft_pending(
    gate_home: Path,
) -> None:
    _plan, bundle, _notification = _plan_gate(gate_home)
    envelope = json.loads((bundle / "request.json").read_text())

    actions = load_gate_actions(bundle, envelope)

    [operation] = actions.operations
    assert operation.id == PLAN_EDIT_OPERATION_ID
    assert operation.kind == "edit_file"
    assert operation.edit_target == "origin"
    assert operation.key == "e"
    assert actions.draft_operation_id is None


def test_edit_action_opens_the_durable_plan_and_accepts_a_valid_edit(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, bundle, notification = _plan_gate(gate_home)
    revised = VALID_TALE_PLAN.replace("# Plan", "# Plan\n\nRevised by the reviewer.", 1)
    opened = _edited_by(monkeypatch, revised)
    app = _SuspendingApp()
    runner = _runner(app, notification, bundle)

    outcome = runner.run_edit(PLAN_EDIT_OPERATION_ID)

    # The editor opened the durable file, not the bundle copy.
    assert [Path(call[-1]) for call in opened] == [plan]
    assert app.suspended == 1
    assert outcome.accepted
    assert not outcome.draft
    assert outcome.content is not None and "Revised by the reviewer." in outcome.content
    assert (bundle / "plan.md").read_text(encoding="utf-8") == revised
    assert (
        load_gate_actions(
            bundle, json.loads((bundle / "request.json").read_text())
        ).draft_operation_id
        is None
    )


def test_edit_action_can_be_repeated_without_answering_the_gate(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plan, bundle, notification = _plan_gate(gate_home)
    runner = _runner(_SuspendingApp(), notification, bundle)

    for marker in ("first pass", "second pass"):
        _edited_by(
            monkeypatch, VALID_TALE_PLAN.replace("# Plan", f"# Plan\n\n{marker}")
        )
        assert runner.run_edit(PLAN_EDIT_OPERATION_ID).accepted

    assert "second pass" in (bundle / "plan.md").read_text(encoding="utf-8")
    assert not (bundle / "response.json").exists()


def test_a_rejected_edit_is_reported_as_a_draft_and_keeps_the_reviewed_plan(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, bundle, notification = _plan_gate(gate_home)
    reviewed = (bundle / "plan.md").read_text(encoding="utf-8")
    _edited_by(monkeypatch, "not a valid plan at all\n")
    runner = _runner(_SuspendingApp(), notification, bundle)

    outcome = runner.run_edit(PLAN_EDIT_OPERATION_ID)

    assert not outcome.accepted
    assert outcome.draft
    assert outcome.message
    # The gate keeps its last accepted revision; the draft survives for a retry.
    assert (bundle / "plan.md").read_text(encoding="utf-8") == reviewed
    assert plan.read_text(encoding="utf-8") == "not a valid plan at all\n"
    actions = load_gate_actions(
        bundle, json.loads((bundle / "request.json").read_text())
    )
    assert actions.draft_operation_id == PLAN_EDIT_OPERATION_ID
    assert actions.draft_path is not None


def test_discarding_the_draft_restores_the_durable_plan(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, bundle, notification = _plan_gate(gate_home)
    reviewed = (bundle / "plan.md").read_text(encoding="utf-8")
    _edited_by(monkeypatch, "not a valid plan at all\n")
    runner = _runner(_SuspendingApp(), notification, bundle)
    runner.run_edit(PLAN_EDIT_OPERATION_ID)

    outcome = runner.discard_draft(PLAN_EDIT_OPERATION_ID)

    assert outcome.accepted
    assert plan.read_text(encoding="utf-8") == reviewed
    assert (
        load_gate_actions(
            bundle, json.loads((bundle / "request.json").read_text())
        ).draft_operation_id
        is None
    )
