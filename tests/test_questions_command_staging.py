"""Unconditional staging behavior for ``sase questions``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from tests._legacy_handoff_markers import write_legacy_handoff_marker

from sase.agent.pending_handoff import QUESTIONS_PENDING_MARKER
from sase.agent.staged_handoff import (
    STAGED_HANDOFF_FILENAME,
    STAGING_RESERVATION_FILENAME,
)
from sase.main.questions_command_handler import handle_questions_command
from tests._rust_extension_module_helpers import override_rust_extension_bindings

_QUESTIONS = json.dumps(
    [{"question": "Pick one", "options": [{"label": "A"}, {"label": "B"}]}]
)


def _prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    return artifacts


def test_questions_stage_without_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifacts = _prepare(tmp_path, monkeypatch)
    with (
        pytest.raises(SystemExit) as staged_exit,
    ):
        handle_questions_command(_QUESTIONS)

    assert staged_exit.value.code == 0
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


def test_questions_stage_canonical_copy_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _prepare(tmp_path, monkeypatch)

    def normalize(value: list[object]) -> list[dict[str, str]]:
        result = []
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
    payload = [
        {
            "question": "Where should the setting point?",
            "copy": [
                "/Users/bryan/.cargo\n",
                {"label": "Chrome", "text": "chrome://settings"},
            ],
        }
    ]
    with pytest.raises(SystemExit) as staged_exit:
        handle_questions_command(json.dumps(payload))

    assert staged_exit.value.code == 0
    record = json.loads(
        (artifacts / STAGED_HANDOFF_FILENAME).read_text(encoding="utf-8")
    )
    assert record["payload"]["questions"][0]["copy"] == [
        {"text": "/Users/bryan/.cargo"},
        {"text": "chrome://settings", "label": "Chrome"},
    ]


def test_invalid_copy_refuses_staging_with_question_relative_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifacts = _prepare(tmp_path, monkeypatch)

    def normalize(_value: object) -> None:
        raise ValueError(
            "invalid_question_copy: copy[3].text: contains control character U+001B"
        )

    override_rust_extension_bindings(monkeypatch, normalize_question_copy=normalize)
    payload = json.dumps([{"question": "Where?", "copy": ["bad"]}])
    with pytest.raises(SystemExit) as exit_info:
        handle_questions_command(payload)

    assert exit_info.value.code == 1
    assert not (artifacts / STAGED_HANDOFF_FILENAME).exists()
    assert not (artifacts / STAGING_RESERVATION_FILENAME).exists()
    assert (
        "Error: Invalid questions schema: question[0].copy[3].text:"
        in capsys.readouterr().err
    )


def test_invalid_json_releases_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _prepare(tmp_path, monkeypatch)
    with (
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
    write_legacy_handoff_marker(
        QUESTIONS_PENDING_MARKER,
        {"questions": [{"question": "already pending"}]},
        artifacts_dir=str(artifacts),
    )
    with (
        pytest.raises(SystemExit) as exc,
    ):
        handle_questions_command(_QUESTIONS)

    assert exc.value.code == 1
    assert not (artifacts / STAGED_HANDOFF_FILENAME).exists()
    marker = json.loads(
        (artifacts / QUESTIONS_PENDING_MARKER).read_text(encoding="utf-8")
    )
    assert marker["questions"][0]["question"] == "already pending"
