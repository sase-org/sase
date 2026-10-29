"""Flag-gated staging behavior for ``sase plan propose``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.pending_handoff import PLAN_PENDING_MARKER
from sase.agent.pending_handoff_write import write_pending_handoff_marker
from sase.agent.staged_handoff import (
    STAGED_HANDOFF_FILENAME,
    STAGING_RESERVATION_FILENAME,
)
from sase.feature_flags import override_flags
from sase.main import plan_command_handler
from sase.llm_provider import _plan_utils
from tests.conftest import redirect_sase_home
from tests.plan_command_handler_helpers import (
    VALID_TALE,
    clear_bead_work_association_env,
    invoke_plan,
    make_artifacts_dir,
)


@pytest.fixture(autouse=True)
def _clear_bead_work_association_env_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_bead_work_association_env(monkeypatch)


def _prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path]:
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = make_artifacts_dir(sase_home)
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(VALID_TALE, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    return artifacts_dir, plan_file, sase_home


def test_flag_enabled_proposal_stages_after_reserving_before_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifacts_dir, plan_file, _sase_home = _prepare(tmp_path, monkeypatch)
    original_move = _plan_utils.move_plan_to_sase

    def assert_reserved_before_archive(path: str) -> Path:
        assert (artifacts_dir / STAGING_RESERVATION_FILENAME).is_file()
        return original_move(path)

    with (
        override_flags(staged_handoffs=True),
        patch.object(
            _plan_utils,
            "move_plan_to_sase",
            side_effect=assert_reserved_before_archive,
        ),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
        patch("sase.main.plan_propose_handler.kill_agent_runner_group") as kill,
    ):
        with pytest.raises(SystemExit) as staged_exit:
            plan_command_handler.handle_plan_propose_command(str(plan_file))

    assert staged_exit.value.code == 0
    kill.assert_not_called()
    assert not plan_file.exists()
    assert not (artifacts_dir / PLAN_PENDING_MARKER).exists()
    assert not (artifacts_dir / STAGING_RESERVATION_FILENAME).exists()

    record = json.loads(
        (artifacts_dir / STAGED_HANDOFF_FILENAME).read_text(encoding="utf-8")
    )
    assert record["kind"] == "plan"
    assert record["successor_workspace"] == "none"
    assert record["carry_allowed"] is False
    assert Path(record["payload"]["plan_file"]).is_file()
    assert record["payload"]["original_file"] == str(plan_file)
    output = capsys.readouterr().out
    assert output.startswith("Staged")
    assert "Nothing starts until this turn ends" in output
    assert "`/sase_final`" in output


def test_flag_disabled_proposal_keeps_legacy_marker_and_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir, plan_file, _sase_home = _prepare(tmp_path, monkeypatch)

    with (
        override_flags(staged_handoffs=False),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ) as kill,
    ):
        assert invoke_plan(plan_file) == 0

    kill.assert_called_once_with(str(artifacts_dir))
    assert (artifacts_dir / PLAN_PENDING_MARKER).is_file()
    assert not (artifacts_dir / STAGED_HANDOFF_FILENAME).exists()
    assert not (artifacts_dir / STAGING_RESERVATION_FILENAME).exists()


def test_staging_reservation_is_released_on_preparation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir, plan_file, _sase_home = _prepare(tmp_path, monkeypatch)

    with (
        override_flags(staged_handoffs=True),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=OSError("formatter unavailable"),
        ),
        pytest.raises(OSError, match="formatter unavailable"),
    ):
        plan_command_handler.handle_plan_propose_command(str(plan_file))

    assert plan_file.read_text(encoding="utf-8") == VALID_TALE
    assert not (artifacts_dir / STAGING_RESERVATION_FILENAME).exists()
    assert not (artifacts_dir / STAGED_HANDOFF_FILENAME).exists()


def test_accepted_declaration_refuses_before_plan_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir, plan_file, _sase_home = _prepare(tmp_path, monkeypatch)

    with (
        override_flags(staged_handoffs=True),
        patch(
            "sase.agent.staged_handoff._has_accepted_current_final_submission",
            return_value=True,
        ),
        patch("sase.main.plan_propose_handler._validate_plan_text") as validate,
        pytest.raises(SystemExit) as exc_info,
    ):
        plan_command_handler.handle_plan_propose_command(str(plan_file))

    assert exc_info.value.code == 1
    validate.assert_not_called()
    assert plan_file.read_text(encoding="utf-8") == VALID_TALE
    assert not (artifacts_dir / STAGING_RESERVATION_FILENAME).exists()
    assert not (artifacts_dir / STAGED_HANDOFF_FILENAME).exists()


def test_existing_handoff_refuses_before_plan_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir, plan_file, _sase_home = _prepare(tmp_path, monkeypatch)
    write_pending_handoff_marker(
        PLAN_PENDING_MARKER,
        {"plan_file": "existing.md"},
        artifacts_dir=str(artifacts_dir),
    )

    with (
        override_flags(staged_handoffs=True),
        patch("sase.main.plan_propose_handler._validate_plan_text") as validate,
        pytest.raises(SystemExit) as exc_info,
    ):
        plan_command_handler.handle_plan_propose_command(str(plan_file))

    assert exc_info.value.code == 1
    validate.assert_not_called()
    assert plan_file.read_text(encoding="utf-8") == VALID_TALE
    assert not (artifacts_dir / STAGING_RESERVATION_FILENAME).exists()
    assert not (artifacts_dir / STAGED_HANDOFF_FILENAME).exists()
