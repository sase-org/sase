"""Tier 1 index must keep the planner row across plan-approval handoff.

The agent runner mutates the planner dir's ``agent_meta.json`` several
times after ``sase plan`` SIGTERMs the process: a role-suffix update,
``promote_to_workflow`` (when the agent is the family root), a
``plan_approved=True`` write, a ``plan_action=<tale|epic|legend|commit>``
write, and finally :func:`create_followup_artifacts` for the coder /
epic / legend / commit phase. Each of those helpers calls
:func:`update_agent_artifact_index_for_marker_mutation` against the
planner dir, so the Tier 1 SQLite index must report a row for the
planner artifact dir at every step.

This regression pins the runner lifecycle so a future helper that
forgets the index upsert (or upserts the wrong dir) fails loudly.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from sase.axe.run_agent_helpers import (
    create_followup_artifacts,
    promote_to_workflow,
    update_meta_field,
    update_meta_suffix,
)
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_artifact_index,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec(RUST_EXTENSION_MODULE_NAME) is None,
    reason="sase_core_rs is required for the artifact-index lifecycle tests.",
)


_FULL_HISTORY_QUERY = AgentArtifactIndexQueryWire(
    include_active=True,
    include_recent_completed=True,
    include_full_history=True,
    active_limit=None,
    recent_completed_limit=None,
    include_hidden=True,
)


def _index_has_dir(index_path: Path, projects_root: Path, artifact_dir: Path) -> bool:
    snapshot = query_agent_artifact_index(
        index_path,
        projects_root,
        query=_FULL_HISTORY_QUERY,
        options=AgentArtifactScanOptionsWire(),
    )
    return any(record.artifact_dir == str(artifact_dir) for record in snapshot.records)


def test_planner_dir_row_survives_full_tale_handoff_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    sase_home = tmp_path / ".sase"

    projects_root = sase_home / "projects"
    planner_dir = projects_root / "myproj" / "artifacts" / "ace-run" / "20260601090000"
    planner_dir.mkdir(parents=True)
    # Realistic post-SIGTERM shape: agent_meta.json only.  No
    # workflow_state.json and no prompt_step_*.json on disk.
    (planner_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": 1,
                "name": "fam",
                "model": "gpt-x",
                "llm_provider": "claude",
                "vcs_provider": "GitHub",
                "cl_name": "myproj",
                "run_started_at": "2026-06-01T09:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    index_path = default_agent_artifact_index_path()
    assert index_path == sase_home / "agent_artifact_index.sqlite"

    # Step 0: initial upsert (mirrors ``setup_artifacts_directory``).
    assert update_agent_artifact_index_for_marker_mutation(planner_dir)
    assert _index_has_dir(index_path, projects_root, planner_dir), (
        "planner missing after initial upsert"
    )

    # Step 1: role-suffix set to ``-plan`` via ``update_meta_suffix``.
    update_meta_suffix(str(planner_dir), "-plan")
    assert _index_has_dir(index_path, projects_root, planner_dir), (
        "planner missing after update_meta_suffix"
    )

    # Step 2: promote_to_workflow stamps plan_chain_root, agent_family, etc.
    promote_to_workflow(str(planner_dir), "fam")
    assert _index_has_dir(index_path, projects_root, planner_dir), (
        "planner missing after promote_to_workflow"
    )

    # Step 3: plan_approved=True written when the user accepts the plan.
    update_meta_field(str(planner_dir), "plan_approved", True)
    assert _index_has_dir(index_path, projects_root, planner_dir), (
        "planner missing after plan_approved=True"
    )

    # Step 4: plan_action chosen (tale, epic, legend, commit).
    update_meta_field(str(planner_dir), "plan_action", "tale")
    assert _index_has_dir(index_path, projects_root, planner_dir), (
        "planner missing after plan_action=tale"
    )

    # Step 5: coder follow-up dir created; planner row must still exist.
    base_meta = json.loads((planner_dir / "agent_meta.json").read_text())
    coder_dir = create_followup_artifacts(
        project_name="myproj",
        base_meta=base_meta,
        suffix="-code",
        prev_artifacts_timestamp="20260601090000",
        agent_name_override="fam-code",
        workflow_name="fam",
    )
    coder_path = Path(coder_dir)
    assert _index_has_dir(index_path, projects_root, planner_dir), (
        "planner missing after create_followup_artifacts"
    )
    assert _index_has_dir(index_path, projects_root, coder_path), (
        "coder follow-up missing from index"
    )
