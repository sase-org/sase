"""Production-shaped synthetic agent archives for load-tier benchmarks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import shutil
from collections.abc import Mapping

from sase.ace.tui.models import _agent_loader_artifacts as loader_artifacts
from sase.core.agent_scan_facade import rebuild_agent_artifact_index

DEFAULT_ARCHIVE_ARTIFACT_COUNT = 13_000
FIXTURE_SCHEMA_VERSION = 2

_TUI_SCAN_OPTIONS = loader_artifacts._TUI_SCAN_OPTIONS
_PROJECTS = ("gh_sase-org__sase", "gh_bobs-org__bob-cli", "home")
_MODELS = ("gpt-5.6-sol", "claude-sonnet-5", "grok-code-fast")
_PROVIDERS = ("codex", "claude", "grok")
_BASE_TIME = datetime(2026, 9, 12, 14, 0, 0, tzinfo=UTC)


@dataclass(frozen=True)
class SyntheticArchiveFixture:
    """Materialized synthetic archive and its rebuilt index."""

    sase_home: Path
    projects_root: Path
    index_path: Path
    artifact_count: int
    active_count: int
    completed_count: int
    hidden_count: int
    workflow_count: int
    provenance_marker_count: int

    def as_dict(self) -> dict[str, int | str]:
        return {
            "sase_home": str(self.sase_home),
            "projects_root": str(self.projects_root),
            "index_path": str(self.index_path),
            "artifact_count": self.artifact_count,
            "active_count": self.active_count,
            "completed_count": self.completed_count,
            "hidden_count": self.hidden_count,
            "workflow_count": self.workflow_count,
            "provenance_marker_count": self.provenance_marker_count,
        }


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


def _artifact_dir(
    projects_root: Path,
    project: str,
    workflow: str,
    offset: int,
) -> Path:
    timestamp = (_BASE_TIME - timedelta(seconds=offset)).strftime("%Y%m%d%H%M%S")
    return projects_root / project / "artifacts" / workflow / timestamp


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _meta_payload(
    *,
    index: int,
    name: str,
    cl_name: str,
    provider: str,
    model: str,
    pid: int | None = None,
    hidden: bool = False,
    active: bool = False,
    provenance: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "cl_name": cl_name,
        "model": model,
        "llm_provider": provider,
        "vcs_provider": "github",
        "workspace_dir": f"/tmp/sase-load-tiering/ws-{index}",
        "run_started_at": "2026-09-12T13:00:00Z",
    }
    if pid is not None:
        payload["pid"] = pid
    if active:
        payload["fixture_active_pid"] = True
    if hidden:
        payload["hidden"] = True
    if provenance:
        payload["imported_source_owner"] = {
            "username": "bryan",
            "machine_name": "apollo",
        }
        payload["source_machine"] = "apollo"
    if not hidden and index % 11 == 0:
        payload["agent_family"] = f"family-{index // 11}"
        payload["agent_family_role"] = "code"
        payload["agent_family_parallel"] = True
    if not hidden and index % 13 == 0:
        payload["tribe"] = "bench"
    return payload


def _done_payload(
    *,
    name: str,
    cl_name: str,
    provider: str,
    model: str,
    project_file: Path,
    outcome: str = "completed",
    hidden: bool = False,
    provenance: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "outcome": outcome,
        "finished_at": 1_789_220_000.0,
        "cl_name": cl_name,
        "project_file": str(project_file),
        "workspace_num": 22,
        "workspace_dir": "/tmp/sase-load-tiering/done",
        "model": model,
        "llm_provider": provider,
        "vcs_provider": "github",
        "name": name,
        "response_path": "/tmp/sase-load-tiering/response.md",
    }
    if outcome == "failed":
        payload["error"] = "RuntimeError: fixture failure"
        payload["traceback"] = "Traceback (most recent call last): ..."
    if hidden:
        payload["hidden"] = True
    if provenance:
        payload["imported_source_owner"] = {
            "username": "bryan",
            "machine_name": "apollo",
        }
        payload["source_machine"] = "apollo"
    return payload


def _write_running(projects_root: Path, index: int, *, active_pid: int) -> None:
    artifact_dir = _artifact_dir(projects_root, "home", "ace-run", index)
    running = {
        "pid": active_pid,
        "fixture_active_pid": True,
        "cl_name": "feature-hot",
        "model": "gpt-5.6-sol",
        "llm_provider": "codex",
        "vcs_provider": "github",
        "workspace_dir": "/tmp/sase-load-tiering/home",
    }
    _write_json(artifact_dir / "running.json", running)
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name="feature-hot-running",
            cl_name="feature-hot",
            provider="codex",
            model="gpt-5.6-sol",
            pid=active_pid,
            active=True,
        ),
    )


def _write_waiting(projects_root: Path, index: int, *, active_pid: int) -> None:
    artifact_dir = _artifact_dir(projects_root, "gh_sase-org__sase", "ace-run", index)
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name="feature-waiting",
            cl_name="feature-wait",
            provider="claude",
            model="claude-sonnet-5",
            pid=active_pid,
            active=True,
        )
        | {"wait_for": ["upstream"], "wait_duration": 300.0},
    )
    _write_json(
        artifact_dir / "waiting.json",
        {
            "cl_name": "feature-wait",
            "waiting_for": ["upstream"],
            "wait_duration": 300.0,
        },
    )


def _write_pending_question(
    projects_root: Path,
    index: int,
    *,
    active_pid: int,
) -> None:
    artifact_dir = _artifact_dir(
        projects_root, "gh_bobs-org__bob-cli", "ace-run", index
    )
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name="feature-question",
            cl_name="feature-question",
            provider="codex",
            model="gpt-5.6-sol",
            pid=active_pid,
            active=True,
        )
        | {"question_request_path": "/tmp/question.md"},
    )
    _write_json(
        artifact_dir / "pending_question.json",
        {
            "session_id": "question-session",
            "request_path": "/tmp/question.md",
            "submitted_at": "2026-09-12T13:01:00Z",
        },
    )


def _write_completed(
    projects_root: Path,
    index: int,
    *,
    provider: str,
    model: str,
) -> None:
    project = "gh_sase-org__sase"
    artifact_dir = _artifact_dir(projects_root, project, "ace-run", index)
    project_file = projects_root / project / f"{project}.sase"
    name = "feature-done-codex"
    cl_name = "feature-done"
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name=name,
            cl_name=cl_name,
            provider=provider,
            model=model,
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
        ),
    )
    (artifact_dir / "raw_xprompt.md").write_text(
        "feature-free-text-needle in prompt\n",
        encoding="utf-8",
    )


def _write_failed(projects_root: Path, index: int) -> None:
    project = "gh_bobs-org__bob-cli"
    artifact_dir = _artifact_dir(projects_root, project, "ace-run", index)
    project_file = projects_root / project / f"{project}.sase"
    name = "feature-failed-claude"
    cl_name = "feature-failed"
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name=name,
            cl_name=cl_name,
            provider="claude",
            model="claude-sonnet-5",
        ),
    )
    _write_json(
        artifact_dir / "done.json",
        _done_payload(
            name=name,
            cl_name=cl_name,
            provider="claude",
            model="claude-sonnet-5",
            project_file=project_file,
            outcome="failed",
        ),
    )


def _write_hidden_completed(projects_root: Path, index: int) -> None:
    project = "gh_sase-org__sase"
    artifact_dir = _artifact_dir(projects_root, project, "ace-run", index)
    project_file = projects_root / project / f"{project}.sase"
    name = "hidden-feature-agent"
    cl_name = "hidden-feature"
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name=name,
            cl_name=cl_name,
            provider="codex",
            model="gpt-5.6-sol",
            hidden=True,
        ),
    )
    _write_json(
        artifact_dir / "done.json",
        _done_payload(
            name=name,
            cl_name=cl_name,
            provider="codex",
            model="gpt-5.6-sol",
            project_file=project_file,
            hidden=True,
        ),
    )


def _write_workflow(projects_root: Path, index: int) -> None:
    project = "gh_sase-org__sase"
    artifact_dir = _artifact_dir(projects_root, project, "workflow-feature", index)
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name="workflow-feature-root",
            cl_name="feature-workflow",
            provider="claude",
            model="claude-sonnet-5",
        )
        | {
            "plan_approved": True,
            "plan_action": "epic",
            "role_suffix": "--plan",
        },
    )
    _write_json(
        artifact_dir / "workflow_state.json",
        {
            "workflow_name": "feature_workflow",
            "context": {"cl_name": "feature-workflow"},
            "status": "completed",
            "pid": os.getpid(),
            "appears_as_agent": True,
            "is_anonymous": False,
            "current_step_index": 2,
            "start_time": "2026-09-12T13:15:00",
            "steps": [
                {
                    "name": "plan",
                    "status": "completed",
                    "output": {"plan_path": "/tmp/feature-plan.md"},
                    "output_types": {"plan_path": "path"},
                },
                {
                    "name": "code",
                    "status": "completed",
                    "output": {"diff_path": "/tmp/feature.diff"},
                    "output_types": {"diff_path": "path"},
                },
            ],
        },
    )
    _write_json(
        artifact_dir / "plan_path.json",
        {"plan_path": "/tmp/feature-plan.md"},
    )
    _write_json(
        artifact_dir / "prompt_step_001_plan.json",
        {
            "workflow_name": "feature_workflow",
            "step_name": "plan",
            "step_type": "agent",
            "step_index": 0,
            "total_steps": 2,
            "status": "completed",
            "model": "claude-sonnet-5",
            "llm_provider": "claude",
            "output": {"meta_workspace": "10", "plan_path": "/tmp/feature-plan.md"},
            "output_types": {"plan_path": "path"},
            "artifacts_dir": str(artifact_dir),
        },
    )
    _write_json(
        artifact_dir / "prompt_step_002_code.json",
        {
            "workflow_name": "feature_workflow",
            "step_name": "code",
            "step_type": "agent",
            "step_index": 1,
            "total_steps": 2,
            "status": "completed",
            "hidden": True,
            "model": "gpt-5.6-sol",
            "llm_provider": "codex",
            "output": {"diff_path": "/tmp/feature.diff"},
            "output_types": {"diff_path": "path"},
            "artifacts_dir": str(artifact_dir),
        },
    )


def _write_monitor_done(projects_root: Path, index: int) -> None:
    project = "home"
    artifact_dir = _artifact_dir(projects_root, project, "ace-run", index)
    project_file = projects_root / project / f"{project}.sase"
    name = "feature-monitor"
    cl_name = "feature-monitor"
    family_shell = {
        "kind": "monitor",
        "id": "mon-fixture",
        "state": "completed",
        "start_status": "MONITORING",
        "stop_status": "MONITORED",
        "monitor": {
            "command": "sleep 0",
            "cwd": str(projects_root / project),
            "settled": True,
        },
    }
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name=name,
            cl_name=cl_name,
            provider="codex",
            model="gpt-5.6-sol",
        )
        | {
            "agent_family": "feature-monitor-family",
            "agent_family_role": "monitor",
            "family_shell": family_shell,
        },
    )
    _write_json(
        artifact_dir / "done.json",
        _done_payload(
            name=name,
            cl_name=cl_name,
            provider="codex",
            model="gpt-5.6-sol",
            project_file=project_file,
            outcome="monitored",
        )
        | {
            "status_label": "MONITORED",
            "family_shell": family_shell,
        },
    )


def _write_provenance_completed(projects_root: Path, index: int) -> None:
    project = "gh_sase-org__sase"
    artifact_dir = _artifact_dir(projects_root, project, "ace-run", index)
    project_file = projects_root / project / f"{project}.sase"
    name = "feature-remote-provenance"
    cl_name = "feature-remote"
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name=name,
            cl_name=cl_name,
            provider="codex",
            model="gpt-5.6-sol",
            provenance=True,
        ),
    )
    _write_json(
        artifact_dir / "done.json",
        _done_payload(
            name=name,
            cl_name=cl_name,
            provider="codex",
            model="gpt-5.6-sol",
            project_file=project_file,
            provenance=True,
        ),
    )


def _write_generic_completed(projects_root: Path, index: int) -> None:
    project = _PROJECTS[index % len(_PROJECTS)]
    workflow = "mentor-bench" if index % 29 == 0 else "ace-run"
    provider = _PROVIDERS[index % len(_PROVIDERS)]
    model = _MODELS[index % len(_MODELS)]
    hidden = index % 97 == 0
    provenance = index % 211 == 0
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


def write_completed_artifact(
    projects_root: Path,
    index: int,
    *,
    project: str = "gh_sase-org__sase",
    workflow: str = "ace-run",
    provider: str = "codex",
    model: str = "gpt-5.6-sol",
    hidden: bool = False,
    outcome: str = "completed",
    source_machine: str | None = None,
    owner_machine: str | None = None,
    meta_source_machine: str | None = None,
    done_source_machine: str | None = None,
    meta_owner_machine: str | None = None,
    done_owner_machine: str | None = None,
    agent_family: str | None = None,
    agent_family_role: str | None = None,
    agent_clan: str | None = None,
    agent_clan_generation: str | None = None,
    parent_timestamp: str | None = None,
) -> Path:
    """Write one additional completed artifact without touching the index.

    Later phases use this to add production-shaped rows *after* a fixture's
    index has already been built, so the oracle can exercise post-build
    discovery and marker mutation without a full rebuild. Choose ``index``
    distinct from every index the base fixture already used (any value
    ``>= artifact_count``, or negative for a timestamp newer than the base
    fixture's rows, is always safe).

    ``source_machine`` and ``owner_machine`` apply to both markers when the
    more specific ``meta_*`` / ``done_*`` arguments are omitted. Pass values
    that differ to reproduce a conflicting-provenance row: live evaluation
    matches either field, and the indexed candidate must preserve both.
    """
    artifact_dir = _artifact_dir(projects_root, project, workflow, index)
    project_file = projects_root / project / f"{project}.sase"
    name = f"post-build-agent-{index:05d}"
    cl_name = f"post-build-{index % 37:02d}"
    meta = _meta_payload(
        index=index,
        name=name,
        cl_name=cl_name,
        provider=provider,
        model=model,
        hidden=hidden,
    )
    done = _done_payload(
        name=name,
        cl_name=cl_name,
        provider=provider,
        model=model,
        project_file=project_file,
        outcome=outcome,
        hidden=hidden,
    )
    if source_machine is not None:
        meta["source_machine"] = source_machine
        done["source_machine"] = source_machine
    if owner_machine is not None:
        owner = {"username": "bryan", "machine_name": owner_machine}
        meta["imported_source_owner"] = owner
        done["imported_source_owner"] = owner
    if meta_source_machine is not None:
        meta["source_machine"] = meta_source_machine
    if done_source_machine is not None:
        done["source_machine"] = done_source_machine
    if meta_owner_machine is not None:
        meta["imported_source_owner"] = {
            "username": "bryan",
            "machine_name": meta_owner_machine,
        }
    if done_owner_machine is not None:
        done["imported_source_owner"] = {
            "username": "bryan",
            "machine_name": done_owner_machine,
        }
    if agent_family is not None:
        meta["agent_family"] = agent_family
        if agent_family_role is not None:
            meta["agent_family_role"] = agent_family_role
    if agent_clan is not None:
        meta["agent_clan"] = agent_clan
        if agent_clan_generation is not None:
            meta["agent_clan_generation"] = agent_clan_generation
    if parent_timestamp is not None:
        meta["parent_timestamp"] = parent_timestamp
    _write_json(artifact_dir / "agent_meta.json", meta)
    _write_json(artifact_dir / "done.json", done)
    return artifact_dir


def set_artifact_machine_provenance(
    artifact_dir: Path,
    *,
    source_machine: str | None = None,
    owner_machine: str | None = None,
) -> None:
    """Rewrite machine provenance on an already-indexed artifact's markers."""

    for marker_name in ("agent_meta.json", "done.json"):
        path = artifact_dir / marker_name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if source_machine is None:
            payload.pop("source_machine", None)
        else:
            payload["source_machine"] = source_machine
        if owner_machine is None:
            payload.pop("imported_source_owner", None)
        else:
            payload["imported_source_owner"] = {
                "username": "bryan",
                "machine_name": owner_machine,
            }
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def set_artifact_hidden(artifact_dir: Path, hidden: bool) -> None:
    """Flip the ``hidden`` marker on an existing artifact's JSON markers in place.

    Simulates a mutation that moves a row into or out of visibility (the
    index query wire always sets ``include_hidden=False``) without a full
    index rebuild, so callers can exercise revalidate-driven repair of an
    already-indexed row.
    """
    for marker_name in ("done.json", "agent_meta.json"):
        path = artifact_dir / marker_name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if hidden:
            payload["hidden"] = True
        else:
            payload.pop("hidden", None)
        _write_json(path, payload)


def delete_artifact(artifact_dir: Path) -> None:
    """Remove an artifact directory outright, simulating a deleted run."""
    shutil.rmtree(artifact_dir, ignore_errors=True)


__all__ = [
    "DEFAULT_ARCHIVE_ARTIFACT_COUNT",
    "SyntheticArchiveFixture",
    "build_synthetic_agent_archive",
    "delete_artifact",
    "rebuild_index",
    "set_artifact_hidden",
    "write_completed_artifact",
]
