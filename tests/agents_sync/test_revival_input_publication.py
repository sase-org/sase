from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from sase.agents_sync.inventory_history import HistoricalAssociations
from sase.agents_sync.inventory_models import ProjectHoodInventory
from sase.agents_sync.inventory_sources import run_from_artifact, run_from_dismissed
from sase.agents_sync.publication import publish_agent_hood
from sase.artifacts import create_artifacts_directory
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.revival_inputs import capture_revival_inputs
from tests.agents_sync.inventory_fixtures import make_record, make_target


def _identity() -> AgentIdentitySnapshot:
    return AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena"))


def _history() -> HistoricalAssociations:
    return HistoricalAssociations({}, ())


def _unused_git(
    _cwd: Path,
    args: list[str],
    *,
    network: bool = False,
    op: str = "",
) -> subprocess.CompletedProcess[str]:
    del network, op
    return subprocess.CompletedProcess(args, 1, "", "unused")


def _seed_run(tmp_path: Path, timestamp: str, prompt: str) -> Path:
    artifacts = Path(create_artifacts_directory("ace-run", "proj", timestamp=timestamp))
    (artifacts / "raw_xprompt.md").write_text(prompt, encoding="utf-8")
    (artifacts / "submitted_xprompt.md").write_text("submitted\n", encoding="utf-8")
    (artifacts / "xprompts.json").write_text("[]\n", encoding="utf-8")
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "foo",
                "artifact_agent_id": artifacts.name,
                "model": "gpt",
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "done.json").write_text(
        json.dumps({"name": "foo", "outcome": "completed"}),
        encoding="utf-8",
    )
    return artifacts


def test_publication_prefers_archive_over_later_live_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts = _seed_run(tmp_path, "260903_121000", "archived prompt\n")
    capture_revival_inputs(artifacts)
    (artifacts / "raw_xprompt.md").write_text("later live prompt\n", encoding="utf-8")

    run = run_from_artifact(
        make_target(tmp_path),
        make_record(artifacts, artifacts.name),
        _identity(),
        _history(),
        {},
        _unused_git,
    )

    assert run is not None
    assert run.prompt_bytes == b"archived prompt\n"


def test_legacy_publication_reads_live_prompt_when_archive_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts = _seed_run(tmp_path, "260903_121100", "legacy live prompt\n")

    run = run_from_artifact(
        make_target(tmp_path),
        make_record(artifacts, artifacts.name),
        _identity(),
        _history(),
        {},
        _unused_git,
    )

    assert run is not None
    assert run.prompt_bytes == b"legacy live prompt\n"


def test_dismissed_publication_after_cleanup_uses_launch_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts = _seed_run(tmp_path, "260903_121200", "keep after cleanup\n")
    capture_revival_inputs(artifacts)
    artifacts_dir = str(artifacts)
    shutil.rmtree(artifacts)

    run = run_from_dismissed(
        {
            "agent_name": "foo",
            "raw_suffix": Path(artifacts_dir).name,
            "artifacts_dir": artifacts_dir,
            "status": "DONE",
            "start_time": "2026-09-03T12:12:00+00:00",
            "stop_time": "2026-09-03T12:13:00+00:00",
            "model": "gpt",
        },
        "dismissed.json",
        "proj",
        _identity(),
        _history(),
    )

    assert run is not None
    assert run.prompt_bytes == b"keep after cleanup\n"

    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    publish_agent_hood(
        make_target(tmp_path),
        sidecar,
        "foo",
        identity=_identity(),
        inventory=ProjectHoodInventory(
            AgentOwnerIdentity("alice", "athena"), "proj", (run,)
        ),
    )
    published = sidecar / "agents" / "alice.athena.foo" / "prompt.md"
    assert published.read_text(encoding="utf-8") == "keep after cleanup\n"


def test_legacy_dismissed_publication_keeps_inline_prompt_without_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run = run_from_dismissed(
        {
            "agent_name": "foo",
            "raw_suffix": "20260903121300",
            "raw_xprompt": "inline legacy prompt\n",
            "status": "DONE",
        },
        "dismissed.json",
        "proj",
        _identity(),
        _history(),
    )

    assert run is not None
    assert run.prompt_bytes == b"inline legacy prompt\n"
