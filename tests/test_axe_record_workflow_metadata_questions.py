"""Tests for question-response metadata persistence in record_workflow_metadata.

When ``handle_questions_marker()`` records a question handoff it passes the
``question_request_path``, ``question_response_path``, and
``question_session_id`` for the answered round. The interrupted artifact must
keep those fields so a completed question row is never reclassified as an
unanswered question (which left rows stuck showing ``QUESTION`` after the user
had already answered).
"""

import json
from unittest.mock import patch

from sase.axe.run_agent_exec_plan import record_workflow_metadata

_QUESTION_RELATIONSHIPS = {
    "questions_submitted_at": "2026-06-17T12:00:05.027993+00:00",
    "question_request_path": "/home/u/.sase/user_question/abc/question_request.json",
    "question_response_path": "/home/u/.sase/user_question/abc/question_response.json",
    "question_session_id": "abc",
    "changespec_name": "sase",
}


def _write_meta(tmp_path) -> str:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "92.f1--code", "role_suffix": "--code"}),
        encoding="utf-8",
    )
    return str(artifacts)


def test_record_workflow_metadata_persists_question_response_paths(tmp_path) -> None:
    """The interrupted artifact retains all three question-response fields."""
    artifacts_dir = _write_meta(tmp_path)

    with patch(
        "sase.axe.run_agent_helpers_artifacts."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        record_workflow_metadata(artifacts_dir, dict(_QUESTION_RELATIONSHIPS))

    meta = json.loads((tmp_path / "artifacts" / "agent_meta.json").read_text())
    assert (
        meta["question_request_path"]
        == (_QUESTION_RELATIONSHIPS["question_request_path"])
    )
    assert (
        meta["question_response_path"]
        == (_QUESTION_RELATIONSHIPS["question_response_path"])
    )
    assert meta["question_session_id"] == "abc"
    assert (
        meta["questions_submitted_at"]
        == (_QUESTION_RELATIONSHIPS["questions_submitted_at"])
    )


def test_record_workflow_metadata_drops_empty_question_fields(tmp_path) -> None:
    """Empty/None question fields are not written (allow-list still filters)."""
    artifacts_dir = _write_meta(tmp_path)

    with patch(
        "sase.axe.run_agent_helpers_artifacts."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        record_workflow_metadata(
            artifacts_dir,
            {
                "questions_submitted_at": "2026-06-17T12:00:05.027993+00:00",
                "question_request_path": None,
                "question_response_path": "",
                "question_session_id": None,
            },
        )

    meta = json.loads((tmp_path / "artifacts" / "agent_meta.json").read_text())
    assert "question_request_path" not in meta
    assert "question_response_path" not in meta
    assert "question_session_id" not in meta
    assert meta["questions_submitted_at"] == "2026-06-17T12:00:05.027993+00:00"


def test_handle_questions_marker_persists_response_paths_on_interrupted_dir(
    tmp_path,
) -> None:
    """handle_questions_marker writes response metadata to the interrupted dir.

    The interrupted (asking) artifact is ``state.current_artifacts_dir`` at the
    time the marker is handled. After the user answers, that dir must carry the
    response paths so the asking row is self-describing.
    """
    from sase.axe.run_agent_exec_questions import handle_questions_marker
    from tests._axe_run_agent_exec_plan_helpers import make_ctx, make_state

    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    interrupted_dir = tmp_path / "code_phase"
    interrupted_dir.mkdir()
    (interrupted_dir / "agent_meta.json").write_text(
        json.dumps({"name": "92.f1--code", "role_suffix": "--code"}),
        encoding="utf-8",
    )
    state.current_artifacts_dir = str(interrupted_dir)

    session_dir = tmp_path / "user_question" / "abc"
    response = {
        "answers": [],
        "global_note": "",
        "_question_request_path": str(session_dir / "question_request.json"),
        "_question_response_path": str(session_dir / "question_response.json"),
        "_question_session_id": "abc",
    }

    patches = {
        "sase.axe.run_agent_exec_questions.normalize_handoff_interruption_state": None,
        "sase.axe.run_agent_exec_questions.finalize_handoff_artifacts_as_completed": (
            None
        ),
        "sase.axe.run_agent_exec_questions.reset_killed": None,
        "sase.axe.run_agent_exec_questions.update_step_marker_chat_path": None,
        "sase.axe.run_agent_exec_questions.create_followup_artifacts": (
            lambda *a, **kw: "/tmp/followup"
        ),
        "sase.axe.run_agent_exec_questions.promote_to_workflow": None,
        "sase.axe.run_agent_exec_questions._store_followup_prompt_artifact": None,
        "sase.history.chat.save_chat_history": lambda **kw: "/fake/chat",
        "sase.history.chat_extras.format_extra_sections": lambda *a: "",
        "sase.axe.run_agent_helpers_artifacts."
        "update_agent_artifact_index_for_marker_mutation": None,
    }

    from contextlib import ExitStack

    with ExitStack() as stack:
        for target, side_effect in patches.items():
            stack.enter_context(
                patch(target, side_effect=side_effect) if side_effect else patch(target)
            )
        stack.enter_context(
            patch(
                "sase.axe.run_agent_exec_questions.handle_questions_flow",
                return_value=response,
            )
        )
        outcome = handle_questions_marker({"questions": []}, ctx, state)

    assert outcome is None
    meta = json.loads((interrupted_dir / "agent_meta.json").read_text())
    assert meta["question_request_path"] == str(session_dir / "question_request.json")
    assert meta["question_response_path"] == str(session_dir / "question_response.json")
    assert meta["question_session_id"] == "abc"
