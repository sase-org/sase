"""Predecessor settlement tests for hijack recovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.agent.hijack.ledger import HijackLedgerConflict
from sase.agent.hijack.recover_common import RecoveryRefusal
from sase.agent.hijack.recover_settle import settle_recovery
from tests._agent_hijack_recover_helpers import (
    FakeLedger,
    record as make_record,
    write_done,
)


class TestSettleRecovery:
    def _resolving(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **overrides: Any
    ) -> tuple[FakeLedger, dict[str, Any]]:
        from sase.agent.hijack import ledger as ledger_module

        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        write_done(artifacts / "done.json")
        record = make_record(
            artifacts,
            state="resolving",
            resolution_action="continue",
            reserved_successor_name="acme--4",
            concrete_target_model="claude/opus@high",
            model_changed=False,
            launch_identity="launch-1",
            admission_request_id="req-1",
            admission_identity="fp-1",
        )
        record.update(overrides)
        ledger = FakeLedger(record)
        monkeypatch.setattr(ledger_module, "cas_advance_record", ledger.cas)
        monkeypatch.setattr(ledger_module, "load_record", ledger.load)
        return ledger, record

    def test_settle_writes_resolved_marker(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import json

        ledger, record = self._resolving(monkeypatch, tmp_path)
        updated = settle_recovery(
            record,
            action="continue",
            successor_name="acme--4",
            successor_pid=4242,
            successor_artifacts_dir=str(tmp_path / "succ"),
        )
        assert updated["state"] == "resolved"
        assert ledger.events == ["complete_resolution"]
        done = json.loads((tmp_path / "artifacts" / "done.json").read_text())
        assert done["outcome"] == "hijacked"
        assert done["recovery"] == {
            "state": "resolved",
            "kind": "hijack",
            "hijack_id": "h-123",
            "action": "continue",
            "successor": "acme--4",
            "model_changed": False,
            "launch_identity": "launch-1",
        }

    def test_settle_refreshes_predecessor_artifact_index(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from sase.core import agent_artifact_index_lifecycle

        ledger, record = self._resolving(monkeypatch, tmp_path)
        refreshed: list[Path | str | None] = []
        monkeypatch.setattr(
            agent_artifact_index_lifecycle,
            "update_agent_artifact_index_for_marker_mutation",
            lambda artifact_dir: refreshed.append(artifact_dir),
        )

        settle_recovery(record, action="continue", successor_name="acme--4")

        assert ledger.events == ["complete_resolution"]
        assert refreshed == [record["artifacts_dir"]]

    def test_settle_preserves_unrelated_done_fields(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import json

        ledger, record = self._resolving(monkeypatch, tmp_path)
        done_path = tmp_path / "artifacts" / "done.json"
        payload = json.loads(done_path.read_text())
        payload["patch_name"] = "keep-me"
        done_path.write_text(json.dumps(payload))
        settle_recovery(record, action="continue", successor_name="acme--4")
        done = json.loads(done_path.read_text())
        assert done["patch_name"] == "keep-me"
        assert done["recovery"]["successor"] == "acme--4"

    def test_settle_missing_done_marker_writes_minimal(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import json

        ledger, record = self._resolving(monkeypatch, tmp_path)
        (tmp_path / "artifacts" / "done.json").unlink()
        settle_recovery(record, action="escalate", successor_name="acme--4")
        done = json.loads((tmp_path / "artifacts" / "done.json").read_text())
        assert done["outcome"] == "hijacked"
        assert done["recovery"]["state"] == "resolved"

    def test_settle_refuses_non_hijack_outcome(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ledger, record = self._resolving(monkeypatch, tmp_path)
        write_done(tmp_path / "artifacts" / "done.json", outcome="done")
        with pytest.raises(RecoveryRefusal, match="not hijacked"):
            settle_recovery(record, action="continue", successor_name="acme--4")
        assert ledger.events == []

    def test_settle_requires_resolving(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ledger, record = self._resolving(monkeypatch, tmp_path)
        record = {**record, "state": "held"}
        with pytest.raises(RecoveryRefusal, match="resolving"):
            settle_recovery(record, action="continue", successor_name="acme--4")
        assert ledger.events == []

    def test_settle_repairs_done_without_recas(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import json

        ledger, record = self._resolving(monkeypatch, tmp_path)
        resolved = dict(record, state="resolved")
        (tmp_path / "artifacts" / "done.json").unlink()
        # The ledger already advanced before the crash; repair only rewrites
        # the predecessor marker.
        ledger.current = dict(resolved)

        def _no_advance(record: Any, event: Any) -> Any:
            raise AssertionError("settlement repair must not CAS again")

        updated = settle_recovery(
            resolved,
            action="continue",
            successor_name="acme--4",
            advance_fn=_no_advance,
        )
        assert ledger.events == []
        done = json.loads((tmp_path / "artifacts" / "done.json").read_text())
        assert done["recovery"]["successor"] == "acme--4"
        assert updated["state"] == "resolved"

    def test_settle_resolved_for_other_successor_conflicts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ledger, record = self._resolving(monkeypatch, tmp_path)
        resolved = dict(record, state="resolved")
        with pytest.raises(HijackLedgerConflict):
            settle_recovery(resolved, action="continue", successor_name="acme--9")
