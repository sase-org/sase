from __future__ import annotations

import json
from pathlib import Path

from sase.agents_sync import inventory_models
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.core.agent_scan_wire import AgentArtifactRecordWire


def make_target(tmp_path: Path) -> ProjectTarget:
    primary = tmp_path / "primary"
    primary.mkdir()
    return ProjectTarget(
        "proj",
        "Project",
        primary,
        (primary.resolve(),),
        tmp_path / "sidecar",
        "unused",
        "primary",
    )


def make_record(artifact: Path, timestamp: str) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir=str(artifact.parents[1]),
        project_file=str(artifact.parents[1] / "proj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(artifact),
        timestamp=timestamp,
        has_done_marker=(artifact / "done.json").is_file(),
    )


def write_artifact(artifacts: Path, timestamp: str, name: str) -> Path:
    artifact = artifacts / timestamp
    artifact.mkdir(parents=True)
    (artifact / "raw_xprompt.md").write_text(f"prompt for {name}\n")
    (artifact / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": name,
                "artifact_agent_id": timestamp,
                "model": "gpt",
            }
        )
    )
    (artifact / "done.json").write_text(
        json.dumps(
            {
                "name": name,
                "outcome": "completed",
                "finished_at": "2026-07-23T12:01:00+00:00",
            }
        )
    )
    return artifact


def git_log(names: tuple[str, ...]) -> str:
    chunks: list[str] = []
    for index, name in enumerate(names, start=1):
        sha = f"{index:040x}"
        chunks.append(
            f"{sha}\x00{index}\x00subject {index}\x00"
            f"subject {index}\n\nSASE_AGENT=alice.athena.{name}\x00"
        )
    return "".join(chunks)


def make_inventory_run(
    name: str,
    suffix: str,
    *,
    source_label: str,
) -> inventory_models.InventoryRun:
    return inventory_models.InventoryRun(
        f"run-{suffix}",
        name,
        f"alice.athena.{name}",
        "completed",
        "2026-07-23T12:00:00+00:00",
        "2026-07-23T12:01:00+00:00",
        None,
        (),
        (CommitRecord("c" * 39 + suffix, name, 1),),
        None,
        None,
        None,
        None,
        (),
        f"2026072312000{suffix}",
        source_label=source_label,
    )
