"""Synthetic Rust-backed fixture measurements for the artifact graph benchmark."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.core import artifact_facade
from sase.core.artifact_wire import (
    ARTIFACT_FILE_TYPE_CHAT,
    ARTIFACT_FILE_TYPE_METADATA_KEY,
    ARTIFACT_FILE_TYPE_PLAN,
    ARTIFACT_KIND_AGENT,
    ARTIFACT_KIND_CHANGESPEC,
    ARTIFACT_KIND_DIRECTORY,
    ARTIFACT_KIND_FILE,
    ARTIFACT_LINK_CREATED,
    ARTIFACT_LINK_PARENT,
    ARTIFACT_LINK_RELATED,
    ARTIFACT_PROVENANCE_MANUAL,
    ARTIFACT_ROOT_ID,
    ARTIFACT_SOURCE_AGENT_ARTIFACT,
    ARTIFACT_SOURCE_AGENT_CREATED_FILE,
    ARTIFACT_SOURCE_AGENT_THOUGHT,
    ARTIFACT_SOURCE_BEAD_STORE,
    ARTIFACT_SOURCE_CHANGESPEC,
    ARTIFACT_SOURCE_COMMIT,
    ARTIFACT_SOURCE_PROJECT_FILE,
    ArtifactLinkUpsertWire,
    ArtifactLinkWire,
    ArtifactMutationResultWire,
    ArtifactNodeUpsertWire,
    ArtifactNodeWire,
    ArtifactQueryWire,
    ArtifactSummaryRequestWire,
)
from sase.ace.tui.artifact_graph_refresh import refresh_artifact_graph_for_paths

from .common import COMMON_SHOW_KINDS
from .records import query_record, time_mutation

HIGH_DEGREE_LINKED_COUNT = 240
PAGE_LIMIT = 10
SEARCH_LIMIT = 12
SUMMARY_VISIBLE_LIMIT = 8


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
    projects_root = root / ".sase" / "projects"
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


def _mutation_batch_record(
    operation: str,
    elapsed_ms: float,
    results: list[ArtifactMutationResultWire],
    *,
    fixture: dict[str, int],
    bounded: bool,
) -> dict[str, Any]:
    errors = [error for result in results for error in result.errors]
    return {
        "operation": operation,
        "latency_ms": elapsed_ms,
        "fixture": fixture,
        "bounded": bounded,
        "mutation_counts": {
            "calls": len(results),
            "nodes_added": sum(result.nodes_added for result in results),
            "nodes_updated": sum(result.nodes_updated for result in results),
            "nodes_removed": sum(result.nodes_removed for result in results),
            "links_added": sum(result.links_added for result in results),
            "links_updated": sum(result.links_updated for result in results),
            "links_removed": sum(result.links_removed for result in results),
            "tombstones_added": sum(result.tombstones_added for result in results),
        },
        "affected_nodes": sum(len(result.affected_node_ids) for result in results),
        "affected_links": sum(len(result.affected_link_ids) for result in results),
        "errors": errors,
    }


def _time_mutation_batch(
    operation: str,
    fn: Any,
    *,
    fixture: dict[str, int],
    bounded: bool,
) -> dict[str, Any]:
    start = time.perf_counter()
    results = fn()
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return _mutation_batch_record(
        operation,
        elapsed_ms,
        results,
        fixture=fixture,
        bounded=bounded,
    )


def _add_node(index_path: Path, node: ArtifactNodeWire) -> None:
    artifact_facade.artifact_add(
        index_path,
        ArtifactNodeUpsertWire(
            schema_version=1,
            node=node,
        ),
    )


def _add_link(
    index_path: Path,
    *,
    link_type: str,
    source_id: str,
    target_id: str,
) -> None:
    artifact_facade.artifact_add(
        index_path,
        ArtifactLinkUpsertWire(
            schema_version=1,
            link=ArtifactLinkWire(
                id=f"{link_type}:{source_id}->{target_id}",
                link_type=link_type,
                source_id=source_id,
                target_id=target_id,
                provenance=ARTIFACT_PROVENANCE_MANUAL,
            ),
        ),
    )


def _write_high_degree_fixture(index_path: Path, *, linked_count: int) -> str:
    parent_id = "bench-high-degree-parent"
    _add_node(
        index_path,
        ArtifactNodeWire(
            id=parent_id,
            kind=ARTIFACT_KIND_DIRECTORY,
            display_title="High degree parent",
            provenance=ARTIFACT_PROVENANCE_MANUAL,
            search_text="high degree parent artifact panel benchmark",
        ),
    )
    _add_link(
        index_path,
        link_type=ARTIFACT_LINK_PARENT,
        source_id=parent_id,
        target_id=ARTIFACT_ROOT_ID,
    )

    for idx in range(linked_count):
        child_id = f"bench-linked-file-{idx:03d}"
        file_type = ARTIFACT_FILE_TYPE_PLAN if idx % 2 == 0 else ARTIFACT_FILE_TYPE_CHAT
        _add_node(
            index_path,
            ArtifactNodeWire(
                id=child_id,
                kind=ARTIFACT_KIND_FILE,
                display_title=f"bench-linked-file-{idx:03d}.md",
                provenance=ARTIFACT_PROVENANCE_MANUAL,
                search_text=f"artifact panel benchmark linked row {idx}",
                metadata={ARTIFACT_FILE_TYPE_METADATA_KEY: file_type},
            ),
        )
        _add_link(
            index_path,
            link_type=ARTIFACT_LINK_PARENT,
            source_id=child_id,
            target_id=parent_id,
        )

    agent_id = "bench-visible-agent"
    changespec_id = "bench-visible-cl"
    _add_node(
        index_path,
        ArtifactNodeWire(
            id=agent_id,
            kind=ARTIFACT_KIND_AGENT,
            display_title="bench visible agent",
            provenance=ARTIFACT_PROVENANCE_MANUAL,
            search_text="artifact summary visible agent benchmark",
        ),
    )
    _add_node(
        index_path,
        ArtifactNodeWire(
            id=changespec_id,
            kind=ARTIFACT_KIND_CHANGESPEC,
            display_title="bench visible cl",
            provenance=ARTIFACT_PROVENANCE_MANUAL,
            search_text="artifact summary visible changespec benchmark",
        ),
    )
    _add_link(
        index_path,
        link_type=ARTIFACT_LINK_CREATED,
        source_id=agent_id,
        target_id="bench-linked-file-000",
    )
    _add_link(
        index_path,
        link_type=ARTIFACT_LINK_RELATED,
        source_id=agent_id,
        target_id=changespec_id,
    )
    _add_link(
        index_path,
        link_type=ARTIFACT_LINK_PARENT,
        source_id=agent_id,
        target_id=ARTIFACT_ROOT_ID,
    )
    _add_link(
        index_path,
        link_type=ARTIFACT_LINK_PARENT,
        source_id=changespec_id,
        target_id=ARTIFACT_ROOT_ID,
    )
    return parent_id


def _refresh_burst_with_fixture_home(
    index_path: Path,
    *,
    root: Path,
    changed_paths: list[Path],
) -> list[ArtifactMutationResultWire]:
    with patch.dict(os.environ, {"HOME": str(root)}):
        return refresh_artifact_graph_for_paths(index_path, changed_paths)


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
        done_path = paths["artifact_dir"] / "done.json"
        done_path.write_text(
            done_path.read_text(encoding="utf-8").replace(
                '"name":',
                '"benchmark_burst": true, "name":',
                1,
            ),
            encoding="utf-8",
        )
        records.append(
            _time_mutation_batch(
                "targeted_agent_artifact_burst",
                lambda: _refresh_burst_with_fixture_home(
                    index_path,
                    root=root,
                    changed_paths=[
                        response_path,
                        done_path,
                        paths["artifact_dir"] / "agent_meta.json",
                    ],
                ),
                fixture=fixture,
                bounded=True,
            )
        )

        parent_id = _write_high_degree_fixture(
            index_path,
            linked_count=HIGH_DEGREE_LINKED_COUNT,
        )
        start = time.perf_counter()
        paged = artifact_facade.artifact_show_paged(
            index_path,
            parent_id,
            artifact_facade.artifact_page_request(
                relation="children",
                offset=0,
                limit=PAGE_LIMIT,
            ),
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        children_loaded = (
            0
            if paged.children_page is None
            else paged.children_page.summary.loaded_count
        )
        children_total = (
            0
            if paged.children_page is None
            else paged.children_page.summary.total_count
        )
        records.append(
            query_record(
                "artifact_show_paged:high_degree_children",
                elapsed_ms,
                fixture={"linked_rows": HIGH_DEGREE_LINKED_COUNT, "limit": PAGE_LIMIT},
                bounded=True,
                query_count=1,
                result_count=children_loaded,
                errors=[]
                if children_loaded <= PAGE_LIMIT
                and children_total == HIGH_DEGREE_LINKED_COUNT
                else [
                    "paged detail did not honor limit or total count",
                ],
            )
        )

        start = time.perf_counter()
        searched = artifact_facade.artifact_search(
            index_path,
            ArtifactQueryWire(text="artifact panel benchmark", limit=SEARCH_LIMIT),
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        records.append(
            query_record(
                "artifact_search:global_limited",
                elapsed_ms,
                fixture={
                    "linked_rows": HIGH_DEGREE_LINKED_COUNT,
                    "limit": SEARCH_LIMIT,
                },
                bounded=True,
                query_count=1,
                result_count=len(searched),
                errors=[]
                if len(searched) <= SEARCH_LIMIT
                else ["global search exceeded explicit limit"],
            )
        )

        visible_ids = [parent_id, "bench-visible-agent", "bench-visible-cl"]
        visible_ids.extend(node.id for node in searched[:SUMMARY_VISIBLE_LIMIT])
        start = time.perf_counter()
        summaries = artifact_facade.artifact_summary(
            index_path,
            ArtifactSummaryRequestWire(artifact_ids=tuple(visible_ids)),
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        records.append(
            query_record(
                "artifact_summary:visible_rows_batch",
                elapsed_ms,
                fixture={"visible_rows": len(visible_ids)},
                bounded=True,
                query_count=1,
                result_count=len(summaries),
                errors=[]
                if len(summaries) == len(visible_ids)
                else ["batched summary returned an unexpected row count"],
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
