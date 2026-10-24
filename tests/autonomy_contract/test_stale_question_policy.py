"""Pre-upgrade built-in snapshots cannot silently answer human questions."""

from pathlib import Path

import pytest

from sase.autonomy.record import read_record
from sase.notification_gates.service import create_gate
from sase.user_question_actions import user_question_gate_spec

from . import harness


def test_stale_live_record_parks_question_and_refreshes_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    stale = harness.stale_standard_record()
    meta = {"autonomy": stale}
    harness.write_meta(tmp_path, meta)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    effective = read_record(meta)
    assert effective is not None
    assert effective["policy"]["gates"]["question"] == "ask"
    assert effective["revision"] == stale["revision"]
    assert effective["digest"] != stale["digest"]
    assert harness.read_meta(tmp_path) == meta

    spec = user_question_gate_spec(
        harness.QUESTIONS, session_id="stale-question", auto=True
    )
    assert spec["auto"]["policy"] == effective
    gate = create_gate(spec)
    assert gate.notification_id is not None
    assert not gate.response_path.exists()
    policy = gate.auto_resolution["policy"]
    assert policy["outcome"] == "ask"
    assert policy["rule"] == "gates.question"
    assert policy["digest"] == effective["digest"]


def test_read_record_keeps_stored_dict_when_refresh_binding_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = harness.stale_standard_record()

    def unavailable(_name: str) -> None:
        raise RuntimeError("unavailable binding")

    monkeypatch.setattr("sase.core.rust.require_rust_binding", unavailable)
    assert read_record({"autonomy": stale}) == stale
