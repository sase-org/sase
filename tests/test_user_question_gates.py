"""Command-backed UserQuestion gate coverage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.notification_gates.service import create_gate
from sase.notifications import pending_actions
from sase.notifications.store import load_notifications
from sase.user_question_actions import (
    UserQuestionActionContext,
    UserQuestionActionError,
    execute_user_question_response,
    resolve_user_question_request,
    validate_user_questions,
    user_question_gate_spec,
)
from tests._rust_extension_module_helpers import (
    install_fake_rust_extension,
    override_rust_extension_bindings,
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
    gate = create_gate(
        user_question_gate_spec(
            _questions(),
            session_id="question-session",
            producer={"agent": "test"},
            action_data={"agent_timestamp": "20260716120000"},
        )
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


def test_copy_metadata_is_canonical_in_gate_and_resolved_request(
    question_gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def normalize(value: list[object]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for item in value:
            if isinstance(item, str):
                result.append({"text": item.rstrip("\n")})
            else:
                assert isinstance(item, dict)
                canonical = {"text": item["text"].rstrip("\n")}
                if item.get("label") is not None:
                    canonical["label"] = item["label"].strip()
                result.append(canonical)
        return result

    override_rust_extension_bindings(monkeypatch, normalize_question_copy=normalize)
    questions: list[dict[str, Any]] = [
        {
            "question": "Which setting should I open?",
            "options": [{"label": "Chrome"}],
            "copy": [
                "/Users/bryan/.cargo\n",
                {"label": " Browser ", "text": "chrome://settings"},
            ],
        }
    ]
    spec = user_question_gate_spec(
        questions,
        session_id="copy-contract-session",
        auto_policy_snapshot=None,
    )
    canonical = [
        {
            "question": "Which setting should I open?",
            "options": [{"label": "Chrome"}],
            "copy": [
                {"text": "/Users/bryan/.cargo"},
                {"text": "chrome://settings", "label": "Browser"},
            ],
        }
    ]
    assert spec["payload"]["questions"] == canonical

    gate = create_gate(spec)
    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert envelope["payload"]["questions"] == canonical
    notification = load_notifications()[0]
    resolved = resolve_user_question_request(_context(notification))
    assert resolved.questions == canonical


def test_question_gate_creation_rejects_invalid_copy_with_payload_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def normalize(_value: object) -> None:
        raise ValueError("invalid_question_copy: copy[2].text: must be nonempty")

    override_rust_extension_bindings(monkeypatch, normalize_question_copy=normalize)
    with pytest.raises(UserQuestionActionError) as exc_info:
        user_question_gate_spec(
            [{"question": "Which path?", "copy": ["x"]}],
            session_id="invalid-copy-session",
            auto_policy_snapshot=None,
        )

    assert exc_info.value.code == "invalid_question_copy"
    assert exc_info.value.target == "payload.questions[0].copy[2].text"


def test_gate_validation_rejects_noncanonical_copy_metadata(
    question_gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def normalize(value: list[object]) -> list[dict[str, str]]:
        return [
            {"text": item.rstrip("\n")} if isinstance(item, str) else item
            for item in value
        ]

    override_rust_extension_bindings(monkeypatch, normalize_question_copy=normalize)
    spec = user_question_gate_spec(
        [{"question": "Which path?", "copy": ["/Users/bryan/.cargo"]}],
        session_id="noncanonical-copy-session",
        auto_policy_snapshot=None,
    )
    spec["payload"]["questions"][0]["copy"][0] = "/Users/bryan/.cargo"

    from sase.notification_gates.models import GateError

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "invalid_question_copy"
    assert exc_info.value.target == "payload.questions[0].copy"


def test_legacy_question_read_keeps_damaged_copy_for_tolerant_display(
    question_gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.core.question_copy_facade import display_question_copy_items

    root = question_gate_home / "legacy"
    root.mkdir()
    (root / "question_request.json").write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "question": "Which paths?",
                        "options": [],
                        "copy": ["/Users/bryan/.cargo", {"text": "bad\u001bvalue"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    seen: list[object] = []

    def display(value: object) -> dict[str, object]:
        seen.append(value)
        return {"items": [{"text": "/Users/bryan/.cargo"}], "unavailable": 1}

    install_fake_rust_extension(monkeypatch, display_question_copy=display)
    request = resolve_user_question_request(
        UserQuestionActionContext(
            notification_id=None,
            host_action_data={"response_dir": str(root)},
        )
    )
    questions = validate_user_questions(request.questions)
    assert questions[0]["copy"] == ["/Users/bryan/.cargo", {"text": "bad\u001bvalue"}]

    display_result = display_question_copy_items(questions[0])

    assert seen == [questions[0]["copy"]]
    assert tuple(item.text for item in display_result.items) == ("/Users/bryan/.cargo",)
    assert display_result.unavailable == 1


def test_gate_answer_operation_request_accepts_normalized_question_input(
    question_gate_home: Path,
) -> None:
    from sase.main.gate_handler import handle_gate_command
    from sase.main.parser import create_parser
    from sase.ops import DurableOperationRequest, write_operation_request
    from sase.ops.names import GATE_ANSWER

    gate = create_gate(
        user_question_gate_spec(_questions(), session_id="question-operation-request")
    )
    request_path = question_gate_home / "operation-request.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation=GATE_ANSWER,
            payload={
                "option_ids": ["submit"],
                "input_data": _complete_response(),
                "feedback": "Prefer the durable path",
                "source": "tui",
            },
        ),
    )
    args = create_parser().parse_args(
        [
            "gate",
            "answer",
            "--id",
            "question-operation-request",
            "--kind",
            "question",
            "--no-detach",
            "--json",
            "-Q",
            str(request_path),
        ]
    )

    with pytest.raises(SystemExit) as exit_info:
        handle_gate_command(args)

    assert int(exit_info.value.code or 0) == 0
    response = json.loads(gate.response_path.read_text(encoding="utf-8"))
    assert response["selected_option_ids"] == ["submit"]
    assert response["option_results"] == [
        {"id": "submit", "result": _complete_response()}
    ]


def test_incomplete_question_form_leaves_gate_answerable(
    question_gate_home: Path,
) -> None:
    del question_gate_home
    gate = create_gate(user_question_gate_spec(_questions(), session_id="incomplete"))
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
    create_gate(user_question_gate_spec(_questions(), session_id="duplicate"))
    notification = load_notifications()[0]
    context = _context(notification)

    execute_user_question_response(context, _complete_response(), source="tui")
    with pytest.raises(UserQuestionActionError) as exc_info:
        execute_user_question_response(context, _complete_response(), source="telegram")

    assert exc_info.value.code == "conflict_already_handled"


@pytest.mark.parametrize("profile", ["standard", "tale", "epic", "question_fixture"])
def test_auto_question_uses_first_options_without_publishing_pending_action(
    question_gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
) -> None:
    from sase.autonomy.record import resolve_selection
    from tests.autonomy_contract.harness import (
        question_first_fixture_record,
        write_meta,
    )

    record = (
        question_first_fixture_record()
        if profile == "question_fixture"
        else resolve_selection("" if profile == "standard" else profile)
    )
    write_meta(question_gate_home, {"autonomy": record})
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(question_gate_home))
    gate = create_gate(
        user_question_gate_spec(
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
    )

    if profile != "question_fixture":
        assert gate.notification_id is not None
        assert gate.auto_resolution["policy"]["outcome"] == "ask"
        assert gate.auto_resolution["policy"]["rule"] == "gates.question"
        assert not gate.response_path.exists()
        assert pending_actions.read_pending_action_store()["actions"]
        return

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


def _explicit_auto_question_policy(
    question_gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.autonomy_contract.harness import (
        question_first_fixture_record,
        write_meta,
    )

    write_meta(question_gate_home, {"autonomy": question_first_fixture_record()})
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(question_gate_home))


def _assert_parked_for_human(gate: Any, question_gate_home: Path) -> None:
    del question_gate_home
    # A manual gate is published and the notification is sent: the journal
    # records the manual path, never an automatic outcome.
    assert gate.notification_id is not None
    assert gate.auto_resolution["state"] == "disabled"
    assert not gate.response_path.exists()
    assert load_notifications()
    entry = next(iter(pending_actions.read_pending_action_store()["actions"].values()))
    assert entry["state"] == "available"


def test_option_less_auto_question_parks_for_human(
    question_gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _explicit_auto_question_policy(question_gate_home, monkeypatch)
    gate = create_gate(
        user_question_gate_spec(
            [{"question": "Any constraints?", "options": []}],
            session_id="option-less-auto",
            auto=True,
        )
    )
    _assert_parked_for_human(gate, question_gate_home)

    # The parked gate stays answerable: a human free-text answer settles it.
    notification = load_notifications()[0]
    result = execute_user_question_response(
        _context(notification),
        {
            "answers": [
                {
                    "question": "Any constraints?",
                    "selected": [],
                    "custom_feedback": "Must run offline",
                }
            ],
            "global_note": "",
        },
        source="tui",
    )
    assert result.answers["answers"][0]["custom_feedback"] == "Must run offline"
    assert gate.response_path.exists()


def test_mixed_option_less_auto_question_parks_for_human(
    question_gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _explicit_auto_question_policy(question_gate_home, monkeypatch)
    gate = create_gate(
        user_question_gate_spec(
            [
                {
                    "question": "Database?",
                    "options": [{"label": "SQLite"}, {"label": "PostgreSQL"}],
                },
                {"question": "Any constraints?", "options": []},
            ],
            session_id="mixed-option-less-auto",
            auto=True,
        )
    )
    _assert_parked_for_human(gate, question_gate_home)


def test_turn_backed_question_settles_its_gate_turn_and_streams_output(
    question_gate_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    del question_gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    from sase.axe.run_agent_helpers_artifacts import update_meta_field
    from sase.gate_turn.member import create_gate_turn_member
    from sase.gate_turn.store import read_gate_turn_marker
    from sase.notification_gates.model_turn import GateTurnSpec

    request = user_question_gate_spec(_questions(), session_id="shell-question")
    # No ``next.prompt`` declared: settlement must not attempt a follow-up
    # launch (and its starter-settle wait) for this test to stay fast.
    request["turn"] = {}
    gate = create_gate(request)
    turn = GateTurnSpec.from_mapping(request["turn"], branches=(("submit",),))
    artifacts_dir = create_gate_turn_member(
        "proj",
        {"name": "lane--0", "agent_session": "lane"},
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
        turn=turn,
    )
    update_meta_field(artifacts_dir, "gate_bundle_path", str(gate.bundle_path))

    notification = load_notifications()[0]
    result = execute_user_question_response(
        _context(notification), _complete_response(), source="test_surface"
    )

    assert result.answers == _complete_response()
    record = read_gate_turn_marker("proj", artifacts_dir)
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
    create_gate(user_question_gate_spec(_questions(), session_id="non-shell-question"))
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
