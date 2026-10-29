"""Host storage, guards, and flag coverage for staged handoffs."""

from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest

from sase.agent.pending_handoff import PLAN_PENDING_MARKER, has_pending_handoff
from sase.agent.pending_handoff_write import (
    PendingHandoffError,
    handoff_guard,
    write_pending_handoff_marker,
)
from sase.agent.staged_handoff import (
    STAGED_HANDOFF_FILENAME,
    STAGED_HANDOFF_RECEIPT_FILENAME,
    STAGED_HANDOFF_RESPONSE_FILENAME,
    STAGING_RESERVATION_FILENAME,
    StagedHandoffError,
    _has_accepted_current_final_submission,
    acquire_staging_reservation,
    build_plan_staged_record,
    discard_staged_handoff,
    occupying_handoff_names,
    read_adoption_receipt,
    read_staged_handoff,
    read_staged_handoff_response,
    receipt_authorizes,
    release_staging_reservation,
    staged_handoffs_enabled,
    write_adoption_receipt,
    write_staged_handoff,
    write_staged_handoff_response,
)
from sase.feature_flags import override_flags
from sase.feature_flags.registry import FeatureFlag, feature_flag_definitions
from sase.finalizers.declaration import (
    FINAL_SUBMISSION_FILENAME,
    final_submission_is_current,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.owned_turn import SASE_FINALIZER_OWNED_TURN_ENV

from tests.finalizer_declaration_channel_test_helpers import (
    clean_state,
    persist_default_plan,
    prepare_agent_env,
    prepare_dirty_declaration,
    valid_manifest,
)


def _agent_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.delenv(SASE_FINALIZER_OWNED_TURN_ENV, raising=False)
    monkeypatch.delenv("SASE_NATIVE_HELPER", raising=False)


def _plan_record(tmp_path: Path) -> dict[str, object]:
    return build_plan_staged_record(
        plan_file=str(tmp_path / "archive.md"),
        original_file=str(tmp_path / "scratch.md"),
        dirty_obligations_at_stage=[],
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        created_at="2026-10-28T12:00:00Z",
    )


def test_flag_is_default_off_beta_with_generated_bead() -> None:
    definition = feature_flag_definitions()[FeatureFlag.staged_handoffs]
    assert definition.kind == "beta"
    assert definition.default is False
    assert definition.bead == "sase-1pk"


def test_flag_disabled_keeps_legacy_protocol(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_env(monkeypatch, tmp_path)
    with override_flags(staged_handoffs=False):
        assert staged_handoffs_enabled() is False
        path = write_pending_handoff_marker(
            PLAN_PENDING_MARKER,
            {"plan_file": str(tmp_path / "plan.md")},
            artifacts_dir=str(tmp_path),
        )
        assert path.is_file()
        assert has_pending_handoff(str(tmp_path)) is True
        assert read_staged_handoff(str(tmp_path)) is None


def test_flag_enabled_exposes_staging_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_env(monkeypatch, tmp_path)
    with override_flags(staged_handoffs=True):
        assert staged_handoffs_enabled() is True
        path = write_staged_handoff(_plan_record(tmp_path), artifacts_dir=str(tmp_path))
        assert path.name == STAGED_HANDOFF_FILENAME
        assert has_pending_handoff(str(tmp_path)) is False
        record = read_staged_handoff(str(tmp_path))
        assert record is not None
        assert record["kind"] == "plan"


def test_write_and_read_round_trip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_env(monkeypatch, tmp_path)
    record = _plan_record(tmp_path)
    write_staged_handoff(record, artifacts_dir=str(tmp_path))
    assert read_staged_handoff(str(tmp_path)) == record


def test_malformed_staged_record_is_refusal_not_absence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_env(monkeypatch, tmp_path)
    (tmp_path / STAGED_HANDOFF_FILENAME).write_text("{", encoding="utf-8")
    with pytest.raises(StagedHandoffError, match="malformed"):
        read_staged_handoff(str(tmp_path))
    assert occupying_handoff_names(str(tmp_path)) == (STAGED_HANDOFF_FILENAME,)


def test_reservation_is_not_a_valid_staged_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_env(monkeypatch, tmp_path)
    reservation_id = acquire_staging_reservation(
        artifacts_dir=str(tmp_path), command="sase plan propose"
    )
    assert (tmp_path / STAGING_RESERVATION_FILENAME).is_file()
    assert read_staged_handoff(str(tmp_path)) is None
    with pytest.raises(PendingHandoffError, match=STAGING_RESERVATION_FILENAME):
        handoff_guard(command="sase plan propose")
    write_staged_handoff(
        _plan_record(tmp_path),
        artifacts_dir=str(tmp_path),
        reservation_id=reservation_id,
    )
    assert not (tmp_path / STAGING_RESERVATION_FILENAME).exists()
    assert read_staged_handoff(str(tmp_path)) is not None


def test_release_reservation_on_pre_stage_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_env(monkeypatch, tmp_path)
    reservation_id = acquire_staging_reservation(artifacts_dir=str(tmp_path))
    release_staging_reservation(reservation_id, artifacts_dir=str(tmp_path))
    assert not (tmp_path / STAGING_RESERVATION_FILENAME).exists()
    assert handoff_guard() == str(tmp_path)


def test_legacy_writer_refuses_staged_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_env(monkeypatch, tmp_path)
    write_staged_handoff(_plan_record(tmp_path), artifacts_dir=str(tmp_path))
    with pytest.raises(PendingHandoffError, match=STAGED_HANDOFF_FILENAME):
        write_pending_handoff_marker(
            PLAN_PENDING_MARKER,
            {"plan_file": "x"},
            artifacts_dir=str(tmp_path),
        )


def test_staged_writer_refuses_legacy_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_env(monkeypatch, tmp_path)
    write_pending_handoff_marker(
        PLAN_PENDING_MARKER,
        {"plan_file": "x"},
        artifacts_dir=str(tmp_path),
    )
    with pytest.raises(StagedHandoffError, match=PLAN_PENDING_MARKER):
        write_staged_handoff(_plan_record(tmp_path), artifacts_dir=str(tmp_path))


def test_handoff_guard_refuses_staged_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_env(monkeypatch, tmp_path)
    write_staged_handoff(_plan_record(tmp_path), artifacts_dir=str(tmp_path))
    with pytest.raises(PendingHandoffError, match=STAGED_HANDOFF_FILENAME):
        handoff_guard()


def test_discard_clears_staged_record_and_reservation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_env(monkeypatch, tmp_path)
    write_staged_handoff(_plan_record(tmp_path), artifacts_dir=str(tmp_path))
    (tmp_path / STAGING_RESERVATION_FILENAME).write_text(
        json.dumps({"reservation_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"}),
        encoding="utf-8",
    )
    discard_staged_handoff(str(tmp_path))
    assert read_staged_handoff(str(tmp_path)) is None
    assert not (tmp_path / STAGING_RESERVATION_FILENAME).exists()


def test_staged_provider_response_is_bound_to_its_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_env(monkeypatch, tmp_path)
    record = _plan_record(tmp_path)
    write_staged_handoff(record, artifacts_dir=str(tmp_path))

    path = write_staged_handoff_response(
        str(record["staged_id"]),
        "the ordinary provider response",
        artifacts_dir=str(tmp_path),
    )

    assert path.name == STAGED_HANDOFF_RESPONSE_FILENAME
    assert (
        read_staged_handoff_response(
            str(record["staged_id"]), artifacts_dir=str(tmp_path)
        )
        == "the ordinary provider response"
    )
    with pytest.raises(StagedHandoffError, match="identity mismatch"):
        read_staged_handoff_response(
            "bbbbbbbb-bbbb-4ccc-8ddd-eeeeeeeeeeee", artifacts_dir=str(tmp_path)
        )

    discard_staged_handoff(str(tmp_path))
    assert not path.exists()


def test_receipt_identity_rejects_other_staged_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_env(monkeypatch, tmp_path)
    record = _plan_record(tmp_path)
    write_staged_handoff(record, artifacts_dir=str(tmp_path))
    receipt = {
        "staged_id": record["staged_id"],
        "adopted_at": "2026-10-28T12:01:00Z",
        "outcome": "adopted",
        "refs": {"successor": "next"},
    }
    write_adoption_receipt(receipt, artifacts_dir=str(tmp_path))
    stored = read_adoption_receipt(str(tmp_path))
    assert stored is not None
    assert receipt_authorizes(stored, str(record["staged_id"])) is True
    assert receipt_authorizes(stored, "bbbbbbbb-bbbb-4ccc-8ddd-eeeeeeeeeeee") is False
    held = {
        "staged_id": record["staged_id"],
        "adopted_at": "2026-10-28T12:02:00Z",
        "outcome": "handoff_not_adopted",
        "reason": "commit failed",
    }
    (tmp_path / STAGED_HANDOFF_RECEIPT_FILENAME).unlink()
    write_adoption_receipt(held, artifacts_dir=str(tmp_path))
    assert receipt_authorizes(held, str(record["staged_id"])) is False


def test_finalizer_owned_and_helper_refusals(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv(SASE_FINALIZER_OWNED_TURN_ENV, "1")
    with pytest.raises(StagedHandoffError, match="host finalizer turn"):
        write_staged_handoff(_plan_record(tmp_path), artifacts_dir=str(tmp_path))
    monkeypatch.delenv(SASE_FINALIZER_OWNED_TURN_ENV)
    monkeypatch.setenv("SASE_NATIVE_HELPER", "1")
    with pytest.raises(StagedHandoffError, match="native helper"):
        write_staged_handoff(_plan_record(tmp_path), artifacts_dir=str(tmp_path))


def test_clean_turn_without_submission_can_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    persist_default_plan(tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: clean_state(tmp_path),
    )
    publish_final_context()
    assert final_submission_is_current() is True
    assert _has_accepted_current_final_submission(str(tmp_path)) is False
    write_staged_handoff(_plan_record(tmp_path), artifacts_dir=str(tmp_path))
    assert read_staged_handoff(str(tmp_path)) is not None


def test_accepted_current_submission_refuses_staging(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    publication = publish_final_context()
    submit_final_manifest(valid_manifest(publication))
    assert (tmp_path / FINAL_SUBMISSION_FILENAME).is_file()
    assert _has_accepted_current_final_submission(str(tmp_path)) is True
    with pytest.raises(StagedHandoffError, match="/sase_final"):
        write_staged_handoff(_plan_record(tmp_path), artifacts_dir=str(tmp_path))


def test_concurrent_staged_and_legacy_writers_exclude_each_other(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _agent_env(monkeypatch, tmp_path)
    errors: list[BaseException] = []
    staged_ok = threading.Event()
    legacy_ok = threading.Event()

    def stage() -> None:
        try:
            write_staged_handoff(_plan_record(tmp_path), artifacts_dir=str(tmp_path))
            staged_ok.set()
        except BaseException as exc:  # noqa: BLE001 - collected by parent
            errors.append(exc)

    def legacy() -> None:
        try:
            write_pending_handoff_marker(
                PLAN_PENDING_MARKER,
                {"plan_file": "x"},
                artifacts_dir=str(tmp_path),
            )
            legacy_ok.set()
        except BaseException as exc:  # noqa: BLE001 - collected by parent
            errors.append(exc)

    threads = [
        threading.Thread(target=stage),
        threading.Thread(target=legacy),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert staged_ok.is_set() ^ legacy_ok.is_set()
    assert len(errors) == 1
    assert isinstance(errors[0], (PendingHandoffError, StagedHandoffError))


def test_stage_versus_submit_refuses_after_accepted_submission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    publication = publish_final_context()
    submit_final_manifest(valid_manifest(publication))
    with pytest.raises(StagedHandoffError, match="/sase_final"):
        write_staged_handoff(_plan_record(tmp_path), artifacts_dir=str(tmp_path))
    assert read_staged_handoff(str(tmp_path)) is None
