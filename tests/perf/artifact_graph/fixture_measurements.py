"""Synthetic Rust-backed fixture measurements for the artifact graph benchmark."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from sase.core import artifact_facade
from sase.core.artifact_wire import (
    ARTIFACT_SOURCE_AGENT_ARTIFACT,
    ARTIFACT_SOURCE_AGENT_CREATED_FILE,
    ARTIFACT_SOURCE_AGENT_THOUGHT,
    ARTIFACT_SOURCE_BEAD_STORE,
    ARTIFACT_SOURCE_CHANGESPEC,
    ARTIFACT_SOURCE_COMMIT,
    ARTIFACT_SOURCE_PROJECT_FILE,
    ArtifactQueryWire,
)

from .common import COMMON_SHOW_KINDS
from .records import query_record, time_mutation


def fixture_size(
    *, project_count: int, bead_count: int, agent_count: int
) -> dict[str, int]:
    return {
        "project_files": project_count,
        "changespecs": project_count,
        "commits": project_count,
        "beads": bead_count + 1,
        "agents": agent_count,
        "created_files": agent_count,
        "thoughts": agent_count,
    }


def write_fixture(
    root: Path,
    *,
    project_count: int,
    bead_count: int,
    agent_count: int,
) -> dict[str, Path]:
    projects_root = root / "projects"
    workspace_root = root / "workspace"
    beads_dir = workspace_root / "sdd" / "beads"
    project_dir = projects_root / "bench"
    artifact_root = project_dir / "artifacts" / "ace-run"
    project_dir.mkdir(parents=True)
    beads_dir.mkdir(parents=True)
    artifact_root.mkdir(parents=True)

    first_project_file: Path | None = None
    for idx in range(project_count):
        project_file = project_dir / f"bench-{idx}.gp"
        if first_project_file is None:
            first_project_file = project_file
        project_file.write_text(
            f"NAME: cl-{idx}\n"
            "DESCRIPTION: Build the artifact graph quality gate.\n"
            "STATUS: WIP\n"
            "COMMITS:\n"
            f"  (1) Commit note {idx}\n",
            encoding="utf-8",
        )

    issues = [
        {
            "id": "sase-10",
            "title": "Artifact graph benchmark epic",
            "status": "open",
            "issue_type": "plan",
            "tier": "epic",
            "owner": "owner@example.com",
            "assignee": "",
            "created_at": "2026-05-05T00:00:00Z",
            "created_by": "owner@example.com",
            "updated_at": "2026-05-05T00:00:00Z",
            "description": "",
            "notes": "",
            "design": "",
            "is_ready_to_work": True,
            "changespec_name": "cl-0",
            "dependencies": [],
        }
    ]
    for idx in range(bead_count):
        issues.append(
            {
                "id": f"sase-10.{idx + 1}",
                "title": f"Phase {idx + 1}",
                "status": "in_progress" if idx == 0 else "open",
                "issue_type": "phase",
                "parent_id": "sase-10",
                "owner": "owner@example.com",
                "assignee": f"agent-alpha-{idx % max(1, agent_count):03d}",
                "created_at": "2026-05-05T00:00:00Z",
                "created_by": "owner@example.com",
                "updated_at": "2026-05-05T00:00:00Z",
                "description": "",
                "notes": "",
                "design": "",
                "is_ready_to_work": False,
                "dependencies": [],
            }
        )
    (beads_dir / "issues.jsonl").write_text(
        "\n".join(json.dumps(issue) for issue in issues) + "\n",
        encoding="utf-8",
    )

    first_artifact_dir: Path | None = None
    for idx in range(agent_count):
        artifact_dir = artifact_root / f"2026050512{idx:04d}"
        if first_artifact_dir is None:
            first_artifact_dir = artifact_dir
        artifact_dir.mkdir(parents=True)
        response_path = artifact_dir / "response.md"
        response_path.write_text(
            f"artifact graph benchmark response {idx}\n",
            encoding="utf-8",
        )
        agent_name = f"agent-alpha-{idx:03d}"
        phase_id = f"sase-10.{(idx % max(1, bead_count)) + 1}"
        (artifact_dir / "agent_meta.json").write_text(
            json.dumps(
                {
                    "name": agent_name,
                    "artifact_agent_id": agent_name,
                    "changespec_name": f"cl-{idx % max(1, project_count)}",
                    "llm_provider": "codex",
                    "phase_bead_id": phase_id,
                }
            ),
            encoding="utf-8",
        )
        (artifact_dir / "done.json").write_text(
            json.dumps(
                {
                    "name": agent_name,
                    "cl_name": f"cl-{idx % max(1, project_count)}",
                    "response_path": str(response_path),
                }
            ),
            encoding="utf-8",
        )
        (artifact_dir / "codex_thinking.jsonl").write_text(
            json.dumps(
                {
                    "text": f"verify integrated graph relationships {idx}",
                    "timestamp": "2026-05-05T12:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )

    assert first_project_file is not None
    assert first_artifact_dir is not None
    return {
        "projects_root": projects_root,
        "workspace_root": workspace_root,
        "beads_dir": beads_dir,
        "project_file": first_project_file,
        "artifact_dir": first_artifact_dir,
    }


def run_fixture_measurements(
    *,
    project_count: int,
    bead_count: int,
    agent_count: int,
) -> list[dict[str, Any]]:
    fixture = fixture_size(
        project_count=project_count,
        bead_count=bead_count,
        agent_count=agent_count,
    )
    records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="sase-artifact-perf-") as tmp:
        root = Path(tmp)
        paths = write_fixture(
            root,
            project_count=project_count,
            bead_count=bead_count,
            agent_count=agent_count,
        )
        index_path = root / "artifacts.sqlite"
        records.append(
            time_mutation(
                "full_graph_rebuild",
                lambda: artifact_facade.artifact_rebuild(
                    index_path,
                    artifact_facade.artifact_rebuild_request(
                        projects_root=paths["projects_root"],
                        workspace_root=paths["workspace_root"],
                        beads_dir=paths["beads_dir"],
                    ),
                ),
                fixture=fixture,
                bounded=False,
            )
        )

        paths["project_file"].write_text(
            paths["project_file"].read_text(encoding="utf-8")
            + "DESCRIPTION: Targeted project update.\n",
            encoding="utf-8",
        )
        records.append(
            time_mutation(
                "targeted_project_file_upsert",
                lambda: artifact_facade.artifact_rebuild(
                    index_path,
                    artifact_facade.artifact_rebuild_request(
                        projects_root=paths["projects_root"],
                        include_sources=(
                            ARTIFACT_SOURCE_PROJECT_FILE,
                            ARTIFACT_SOURCE_CHANGESPEC,
                            ARTIFACT_SOURCE_COMMIT,
                        ),
                        target_path=paths["project_file"],
                    ),
                ),
                fixture=fixture,
                bounded=True,
            )
        )

        issues_path = paths["beads_dir"] / "issues.jsonl"
        issues_path.write_text(
            issues_path.read_text(encoding="utf-8").replace(
                '"title": "Phase 1"',
                '"title": "Phase 1 updated by perf harness"',
                1,
            ),
            encoding="utf-8",
        )
        records.append(
            time_mutation(
                "targeted_bead_store_upsert",
                lambda: artifact_facade.artifact_rebuild(
                    index_path,
                    artifact_facade.artifact_rebuild_request(
                        beads_dir=paths["beads_dir"],
                        include_sources=(ARTIFACT_SOURCE_BEAD_STORE,),
                    ),
                ),
                fixture=fixture,
                bounded=True,
            )
        )

        response_path = paths["artifact_dir"] / "response.md"
        response_path.write_text(
            response_path.read_text(encoding="utf-8")
            + "targeted agent artifact update\n",
            encoding="utf-8",
        )
        records.append(
            time_mutation(
                "targeted_agent_artifact_upsert",
                lambda: artifact_facade.artifact_rebuild(
                    index_path,
                    artifact_facade.artifact_rebuild_request(
                        projects_root=paths["projects_root"],
                        artifact_dir=paths["artifact_dir"],
                        include_sources=(
                            ARTIFACT_SOURCE_AGENT_ARTIFACT,
                            ARTIFACT_SOURCE_AGENT_CREATED_FILE,
                            ARTIFACT_SOURCE_AGENT_THOUGHT,
                        ),
                    ),
                ),
                fixture=fixture,
                bounded=True,
            )
        )

        for kind in COMMON_SHOW_KINDS:
            nodes = artifact_facade.artifact_list(
                index_path,
                ArtifactQueryWire(kinds=(kind,), limit=1),
            )
            if not nodes:
                records.append(
                    query_record(
                        f"artifact_show:{kind}",
                        0.0,
                        fixture=fixture,
                        bounded=True,
                        query_count=1,
                        result_count=0,
                        errors=[f"no {kind} node found"],
                    )
                )
                continue
            start = time.perf_counter()
            detail = artifact_facade.artifact_show(index_path, nodes[0].id)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            records.append(
                query_record(
                    f"artifact_show:{kind}",
                    elapsed_ms,
                    fixture=fixture,
                    bounded=True,
                    query_count=1,
                    result_count=1 if detail.node is not None else 0,
                )
            )

        doctor = artifact_facade.artifact_doctor(index_path)
        records.append(
            query_record(
                "artifact_doctor",
                0.0,
                fixture=fixture,
                bounded=True,
                query_count=1,
                result_count=len(doctor.issues),
                errors=[] if doctor.ok else [issue.message for issue in doctor.issues],
            )
        )
    return records
