"""Tests for the agent-hold wire helpers in agent_hold_facade."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.core.agent_hold_facade import (
    _AgentHoldServiceError,
    agent_armer_wire_for_artifacts,
    current_armer_wire,
    _hold_scope_wire,
    _hold_selectors_wire,
)

from tests._runner_slot_fixtures import artifact as make_artifact


def test_hold_scope_wire_project_and_host() -> None:
    assert _hold_scope_wire("project", project="proj") == {
        "kind": "project",
        "project": "proj",
    }
    assert _hold_scope_wire("host", project="proj") == {"kind": "host"}


def test_hold_selectors_wire_normalizes_tribes_and_defaults() -> None:
    selectors = _hold_selectors_wire(
        names=["a.b--code"],
        tribes=["@ops", "infra"],
        hoods=["fi"],
        future=True,
        artifact_dirs=["/a/w1"],
    )
    assert selectors["artifact_dirs"] == ["/a/w1"]
    assert selectors["names"] == ["a.b--code"]
    assert selectors["families"] == []
    assert selectors["clans"] == ["a.b--code"]
    assert selectors["workflows"] == ["a.b--code"]
    assert selectors["hoods"] == ["fi"]
    assert selectors["tribes"] == ["infra", "ops"]
    assert selectors["future"] is True


def test_hold_selectors_wire_expands_family_names() -> None:
    selectors = _hold_selectors_wire(names=["team"])
    assert selectors["names"] == ["team"]
    assert selectors["families"] == ["team"]
    assert selectors["clans"] == ["team"]
    assert selectors["workflows"] == ["team"]


def test_hold_selectors_wire_defaults_are_empty() -> None:
    selectors = _hold_selectors_wire()
    assert selectors["artifact_dirs"] == []
    assert selectors["names"] == []
    assert selectors["families"] == []
    assert selectors["clans"] == []
    assert selectors["workflows"] == []
    assert selectors["hoods"] == []
    assert selectors["tribes"] == []
    assert selectors["future"] is False


def test_current_armer_wire_uses_agent_metadata_when_artifacts_dir_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts_dir = make_artifact(tmp_path, "20260910120000", 4242)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": 4242,
                "name": "worker.a--code",
                "agent_family": "worker.a",
                "agent_clan": "builders",
            }
        )
    )

    armer = current_armer_wire(env={"SASE_ARTIFACTS_DIR": str(artifacts_dir)})

    assert armer["kind"] == "agent"
    assert armer["key"] == "agent:worker.a--code"
    assert armer["display"] == "worker.a--code"
    assert armer["project"] == "proj"
    assert armer["agent_name"] == "worker.a--code"
    assert armer["family"] == "worker.a"
    assert armer["clan"] == "builders"
    assert armer["pid"] == 4242
    assert armer["done_marker_path"] == str(artifacts_dir / "done.json")


def test_current_armer_wire_raises_when_agent_meta_has_no_name(
    tmp_path: Path,
) -> None:
    artifacts_dir = make_artifact(tmp_path, "20260910120001", 4242)
    (artifacts_dir / "agent_meta.json").write_text(json.dumps({"pid": 4242}))

    with pytest.raises(_AgentHoldServiceError):
        current_armer_wire(env={"SASE_ARTIFACTS_DIR": str(artifacts_dir)})


def test_agent_armer_wire_for_artifacts_uses_pid_fallback_when_meta_has_no_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts_dir = make_artifact(tmp_path, "20260910120002", 4242)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": "worker.a--code"})
    )

    armer = agent_armer_wire_for_artifacts(str(artifacts_dir), pid_fallback=9999)

    assert armer["pid"] == 9999


def test_agent_armer_wire_for_artifacts_prefers_meta_pid_over_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts_dir = make_artifact(tmp_path, "20260910120003", 4242)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"pid": 4242, "name": "worker.a--code"})
    )

    armer = agent_armer_wire_for_artifacts(str(artifacts_dir), pid_fallback=9999)

    assert armer["pid"] == 4242


def test_current_armer_wire_falls_back_to_cli_kind_without_artifacts_dir() -> None:
    with patch("sase.core.agent_hold_facade._project_for_cwd", return_value="scratch"):
        armer = current_armer_wire(env={}, pid_override=4321)

    assert armer["kind"] == "cli"
    assert armer["pid"] == 4321
    assert armer["key"].endswith(":4321")
    assert armer["project"] == "scratch"


def test_current_armer_wire_cli_kind_defaults_pid_to_parent_process() -> None:
    with patch("sase.core.agent_hold_facade._project_for_cwd", return_value="scratch"):
        armer = current_armer_wire(env={})

    assert armer["pid"] == os.getppid()


def test_project_for_cwd_raises_when_unresolvable() -> None:
    with patch("sase.bead.project_name.infer_project_name_from_cwd", return_value=None):
        with pytest.raises(_AgentHoldServiceError):
            current_armer_wire(env={})
