"""Shared fixtures for ``sase.monitor`` tests.

Builds real ``agent_meta.json`` / ``done.json`` files under a sandboxed
``SASE_HOME`` and a real ``.sase`` project file for workspace claims, then
reads scan-shaped records straight off disk -- bypassing the Rust-backed
artifact index/scanner so these tests do not depend on a compiled binding.

Also carries the bounded-wait helpers the monitor tests use to poll for
markers written by real supervisor subprocesses.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

from sase.core.agent_scan_wire import AgentMetaWire, DoneMarkerWire
from sase.core.agent_scan_wire_records import AgentArtifactRecordWire
from sase.core.paths import sase_projects_dir
from sase.core.wire import known_field_kwargs
from sase.running_field import WorkspaceClaim

DEAD_PID = 99_999_999
POLL_TIMEOUT = 60.0
POLL_INTERVAL = 0.1


def make_starter_agent(
    project: str,
    timestamp: str,
    name: str,
    **meta_overrides: object,
) -> str:
    """Create a real sharded artifacts dir for a fake single (non-family) agent."""
    artifact_dir = (
        sase_projects_dir()
        / project
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )
    artifact_dir.mkdir(parents=True)
    meta: dict[str, object] = {"name": name, "model": "test", **meta_overrides}
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return str(artifact_dir)


def write_project_file(
    project: str,
    *,
    running_claims: list[WorkspaceClaim] | None = None,
) -> str:
    """Write a real ``.sase`` project file with an optional RUNNING field."""
    project_dir = sase_projects_dir() / project
    project_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=project_dir, mode="w", delete=False, suffix=".sase", prefix=f"{project}."
    ) as f:
        f.write("# Test Project\n\n")
        if running_claims:
            f.write("RUNNING:\n")
            for claim in running_claims:
                f.write(claim.to_line() + "\n")
        f.write("NAME: Test Feature\nDESCRIPTION:\n  Test\nPARENT: None\nPR: None\n")
        f.write("STATUS: Ready\n")
        path = f.name
    canonical = project_dir / f"{project}.gp"
    Path(path).replace(canonical)
    return str(canonical)


def record_from_disk(artifacts_dir: str | Path) -> AgentArtifactRecordWire:
    """Read one real artifacts dir back into a scan-shaped record."""
    path = Path(artifacts_dir).resolve()
    relative = path.relative_to(sase_projects_dir().resolve())
    project_name = relative.parts[0]
    project_dir = sase_projects_dir() / project_name

    meta = _load(path / "agent_meta.json", AgentMetaWire)
    done_path = path / "done.json"
    done = _load(done_path, DoneMarkerWire) if done_path.exists() else None
    return AgentArtifactRecordWire(
        project_name=project_name,
        project_dir=str(project_dir),
        project_file=str(project_dir / f"{project_name}.gp"),
        workflow_dir_name="ace-run",
        artifact_dir=str(path),
        timestamp=path.name,
        agent_meta=meta,
        done=done,
        has_done_marker=done_path.exists(),
    )


def patch_project_records(
    monkeypatch: pytest.MonkeyPatch,
    artifacts_dirs: list[str],
) -> None:
    """Make ``sase.monitor.store`` see exactly *artifacts_dirs*, read live from disk."""
    from sase.monitor import store as store_module

    def fake(
        project_name: str | None, *, only_monitors: bool = False
    ) -> list[AgentArtifactRecordWire]:
        del only_monitors
        return [
            record
            for record in (record_from_disk(d) for d in artifacts_dirs)
            if project_name is None or record.project_name == project_name
        ]

    monkeypatch.setattr(store_module, "_project_records", fake)


def wait_for_done(
    artifacts_dir: str,
    *,
    timeout: float = POLL_TIMEOUT,
) -> dict[str, object]:
    """Block until a monitor member writes ``done.json`` and return it."""
    done_path = Path(artifacts_dir) / "done.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if done_path.exists():
            try:
                return json.loads(done_path.read_text())
            except json.JSONDecodeError:
                pass
        time.sleep(POLL_INTERVAL)
    raise AssertionError(f"monitor at {artifacts_dir} never finished")


def wait_for_path(path: Path, *, timeout: float = POLL_TIMEOUT) -> None:
    """Block until *path* exists."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(POLL_INTERVAL)  # sase-test-wait: poll subprocess file marker
    raise AssertionError(f"{path} was not created")


def _load[WireT](path: Path, cls: type[WireT]) -> WireT:
    data = json.loads(path.read_text(encoding="utf-8"))
    return cls(**known_field_kwargs(cls, data))
