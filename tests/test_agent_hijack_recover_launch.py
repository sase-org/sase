"""Successful and repeated hijack recovery launches."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests._agent_hijack_recover_helpers import (
    Flow,
    record as make_record,
    spawned,
    write_done,
)


class TestLaunchedRecovery:
    def _happy_flow(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        **kwargs: Any,
    ) -> tuple[Flow, Any]:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        write_done(artifacts / "done.json")
        successor_dir = tmp_path / "succ"
        successor_dir.mkdir()
        record = make_record(artifacts)
        action = str(kwargs.pop("action", "continue"))
        flow = Flow(monkeypatch, record, successor_dir, **kwargs)
        if flow._spawn is None:
            flow._spawn = spawned(4242, successor_dir)
        result = flow.recover(action=action)
        return flow, result

    def test_continue_launches_and_settles(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import hashlib
        import json

        flow, result = self._happy_flow(monkeypatch, tmp_path)
        assert result.kind == "launched"
        assert result.successor == "acme--4"
        assert result.launch_identity
        assert result.admission_request_id
        assert result.concrete_target == "claude/opus@high"
        assert result.model_changed is False
        # Binding persisted before dispatch: begin, then queued record_launch.
        assert flow.ledger.events[:2] == ["begin_resolution", "record_launch"]
        assert flow.ledger.events[-1] == "complete_resolution"
        assert flow.log == ["spawn"]
        assert flow.prompt_prepared_before_cas is True
        assert flow.preview_states == ["held"]
        from sase.agent.hijack.recovery_successor import (
            RECOVERY_DESCRIPTOR_ENV,
            decode_recovery_descriptor,
        )

        assert flow.spawned_descriptor is not None
        assert flow.spawned_extra_env is not None
        assert flow.spawned_prompt is not None
        bootstrap_descriptor = decode_recovery_descriptor(
            flow.spawned_extra_env[RECOVERY_DESCRIPTOR_ENV]
        )
        assert bootstrap_descriptor == flow.spawned_descriptor
        assert (
            bootstrap_descriptor["admission_request_id"] == result.admission_request_id
        )
        assert (
            bootstrap_descriptor["admission_identity"]
            == (flow.ledger.current["admission_identity"])
        )
        assert bootstrap_descriptor["expected_owner_pid"] == 111
        assert (
            bootstrap_descriptor["prompt_digest"]
            == hashlib.sha256(flow.spawned_prompt.encode("utf-8")).hexdigest()
        )
        # Ack staged in the successor dir; predecessor marker settled.
        from sase.agent.hijack.recovery_successor import read_recovery_ack

        ack = read_recovery_ack(str(flow.successor_dir))
        assert ack is not None and ack["goal"] == "goal-1"
        done = json.loads((tmp_path / "artifacts" / "done.json").read_text())
        assert done["outcome"] == "hijacked"
        assert done["recovery"]["state"] == "resolved"
        assert done["recovery"]["successor"] == "acme--4"
        assert done["recovery"]["model_changed"] is False
        from sase.agent.hijack.core import agent_hijack_status_for_done_marker

        assert (
            agent_hijack_status_for_done_marker("hijacked", done["recovery"])
            == "CONTINUED"
        )

    def test_escalate_settles_model_changed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import json

        flow, result = self._happy_flow(monkeypatch, tmp_path, action="escalate")
        assert result.kind == "launched"
        assert result.concrete_target == "claude/opus@xhigh"
        assert result.model_changed is True
        done = json.loads((tmp_path / "artifacts" / "done.json").read_text())
        assert done["recovery"]["model_changed"] is True
        from sase.agent.hijack.core import agent_hijack_status_for_done_marker

        assert (
            agent_hijack_status_for_done_marker("hijacked", done["recovery"])
            == "ESCALATED"
        )

    def test_repeat_call_returns_resolution_without_relaunch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        flow, first = self._happy_flow(monkeypatch, tmp_path)
        assert first.kind == "launched"
        spawns = list(flow.log)
        # Fresh subject at the resolved revision: no second spawn.
        second = flow.recover()
        assert second.kind == "already_resolved"
        assert second.successor == "acme--4"
        assert flow.log == spawns

    def test_fresh_coordinator_reuses_the_persisted_dispatch_fingerprint(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import json

        from sase.agent.hijack.recovery_admission import (
            RECOVERY_ADMISSION_METADATA_KEY,
        )
        from sase.agent.launch_admission import run_coordinator_in_bundle
        from sase.agent.launch_request_response import read_launch_request

        flow, result = self._happy_flow(monkeypatch, tmp_path)
        assert result.kind == "launched"
        assert result.admission_request_id
        bundle = flow.admission_root / "typed_launches" / result.admission_request_id
        data = read_launch_request(bundle)
        descriptor = data["unit_dispatch_metadata"][RECOVERY_ADMISSION_METADATA_KEY]
        unit = descriptor["typed_plan"]["units"][0]["payload"]
        assert descriptor["admission_request_id"] == result.admission_request_id
        assert (
            descriptor["dispatch_fingerprint"]
            == flow.ledger.current["admission_identity"]
        )
        assert unit["identity"] == "acme--4"
        assert unit["model"] == "claude/opus"
        assert unit["reasoning_effort"] == "high"
        journal = (bundle / "launch_admission" / "journal.jsonl").read_text()
        assert json.loads(journal.splitlines()[-1])["phase"] == "launched"

        # A new coordinator rebuilds the recovery dispatcher from the stored
        # bundle and journal. The launched unit is terminal, so it cannot spawn
        # a second successor.
        progress = run_coordinator_in_bundle(bundle)
        assert progress.complete is True
        assert progress.summary.launched == 1
        assert flow.log == ["spawn"]

    def test_concurrent_resolvers_yield_one_successor(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import threading

        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        write_done(artifacts / "done.json")
        successor_dir = tmp_path / "succ"
        successor_dir.mkdir()
        record = make_record(artifacts)
        flow = Flow(
            monkeypatch,
            record,
            successor_dir,
            spawn=spawned(4242, successor_dir),
        )
        results: list[Any] = []

        def worker() -> None:
            results.append(flow.recover())

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        # Exactly one winner launches; the loser learns the resolution
        # (still resolving or already resolved, depending on interleaving).
        kinds = sorted(result.kind for result in results)
        assert kinds[1] == "launched"
        assert kinds[0] in ("already_resolving", "already_resolved")
        assert results[0].successor == results[1].successor == "acme--4"
        assert flow.log == ["spawn"]
        assert flow.ledger.current["state"] == "resolved"
        assert flow.ledger.current["reserved_successor_name"] == "acme--4"

    def test_stale_snapshot_loses_to_winner(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        write_done(artifacts / "done.json")
        successor_dir = tmp_path / "succ"
        successor_dir.mkdir()
        record = make_record(artifacts)
        flow = Flow(
            monkeypatch,
            record,
            successor_dir,
            spawn=spawned(4242, successor_dir),
        )
        first = flow.recover()
        assert first.kind == "launched"
        # A second resolver holding the pre-win snapshot retries the CAS,
        # loses, and learns the winner's resolution instead of launching.
        second = flow.recover()
        assert second.kind == "already_resolved"
        assert second.successor == "acme--4"
        assert flow.log == ["spawn"]
