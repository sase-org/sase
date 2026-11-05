"""Refusal cases for exactly-once hijack recovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agent.hijack.recover import recover_hijacked_agent
from sase.agent.hijack.recover_common import RecoveryDeps
from tests._agent_hijack_recover_helpers import (
    Flow,
    record as make_record,
    subject as make_subject,
    write_done,
)


class TestRecoveryRefusals:
    def test_record_not_found(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        deps = RecoveryDeps(load_subject=lambda name: None)
        result = recover_hijacked_agent("ghost", action="continue", deps=deps)
        assert result.kind == "refused"
        assert result.detail["code"] == "record_not_found"

    def test_hijack_id_mismatch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        flow = Flow(monkeypatch, make_record(artifacts), tmp_path / "succ")
        result = flow.recover(expected_hijack_id="other")
        assert result.kind == "refused"
        assert result.detail["code"] == "hijack_mismatch"
        assert flow.ledger.events == []

    def test_not_held_refuses(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        flow = Flow(
            monkeypatch, make_record(artifacts, state="requested"), tmp_path / "succ"
        )
        result = flow.recover()
        assert result.kind == "refused"
        assert result.detail["code"] == "not_held"
        assert flow.ledger.events == []

    def test_resolved_returns_resolution(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        record = make_record(
            artifacts,
            state="resolved",
            reserved_successor_name="acme--4",
            launch_identity="launch-1",
        )
        flow = Flow(monkeypatch, record, tmp_path / "succ")
        result = flow.recover()
        assert result.kind == "already_resolved"
        assert result.successor == "acme--4"
        assert result.launch_identity == "launch-1"
        assert flow.log == []

    def test_resolving_returns_current_resolution(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        record = make_record(
            artifacts,
            state="resolving",
            reserved_successor_name="acme--4",
            launch_identity="launch-1",
        )
        flow = Flow(monkeypatch, record, tmp_path / "succ")
        result = flow.recover(expected_revision=7)
        assert result.kind == "already_resolving"
        assert result.successor == "acme--4"
        assert flow.log == []

    def test_stale_revision_refuses(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        flow = Flow(monkeypatch, make_record(artifacts), tmp_path / "succ")
        result = flow.recover(expected_revision=6)
        assert result.kind == "refused"
        assert result.detail["code"] == "stale_revision"
        assert flow.ledger.events == []

    def test_stale_resolving_revision_refuses(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        record = make_record(artifacts, state="resolving")
        flow = Flow(monkeypatch, record, tmp_path / "succ")
        result = flow.recover(expected_revision=6)
        assert result.kind == "refused"
        assert result.detail["code"] == "stale_revision"

    def test_outcome_changed_refuses_before_cas(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        write_done(artifacts / "done.json", outcome="done")
        record = make_record(artifacts)
        flow = Flow(monkeypatch, record, tmp_path / "succ")
        deps = flow.deps()
        deps.load_subject = lambda name: make_subject(record, done_outcome="done")
        result = recover_hijacked_agent("acme--3", action="continue", deps=deps)
        assert result.kind == "refused"
        assert result.detail["code"] == "outcome_changed"
        assert flow.ledger.events == []
