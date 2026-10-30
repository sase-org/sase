"""Flag-gated staging behavior for ``sase questions``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.pending_handoff import QUESTIONS_PENDING_MARKER
from sase.agent.pending_handoff_write import write_pending_handoff_marker
from sase.agent.staged_handoff import (
    STAGED_HANDOFF_FILENAME,
    STAGING_RESERVATION_FILENAME,
)
from sase.feature_flags import override_flags
from sase.main.questions_command_handler import handle_questions_command

_QUESTIONS = json.dumps(
    [{"question": "Pick one", "options": [{"label": "A"}, {"label": "B"}]}]
)


def _prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    return artifacts


def test_flag_enabled_questions_stage_without_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifacts = _prepare(tmp_path, monkeypatch)
    with (
        override_flags(staged_handoffs=True),
        patch("sase.main.questions_command_handler.kill_agent_runner_group") as kill,
        pytest.raises(SystemExit) as staged_exit,
    ):
        handle_questions_command(_QUESTIONS)

    assert staged_exit.value.code == 0
    kill.assert_not_called()
    assert not (artifacts / QUESTIONS_PENDING_MARKER).exists()
    assert not (artifacts / STAGING_RESERVATION_FILENAME).exists()
    record = json.loads(
        (artifacts / STAGED_HANDOFF_FILENAME).read_text(encoding="utf-8")
    )
    assert record["kind"] == "questions"
    assert record["successor_workspace"] == "inherit"
    assert record["carry_allowed"] is True
    assert record["payload"]["questions"][0]["question"] == "Pick one"
    output = capsys.readouterr().out
    assert output.startswith("Staged")
    assert "Nothing starts until this turn ends" in output
    assert "`/sase_final`" in output


def test_flag_disabled_questions_keeps_legacy_marker_and_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _prepare(tmp_path, monkeypatch)
    with (
        override_flags(staged_handoffs=False),
        patch(
            "sase.main.questions_command_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ) as kill,
        pytest.raises(SystemExit) as exc,
    ):
        handle_questions_command(_QUESTIONS)

    assert exc.value.code == 0
    kill.assert_called_once_with(str(artifacts))
    assert (artifacts / QUESTIONS_PENDING_MARKER).is_file()
    assert not (artifacts / STAGED_HANDOFF_FILENAME).exists()


def test_invalid_json_releases_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _prepare(tmp_path, monkeypatch)
    with (
        override_flags(staged_handoffs=True),
        pytest.raises(SystemExit) as exc,
    ):
        handle_questions_command("{not-json")

    assert exc.value.code == 1
    assert not (artifacts / STAGING_RESERVATION_FILENAME).exists()
    assert not (artifacts / STAGED_HANDOFF_FILENAME).exists()


def test_accepted_declaration_refuses_before_questions_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _prepare(tmp_path, monkeypatch)
    with (
        override_flags(staged_handoffs=True),
        patch(
            "sase.agent._staged_handoff_admission._has_accepted_current_final_submission",
            return_value=True,
        ),
        pytest.raises(SystemExit) as exc,
    ):
        handle_questions_command(_QUESTIONS)

    assert exc.value.code == 1
    assert not (artifacts / STAGING_RESERVATION_FILENAME).exists()
    assert not (artifacts / STAGED_HANDOFF_FILENAME).exists()


def test_existing_handoff_refuses_questions_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _prepare(tmp_path, monkeypatch)
    write_pending_handoff_marker(
        QUESTIONS_PENDING_MARKER,
        {"questions": [{"question": "already pending"}]},
        artifacts_dir=str(artifacts),
    )
    with (
        override_flags(staged_handoffs=True),
        pytest.raises(SystemExit) as exc,
    ):
        handle_questions_command(_QUESTIONS)

    assert exc.value.code == 1
    assert not (artifacts / STAGED_HANDOFF_FILENAME).exists()
    marker = json.loads(
        (artifacts / QUESTIONS_PENDING_MARKER).read_text(encoding="utf-8")
    )
    assert marker["questions"][0]["question"] == "already pending"
