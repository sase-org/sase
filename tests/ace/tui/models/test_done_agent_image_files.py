from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.models._loaders._done_loaders import (
    _load_done_agent_for_dir,
    load_done_agents_from_snapshot,
)
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    DoneMarkerWire,
)


def test_done_loader_adds_image_paths_to_extra_files(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "20260430120000"
    artifact_dir.mkdir()
    plan = tmp_path / "plan.md"
    pdf = tmp_path / "notes.pdf"
    image = tmp_path / "image.png"
    video = tmp_path / "demo.mp4"
    duplicate = tmp_path / "duplicate.png"
    done = {
        "cl_name": "feature",
        "project_file": "/tmp/project.sase",
        "outcome": "completed",
        "plan_path": str(plan),
        "markdown_pdf_paths": [str(pdf), str(plan)],
        "image_paths": [str(image), str(plan), str(duplicate)],
        "video_paths": [str(video), str(image)],
    }
    (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.extra_files == [
        str(plan),
        str(pdf),
        str(image),
        str(duplicate),
        str(video),
    ]
    assert agent.instruction_bundle_files == []


def test_done_loader_adds_instruction_bundle_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.core.instruction_manifest.normalize_instruction_manifest",
        lambda payload: payload,
    )
    from tests.instructions.fixture_shadow import write_helper_shadow, write_shadow_run

    artifact_dir = tmp_path / "20260430120100"
    artifact_dir.mkdir()
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "cl_name": "feature",
                "project_file": "/tmp/project.sase",
                "outcome": "completed",
            }
        ),
        encoding="utf-8",
    )
    _artifacts, root, _bundle = write_shadow_run(
        tmp_path, provider="claude", artifacts_dir=artifact_dir
    )
    write_helper_shadow(
        artifact_dir,
        provider="claude",
        parent_invocation_id=str(root["delivery"]["invocation_id"]),
    )

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    names = [Path(path).name for path in agent.instruction_bundle_files]
    assert names == ["00-claude.md", "00-claude.helper.md"]


def test_snapshot_done_loader_adds_image_paths_to_extra_files(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    pdf = tmp_path / "notes.pdf"
    image = tmp_path / "image.png"
    video = tmp_path / "demo.mp4"
    duplicate = tmp_path / "duplicate.png"
    record = AgentArtifactRecordWire(
        project_name="myproj",
        project_dir=str(tmp_path / "myproj"),
        project_file=str(tmp_path / "myproj" / "myproj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(tmp_path / "artifacts" / "ace-run" / "20260430120000"),
        timestamp="20260430120000",
        done=DoneMarkerWire(
            outcome="completed",
            cl_name="feature",
            project_file="/tmp/project.sase",
            plan_path=str(plan),
            markdown_pdf_paths=[str(pdf), str(plan)],
            image_paths=[str(image), str(plan), str(duplicate)],
            video_paths=[str(video), str(image)],
        ),
        has_done_marker=True,
    )
    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(tmp_path),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[record],
    )

    agents = load_done_agents_from_snapshot(snapshot, {}, {})

    assert len(agents) == 1
    assert agents[0].extra_files == [
        str(plan),
        str(pdf),
        str(image),
        str(duplicate),
        str(video),
    ]
