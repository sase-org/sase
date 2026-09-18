"""Build and cache synthetic agent archives for load-tier benchmarks."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import shutil

from sase.core.agent_scan_facade import rebuild_agent_artifact_index

from tests.perf._agent_load_tiering_fixture_core import (
    DEFAULT_ARCHIVE_ARTIFACT_COUNT,
    FIXTURE_SCHEMA_VERSION,
    SyntheticArchiveFixture,
    _MODELS,
    _PROJECTS,
    _PROVIDERS,
    _TUI_SCAN_OPTIONS,
    _artifact_dir,
    _done_payload,
    _meta_payload,
    _write_json,
)
from tests.perf._agent_load_tiering_fixture_special import (
    _write_completed,
    _write_failed,
    _write_hidden_completed,
    _write_monitor_done,
    _write_pending_question,
    _write_provenance_completed,
    _write_running,
    _write_waiting,
    _write_workflow,
)


def build_synthetic_agent_archive(
    cache_root: Path,
    *,
    artifact_count: int = DEFAULT_ARCHIVE_ARTIFACT_COUNT,
) -> SyntheticArchiveFixture:
    """Build or reuse a synthetic ``SASE_HOME`` with a large projects tree."""

    if artifact_count < 24:
        raise ValueError("artifact_count must be at least 24")

    sase_home = cache_root / "sase-home"
    projects_root = sase_home / "projects"
    index_path = sase_home / "agent_artifact_index.sqlite"
    meta_path = cache_root / "agent-load-tiering-fixture.json"
    active_pid = os.getpid()
    expected_meta = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "artifact_count": artifact_count,
    }

    if _fixture_cache_matches(meta_path, expected_meta) and projects_root.is_dir():
        _refresh_active_pids(projects_root, active_pid)
    else:
        shutil.rmtree(cache_root, ignore_errors=True)
        cache_root.mkdir(parents=True, exist_ok=True)
        projects_root.mkdir(parents=True, exist_ok=True)
        _write_fixture_projects(projects_root, artifact_count, active_pid=active_pid)
        meta_path.write_text(
            json.dumps(expected_meta, sort_keys=True),
            encoding="utf-8",
        )

    index_path.parent.mkdir(parents=True, exist_ok=True)
    rebuild_agent_artifact_index(index_path, projects_root, _TUI_SCAN_OPTIONS)
    summary = _fixture_summary(projects_root, artifact_count)
    return SyntheticArchiveFixture(
        sase_home=sase_home,
        projects_root=projects_root,
        index_path=index_path,
        artifact_count=artifact_count,
        **summary,
    )


def rebuild_index(fixture: SyntheticArchiveFixture) -> None:
    """Rebuild a fixture's persistent index from its current on-disk state.

    Callers use this after mutating markers in place (:func:`write_completed_artifact`,
    :func:`set_artifact_hidden`, :func:`delete_artifact`) when a test needs the
    index to already know about a row, as opposed to leaving it stale to
    exercise revalidate/discovery behavior directly.
    """
    rebuild_agent_artifact_index(
        fixture.index_path, fixture.projects_root, _TUI_SCAN_OPTIONS
    )


def _fixture_cache_matches(meta_path: Path, expected: Mapping[str, object]) -> bool:
    try:
        actual = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return all(actual.get(key) == value for key, value in expected.items())


def _refresh_active_pids(projects_root: Path, active_pid: int) -> None:
    for marker_name in ("running.json", "agent_meta.json"):
        for path in projects_root.glob(f"**/{marker_name}"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("fixture_active_pid") is not True:
                continue
            data["pid"] = active_pid
            path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def _fixture_summary(
    projects_root: Path,
    artifact_count: int,
) -> dict[str, int]:
    active_count = 0
    hidden_count = 0
    workflow_count = 0
    provenance_marker_count = 0
    for artifact_dir in projects_root.glob("*/artifacts/*/*"):
        if not artifact_dir.is_dir():
            continue
        if (artifact_dir / "done.json").is_file():
            try:
                done = json.loads((artifact_dir / "done.json").read_text())
            except (OSError, ValueError):
                done = {}
            hidden_count += int(bool(done.get("hidden")))
            provenance_marker_count += int("source_machine" in done)
        else:
            active_count += 1
        if (artifact_dir / "workflow_state.json").is_file():
            workflow_count += 1
        if (artifact_dir / "agent_meta.json").is_file():
            try:
                meta = json.loads((artifact_dir / "agent_meta.json").read_text())
            except (OSError, ValueError):
                meta = {}
            hidden_count += int(bool(meta.get("hidden")))
            provenance_marker_count += int("source_machine" in meta)

    return {
        "active_count": active_count,
        "completed_count": artifact_count - active_count,
        "hidden_count": hidden_count,
        "workflow_count": workflow_count,
        "provenance_marker_count": provenance_marker_count,
    }


def _write_fixture_projects(
    projects_root: Path,
    artifact_count: int,
    *,
    active_pid: int,
) -> None:
    for project in _PROJECTS:
        project_dir = projects_root / project
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / f"{project}.sase").write_text(
            f"PROJECT: {project}\n",
            encoding="utf-8",
        )

    writers = (
        lambda: _write_running(projects_root, 0, active_pid=active_pid),
        lambda: _write_waiting(projects_root, 1, active_pid=active_pid),
        lambda: _write_pending_question(projects_root, 2, active_pid=active_pid),
        lambda: _write_completed(
            projects_root, 3, provider="codex", model="gpt-5.6-sol"
        ),
        lambda: _write_failed(projects_root, 4),
        lambda: _write_hidden_completed(projects_root, 5),
        lambda: _write_workflow(projects_root, 6),
        lambda: _write_monitor_done(projects_root, 7),
        lambda: _write_provenance_completed(projects_root, 8),
    )
    for writer in writers:
        writer()

    for index in range(len(writers), artifact_count):
        _write_generic_completed(projects_root, index)


def _write_generic_completed(projects_root: Path, index: int) -> None:
    project = _PROJECTS[index % len(_PROJECTS)]
    workflow = "mentor-bench" if index % 29 == 0 else "ace-run"
    provider = _PROVIDERS[index % len(_PROVIDERS)]
    model = _MODELS[index % len(_MODELS)]
    hidden = index % 97 == 0
    provenance = index % 211 == 0
    if index % 3 == 0:
        _write_marker_only_active(
            projects_root,
            index,
            project=project,
            workflow=workflow,
            provider=provider,
            model=model,
        )
        return
    artifact_dir = _artifact_dir(projects_root, project, workflow, index)
    project_file = projects_root / project / f"{project}.sase"
    name = f"feature-agent-{index:05d}"
    cl_name = f"feature-{index % 37:02d}"
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name=name,
            cl_name=cl_name,
            provider=provider,
            model=model,
            hidden=hidden,
            provenance=provenance,
        ),
    )
    _write_json(
        artifact_dir / "done.json",
        _done_payload(
            name=name,
            cl_name=cl_name,
            provider=provider,
            model=model,
            project_file=project_file,
            hidden=hidden,
            provenance=provenance,
        ),
    )


def _write_marker_only_active(
    projects_root: Path,
    index: int,
    *,
    project: str,
    workflow: str,
    provider: str,
    model: str,
) -> None:
    """Write a production-shaped waiting/question record that is not a base row.

    These look SQL-active (no done marker) but the Agents-list loaders cannot
    materialize them. They exist to prove the projection mode does not decode
    them. Prefer a non-home project so they cannot be mistaken for home-running
    rows.
    """
    if project == "home":
        project = "gh_sase-org__sase"
    artifact_dir = _artifact_dir(projects_root, project, workflow, index)
    name = f"marker-only-{index:05d}"
    cl_name = f"marker-{index % 37:02d}"
    meta = _meta_payload(
        index=index,
        name=name,
        cl_name=cl_name,
        provider=provider,
        model=model,
        active=True,
    )
    if index % 13 == 0:
        meta["agent_clan"] = f"marker-clan-{index % 5}"
        meta["agent_clan_generation"] = "g1"
        meta["clan_tribe"] = "bench"
        meta["clan_summary"] = "Marker-only clan context"
    _write_json(artifact_dir / "agent_meta.json", meta)
    if index % 6 == 0:
        _write_json(
            artifact_dir / "pending_question.json",
            {
                "session_id": f"question-{index:05d}",
                "request_path": "/tmp/question.md",
                "submitted_at": "2026-09-12T13:01:00Z",
            },
        )
        return
    _write_json(
        artifact_dir / "waiting.json",
        {
            "cl_name": cl_name,
            "waiting_for": ["upstream"],
            "wait_duration": 300.0,
        },
    )
