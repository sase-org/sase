"""Instrumentation for the gate-shell exact-id lookup boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

import sase.gate_shell.store as gate_store
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    FamilyShellGateWire,
    FamilyShellWire,
)
from tests.telemetry.conftest import init_enabled, sample


def _gate_wire(path: str) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir="/tmp/proj",
        project_file="/tmp/proj/proj.sase",
        workflow_dir_name="ace-run",
        artifact_dir=path,
        timestamp="20260812120000",
        agent_meta=AgentMetaWire(
            name=Path(path).name,
            agent_family="lane",
            agent_family_role="gate",
            family_shell=FamilyShellWire(
                kind="gate",
                id="gate-1",
                state="pending",
                gate=FamilyShellGateWire(kind="custom"),
            ),
        ),
    )


def test_indexed_lookup_records_duration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reg = init_enabled()
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.write_bytes(b"")
    monkeypatch.setattr(
        gate_store, "default_agent_artifact_index_path", lambda: index_path
    )
    wire = _gate_wire("/tmp/proj/artifacts/ace-run/20260812120000")
    monkeypatch.setattr(
        gate_store, "_rust_find_gate_shell_by_gate_id", lambda *a, **k: wire
    )

    record = gate_store.find_gate_shell_by_gate_id("proj", "gate-1")

    assert record is not None
    assert (
        sample(
            reg, "sase_gate_shell_lookup_duration_seconds_count", {"path": "indexed"}
        )
        == 1.0
    )
    assert sample(reg, "sase_gate_shell_lookup_fallbacks_total", {}) is None


def test_fallback_scan_records_duration_and_fallback_counter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reg = init_enabled()
    monkeypatch.setattr(
        gate_store,
        "default_agent_artifact_index_path",
        lambda: tmp_path / "agent_artifact_index.sqlite",
    )
    wire = _gate_wire("/tmp/proj/artifacts/ace-run/20260812120000")
    monkeypatch.setattr(gate_store, "_project_records", lambda project_name: [wire])

    record = gate_store.find_gate_shell_by_gate_id("proj", "gate-1")

    assert record is not None
    assert (
        sample(
            reg, "sase_gate_shell_lookup_duration_seconds_count", {"path": "fallback"}
        )
        == 1.0
    )
    assert sample(reg, "sase_gate_shell_lookup_fallbacks_total", {}) == 1.0
