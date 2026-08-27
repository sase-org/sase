"""Command-backed UserQuestion gate coverage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.notifications import pending_actions
from sase.notifications.store import load_notifications
from sase.user_question_actions import (
    UserQuestionActionContext,
    UserQuestionActionError,
    create_user_question_gate,
    execute_user_question_response,
)


@pytest.fixture()
def question_gate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from sase.notification_gates import paths
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
    store._LOAD_CACHE.clear()
    return tmp_path


def _questions() -> list[dict[str, object]]:
    return [
        {
            "question": "Which database?",
            "options": [{"label": "SQLite"}, {"label": "PostgreSQL"}],
        },
        {
            "question": "Which checks?",
            "options": [{"label": "Lint"}, {"label": "Tests"}],
            "multiSelect": True,
        },
        {"question": "Any constraints?", "options": []},
    ]


def _complete_response() -> dict[str, object]:
    return {
        "answers": [
            {
                "question": "Which database?",
                "selected": ["PostgreSQL"],
                "custom_feedback": None,
            },
            {
                "question": "Which checks?",
                "selected": ["Lint", "Tests"],
                "custom_feedback": None,
            },
            {
                "question": "Any constraints?",
                "selected": ["Other"],
                "custom_feedback": "Keep startup under 100ms",
            },
        ],
        "global_note": "Prefer the durable path",
    }


def _context(notification: Any) -> UserQuestionActionContext:
    return UserQuestionActionContext(
        notification_id=str(notification.id),
        host_action_data=dict(notification.action_data),
    )


def test_question_gate_executes_complete_form_and_marks_handled(
    question_gate_home: Path,
) -> None:
    del question_gate_home
    gate = create_user_question_gate(
        _questions(),
        session_id="question-session",
        producer={"agent": "test"},
        action_data={"agent_timestamp": "20260716120000"},
    )
    notification = load_notifications()[0]

    result = execute_user_question_response(
        _context(notification),
        _complete_response(),
        source="test_surface",
    )

    assert result.response_file == "response.json"
    assert result.answers == _complete_response()
    assert result.response_json["selected_option_ids"] == ["submit"]
    assert result.response_json["option_results"] == [
        {"id": "submit", "result": _complete_response()}
    ]
    assert result.response_json["feedback"] == "Prefer the durable path"
    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert envelope["payload"]["questions"] == _questions()
    assert envelope["query"] == "submit"
    assert envelope["primary_branch"] == ["submit"]
    assert envelope["options"][0]["icon"] == "✅"
    assert envelope["options"][0]["command"]["argv"] == ["commands/submit"]
    entry = next(iter(pending_actions.read_pending_action_store()["actions"].values()))
    assert entry["state"] == "already_handled"


def test_incomplete_question_form_leaves_gate_answerable(
    question_gate_home: Path,
) -> None:
    del question_gate_home
    gate = create_user_question_gate(_questions(), session_id="incomplete")
    notification = load_notifications()[0]

    with pytest.raises(UserQuestionActionError) as exc_info:
        execute_user_question_response(
            _context(notification),
            {
                "answers": [
                    {
                        "question": "Which database?",
                        "selected": [],
                        "custom_feedback": None,
                    }
                ],
                "global_note": "",
            },
        )

    assert exc_info.value.code == "incomplete_question_form"
    assert not gate.response_path.exists()
    entry = next(iter(pending_actions.read_pending_action_store()["actions"].values()))
    assert entry["state"] == "available"


def test_cross_surface_duplicate_question_answer_is_write_once(
    question_gate_home: Path,
) -> None:
    del question_gate_home
    create_user_question_gate(_questions(), session_id="duplicate")
    notification = load_notifications()[0]
    context = _context(notification)

    execute_user_question_response(context, _complete_response(), source="tui")
    with pytest.raises(UserQuestionActionError) as exc_info:
        execute_user_question_response(context, _complete_response(), source="telegram")

    assert exc_info.value.code == "conflict_already_handled"


def test_auto_question_uses_first_options_without_publishing_pending_action(
    question_gate_home: Path,
) -> None:
    del question_gate_home
    gate = create_user_question_gate(
        [
            {
                "question": "Database?",
                "options": [{"label": "SQLite"}, {"label": "PostgreSQL"}],
            },
            {
                "question": "Checks?",
                "options": [{"label": "Lint"}, {"label": "Tests"}],
                "multiSelect": True,
            },
        ],
        session_id="automatic",
        auto=True,
    )

    assert gate.notification_id is None
    response = json.loads(gate.response_path.read_text(encoding="utf-8"))
    assert response["option_results"][0]["result"] == {
        "answers": [
            {
                "question": "Database?",
                "selected": ["SQLite"],
                "custom_feedback": None,
            },
            {
                "question": "Checks?",
                "selected": ["Lint"],
                "custom_feedback": None,
            },
        ],
        "global_note": "",
    }
    assert load_notifications(include_dismissed=True) == []
    assert pending_actions.read_pending_action_store()["actions"] == {}


def test_shell_backed_question_settles_its_gate_shell_and_streams_output(
    question_gate_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    del question_gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    from sase.axe.run_agent_helpers_artifacts import update_meta_field
    from sase.gate_shell.member import create_gate_shell_member
    from sase.gate_shell.store import read_gate_shell_marker
    from sase.notification_gates.model_shell import GateShellSpec
    from sase.notification_gates.service import create_gate
    from sase.user_question_actions import user_question_gate_spec

    request = user_question_gate_spec(_questions(), session_id="shell-question")
    # No ``next.prompt`` declared: settlement must not attempt a follow-up
    # launch (and its starter-settle wait) for this test to stay fast.
    request["shell"] = {}
    gate = create_gate(request)
    shell = GateShellSpec.from_mapping(request["shell"], branches=(("submit",),))
    artifacts_dir = create_gate_shell_member(
        "proj",
        {"name": "lane--0", "agent_family": "lane"},
        lane="lane",
        suffix="--gate",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=None,
        gate_id="shell-question",
        gate_kind="question",
        label="Question",
        reason="wait for reviewer",
        creator_agent="lane--0",
        timeout_seconds=86400.0,
        request_fingerprint=None,
        shell=shell,
    )
    update_meta_field(artifacts_dir, "gate_bundle_path", str(gate.bundle_path))

    notification = load_notifications()[0]
    result = execute_user_question_response(
        _context(notification), _complete_response(), source="test_surface"
    )

    assert result.answers == _complete_response()
    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None
    assert record.gate_state == "answered"
    assert (Path(artifacts_dir) / "gate_decision.md").exists()
    log_text = (Path(artifacts_dir) / "gate.log").read_text(encoding="utf-8")
    assert "commands/submit" in log_text


def test_non_shell_question_answers_exactly_as_today(
    question_gate_home: Path,
) -> None:
    """A gate with no ``shell`` block never touches gate-shell machinery."""
    del question_gate_home
    create_user_question_gate(_questions(), session_id="non-shell-question")
    notification = load_notifications()[0]

    result = execute_user_question_response(
        _context(notification), _complete_response(), source="test_surface"
    )

    assert result.answers == _complete_response()


def test_ace_and_mobile_answering_surfaces_route_through_the_chokepoint() -> None:
    """ACE and mobile both funnel through the one shell-settling function."""
    from pathlib import Path as _Path

    ace_source = _Path(
        "src/sase/ace/tui/actions/agents/_notification_question_modal.py"
    ).read_text(encoding="utf-8")
    mobile_source = _Path(
        "src/sase/integrations/_mobile_notification_actions.py"
    ).read_text(encoding="utf-8")
    assert "execute_user_question_response" in ace_source
    assert "execute_user_question_response" in mobile_source
