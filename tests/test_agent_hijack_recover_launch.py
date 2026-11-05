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
