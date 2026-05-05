"""Benchmark the unified artifact graph integration path.

The harness builds a deterministic mixed SASE fixture in a temp directory,
then measures the Rust-backed Python facade operations that Epic 6 treats as
the integrated artifact quality gate:

    python tests/perf/bench_artifact_graph.py --runs 3 --output /tmp/artifacts.json

The timings are intentionally descriptive rather than workstation-gating. The
assertions only cover integration correctness, bounded modal behavior, and
absence of broad scans in the fake TUI graph.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import statistics
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.tui.modals.artifact_panel_modal import ArtifactPanelModal
from sase.core import artifact_facade
from sase.core.artifact_wire import (
    ARTIFACT_KIND_AGENT,
    ARTIFACT_KIND_BEAD,
    ARTIFACT_KIND_CHANGESPEC,
    ARTIFACT_KIND_COMMIT,
    ARTIFACT_KIND_FILE,
    ARTIFACT_KIND_PROJECT,
    ARTIFACT_KIND_THOUGHT,
    ARTIFACT_SOURCE_AGENT_ARTIFACT,
    ARTIFACT_SOURCE_AGENT_CREATED_FILE,
    ARTIFACT_SOURCE_AGENT_THOUGHT,
    ARTIFACT_SOURCE_BEAD_STORE,
    ARTIFACT_SOURCE_CHANGESPEC,
    ARTIFACT_SOURCE_COMMIT,
    ARTIFACT_SOURCE_PROJECT_FILE,
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDetailWire,
    ArtifactGraphOptionsWire,
    ArtifactGraphWire,
    ArtifactLinkWire,
    ArtifactMutationResultWire,
    ArtifactNodeWire,
    ArtifactQueryWire,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME

pytestmark = pytest.mark.slow


COMMON_SHOW_KINDS = (
    ARTIFACT_KIND_PROJECT,
    ARTIFACT_KIND_CHANGESPEC,
    ARTIFACT_KIND_COMMIT,
    ARTIFACT_KIND_BEAD,
    ARTIFACT_KIND_AGENT,
    ARTIFACT_KIND_FILE,
    ARTIFACT_KIND_THOUGHT,
)


class _ModalBenchApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


class _LargeFakeArtifactGraph:
    """Deterministic large graph fixture that avoids Rust and user state."""

    def __init__(self, *, linked_count: int) -> None:
        self.show_calls: list[str] = []
        self.graph_calls: list[ArtifactGraphOptionsWire] = []
        self.export_calls: list[tuple[ArtifactGraphOptionsWire, str]] = []
        self.details = self._build_details(linked_count)

    def show(self, index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path
        self.show_calls.append(artifact_id)
        return self.details[artifact_id]

    def graph(
        self,
        index_path: str | Any,
        options: ArtifactGraphOptionsWire,
    ) -> ArtifactGraphWire:
        del index_path
        self.graph_calls.append(options)
        root_id = options.root_id or "/"
        detail = self.details[root_id]
        nodes = [detail.node, *detail.children]
        limit = options.limit or len(nodes)
        return ArtifactGraphWire(
            schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
            root_id=root_id,
            nodes=[node for node in nodes if node is not None][:limit],
            node_count=len(nodes),
            link_count=len(detail.outbound_links) + len(detail.inbound_links),
            truncated=len(nodes) > limit,
            limit=limit,
        )

    def export(
        self,
        index_path: str | Any,
        options: ArtifactGraphOptionsWire,
        output_format: str,
    ) -> str:
        del index_path
        self.export_calls.append((options, output_format))
        return "flowchart TD\n  root --> child\n"

    def _build_details(self, linked_count: int) -> dict[str, ArtifactDetailWire]:
        root_children = [
            _node(f"changespec:{idx}", "changespec", f"ChangeSpec {idx}")
            for idx in range(linked_count)
        ]
        changespec_children = [
            _node(f"agent:{idx}", "agent", f"Agent {idx}")
            for idx in range(linked_count)
        ]
        agent_children = [
            _node(
                f"file:{idx}",
                "file",
                f"File {idx}",
                {"path": f"/tmp/nonexistent-artifact-{idx}.txt"},
            )
            for idx in range(linked_count)
        ]
        details = {
            "/": _detail("/", kind="root", children=root_children),
            "changespec:current": _detail(
                "changespec:current",
                kind="changespec",
                metadata={"name": "feature/current", "status": "WIP"},
                children=changespec_children,
                outbound_links=[
                    ArtifactLinkWire(
                        id=f"cs-created-{idx}",
                        link_type="created",
                        source_id="changespec:current",
                        target_id=f"agent:{idx}",
                    )
                    for idx in range(linked_count)
                ],
                inbound_links=[
                    ArtifactLinkWire(
                        id=f"cs-related-{idx}",
                        link_type="related",
                        source_id=f"project:{idx}",
                        target_id="changespec:current",
                    )
                    for idx in range(linked_count)
                ],
                path_to_root=[_node("/", "root")],
            ),
            "agent:current": _detail(
                "agent:current",
                kind="agent",
                metadata={"status": "DONE", "provider": "codex"},
                children=agent_children,
                path_to_root=[_node("/", "root"), _node("changespec:current")],
            ),
        }
        for nodes in (root_children, changespec_children, agent_children):
            for node in nodes:
                details[node.id] = _detail(node.id, kind=node.kind)
        return details


def _node(
    artifact_id: str,
    kind: str = "file",
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ArtifactNodeWire:
    return ArtifactNodeWire(
        id=artifact_id,
        kind=kind,
        display_title=title or artifact_id,
        provenance="derived",
        metadata=metadata or {},
    )


def _detail(
    artifact_id: str,
    *,
    kind: str = "file",
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
    children: list[ArtifactNodeWire] | None = None,
    outbound_links: list[ArtifactLinkWire] | None = None,
    inbound_links: list[ArtifactLinkWire] | None = None,
    path_to_root: list[ArtifactNodeWire] | None = None,
) -> ArtifactDetailWire:
    return ArtifactDetailWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        node=_node(artifact_id, kind, title, metadata),
        children=children or [],
        outbound_links=outbound_links or [],
        inbound_links=inbound_links or [],
        path_to_root=path_to_root or [],
    )


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = max(0, min(len(sorted_vals) - 1, int(round(pct * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def _summarize(values: Iterable[float]) -> dict[str, float]:
    vals = sorted(values)
    if not vals:
        return {"count": 0.0}
    return {
        "count": float(len(vals)),
        "min_ms": vals[0],
        "median_ms": statistics.median(vals),
        "p95_ms": _percentile(vals, 0.95),
        "max_ms": vals[-1],
    }


def _ensure_extension() -> None:
    module = importlib.import_module(RUST_EXTENSION_MODULE_NAME)
    required = {
        "artifact_rebuild",
        "artifact_list",
        "artifact_show",
        "artifact_doctor",
    }
    missing = sorted(name for name in required if not hasattr(module, name))
    if missing:
        raise RuntimeError(f"{RUST_EXTENSION_MODULE_NAME} is missing {missing}")


def _fixture_size(
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


def _write_fixture(
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


def _mutation_record(
    operation: str,
    latency_ms: float,
    result: ArtifactMutationResultWire,
    *,
    fixture: dict[str, int],
    bounded: bool,
) -> dict[str, Any]:
    return {
        "operation": operation,
        "latency_ms": latency_ms,
        "fixture": fixture,
        "bounded": bounded,
        "mutation_counts": {
            "nodes_added": result.nodes_added,
            "nodes_updated": result.nodes_updated,
            "nodes_removed": result.nodes_removed,
            "links_added": result.links_added,
            "links_updated": result.links_updated,
            "links_removed": result.links_removed,
            "tombstones_added": result.tombstones_added,
        },
        "affected_nodes": len(result.affected_node_ids),
        "affected_links": len(result.affected_link_ids),
        "errors": result.errors,
    }


def _query_record(
    operation: str,
    latency_ms: float,
    *,
    fixture: dict[str, int],
    bounded: bool,
    query_count: int,
    result_count: int,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "operation": operation,
        "latency_ms": latency_ms,
        "fixture": fixture,
        "bounded": bounded,
        "query_counts": {"calls": query_count},
        "result_count": result_count,
        "errors": errors or [],
    }


def _time_mutation(
    operation: str,
    fn: Callable[[], ArtifactMutationResultWire],
    *,
    fixture: dict[str, int],
    bounded: bool,
) -> dict[str, Any]:
    start = time.perf_counter()
    result = fn()
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return _mutation_record(
        operation, elapsed_ms, result, fixture=fixture, bounded=bounded
    )


def _run_fixture_measurements(
    *,
    project_count: int,
    bead_count: int,
    agent_count: int,
) -> list[dict[str, Any]]:
    fixture = _fixture_size(
        project_count=project_count,
        bead_count=bead_count,
        agent_count=agent_count,
    )
    records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="sase-artifact-perf-") as tmp:
        root = Path(tmp)
        paths = _write_fixture(
            root,
            project_count=project_count,
            bead_count=bead_count,
            agent_count=agent_count,
        )
        index_path = root / "artifacts.sqlite"
        records.append(
            _time_mutation(
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
            _time_mutation(
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
            _time_mutation(
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
            _time_mutation(
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
                    _query_record(
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
                _query_record(
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
            _query_record(
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


async def _measure_modal_open(
    *,
    start_id: str,
    linked_count: int,
) -> dict[str, Any]:
    fixture = {"linked_rows": linked_count}
    graph = _LargeFakeArtifactGraph(linked_count=linked_count)
    modal = ArtifactPanelModal(artifact_id=start_id, show_func=graph.show)
    app = _ModalBenchApp()

    start = time.perf_counter()
    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        option_count = modal.query_one("#artifact-panel-list", OptionList).option_count
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    query_counts = Counter(graph.show_calls)
    errors: list[str] = []
    if query_counts != Counter({start_id: 1}):
        errors.append(f"unexpected show calls: {dict(query_counts)}")
    if graph.graph_calls:
        errors.append(f"unexpected graph calls: {len(graph.graph_calls)}")
    if graph.export_calls:
        errors.append(f"unexpected export calls: {len(graph.export_calls)}")

    return _query_record(
        f"modal_open:{start_id}",
        elapsed_ms,
        fixture=fixture,
        bounded=True,
        query_count=len(graph.show_calls),
        result_count=option_count,
        errors=errors,
    )


async def _run_modal_measurements(*, linked_count: int) -> list[dict[str, Any]]:
    return [
        await _measure_modal_open(start_id=start_id, linked_count=linked_count)
        for start_id in ("/", "changespec:current", "agent:current")
    ]


def _summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["operation"]), []).append(record)
    return {
        operation: {
            "latency": _summarize([float(item["latency_ms"]) for item in items]),
            "bounded": items[0]["bounded"],
            "fixture": items[0]["fixture"],
            "errors": [error for item in items for error in item.get("errors", [])],
        }
        for operation, items in grouped.items()
    }


def run_benchmark(
    *,
    runs: int,
    project_count: int,
    bead_count: int,
    agent_count: int,
    modal_linked_count: int,
) -> dict[str, Any]:
    _ensure_extension()
    records: list[dict[str, Any]] = []
    for _ in range(runs):
        records.extend(
            _run_fixture_measurements(
                project_count=project_count,
                bead_count=bead_count,
                agent_count=agent_count,
            )
        )
        records.extend(
            asyncio.run(_run_modal_measurements(linked_count=modal_linked_count))
        )
    return {
        "schema_version": ARTIFACT_WIRE_SCHEMA_VERSION,
        "runs": runs,
        "operations": _summarize_records(records),
        "measurements": records,
    }


def test_artifact_graph_benchmark_smoke() -> None:
    pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    result = run_benchmark(
        runs=1,
        project_count=2,
        bead_count=4,
        agent_count=4,
        modal_linked_count=12,
    )

    errors = [
        error
        for measurement in result["measurements"]
        for error in measurement.get("errors", [])
    ]
    assert errors == []
    modal_rows = [
        row
        for row in result["measurements"]
        if str(row["operation"]).startswith("modal_open:")
    ]
    assert modal_rows
    assert all(row["query_counts"]["calls"] == 1 for row in modal_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--projects", type=int, default=4)
    parser.add_argument("--beads", type=int, default=30)
    parser.add_argument("--agents", type=int, default=30)
    parser.add_argument("--modal-linked", type=int, default=240)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = run_benchmark(
        runs=args.runs,
        project_count=args.projects,
        bead_count=args.beads,
        agent_count=args.agents,
        modal_linked_count=args.modal_linked,
    )
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
