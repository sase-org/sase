"""Exercise the collector's real native reader across interleaved batches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.bead import _stranded_facts_snapshot as snapshot
from sase.core import agent_scan_index_reader as adapter
from sase.core.agent_scan_facade import rebuild_agent_artifact_index


def test_interleaved_projects_and_chunks_reuse_then_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "projects"
    for project in ("one", "two"):
        for number in range(2):
            artifact = (
                root / project / "artifacts" / "ace-run" / f"2026112300000{number}"
            )
            artifact.mkdir(parents=True)
            (artifact / "agent_meta.json").write_text(
                json.dumps({"name": f"agent-{number}", "model": "original"})
            )
    index = tmp_path / "index.sqlite"
    rebuild_agent_artifact_index(index, root)
    monkeypatch.setattr(snapshot, "default_agent_artifact_index_path", lambda: index)
    monkeypatch.setattr(snapshot, "sase_projects_dir", lambda: root)
    monkeypatch.setattr(snapshot, "_BATCH_CHUNK_SIZE", 1)
    snapshot._session_index_reader.cache_clear()
    original = adapter.agent_scan_wire_from_dict
    hydrated: list[int] = []

    def decode(payload: dict[str, Any]) -> Any:
        hydrated.append(len(payload["records"]))
        return original(payload)

    monkeypatch.setattr(adapter, "agent_scan_wire_from_dict", decode)
    keys = {"agent-0", "agent-1"}
    try:
        cold = [snapshot.session_record_cache(p, keys) for p in ("one", "two")]
        warm = [snapshot.session_record_cache(p, keys) for p in ("one", "two")]
        assert hydrated == [1, 1, 1, 1, 0, 0, 0, 0]
        for before, after in zip(cold, warm, strict=True):
            for key in keys:
                assert before[key][1] and after[key][1]
                assert before[key][0][0] is after[key][0][0]
                assert before[key][0] is not after[key][0]

        marker = root / "one/artifacts/ace-run/20261123000000/agent_meta.json"
        marker.write_text(json.dumps({"name": "agent-0", "model": "repaired"}))
        changed = snapshot.session_record_cache("one", keys)
        meta = changed["agent-0"][0][0].agent_meta
        old_meta = cold[0]["agent-0"][0][0].agent_meta
        assert meta is not None and old_meta is not None
        assert meta.model == "repaired" and old_meta.model == "original"
        # Repair invalidates native generations conservatively, including the
        # other batch. Never assume that an unchanged Python key proves reuse.
        assert changed["agent-1"][0][0] == cold[0]["agent-1"][0][0]
        assert hydrated[-2:] == [1, 1]
        snapshot.session_record_cache("one", keys)
        assert hydrated[-2:] == [1, 0]  # Repaired batch establishes a generation.
        snapshot.session_record_cache("one", keys)
        assert hydrated[-2:] == [0, 0]
    finally:
        snapshot._session_index_reader.cache_clear()
