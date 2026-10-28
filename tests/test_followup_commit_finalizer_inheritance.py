"""In-process followups inherit opened-repository finalizer responsibility."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase._linked_repo_markers import (
    opened_external_repo_records,
    record_opened_external_repo,
)
from sase.axe.run_agent_helpers import create_followup_artifacts
from sase.llm_provider.commit_finalizer_baseline import load_finalizer_baseline_records
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.repo_open_log import filter_repo_open_events, read_repo_open_events
from tests.finalizers_live_e2e_test_helpers import init_live_repo


def test_create_followup_artifacts_inherits_opened_repo_marker_and_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = init_live_repo(tmp_path / "workspace")
    external = init_live_repo(
        workspace / "sase" / "repos" / "external" / "projects" / "widget"
    )
    parent = tmp_path / "parent-artifacts"
    parent.mkdir()
    child = tmp_path / "child-artifacts"
    child.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(parent))
    record_opened_external_repo(
        "widget",
        str(external),
        reason="inspect in-process followup source",
        opened_at="2026-10-27T11:00:00+00:00",
    )
    parent_records = load_finalizer_baseline_records(parent)
    assert parent_records is not None
    original = next(item for item in parent_records if item.scope == "opened_repo")
    (external / "parent-work.txt").write_text(
        "uncommitted predecessor work\n", encoding="utf-8"
    )
    audit_log = tmp_path / "repo_opens.jsonl"
    monkeypatch.setattr(
        "sase.repo_open_log._repo_open_log_path", lambda _project: audit_log
    )

    monkeypatch.setenv("SASE_AGENT_NAME", "stale-parent-env")
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "20261027120000")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(workspace))
    monkeypatch.setattr(
        "sase.axe.run_agent_helpers.create_artifacts_directory",
        lambda *_args, **_kwargs: str(child),
    )
    result = create_followup_artifacts(
        "sase-test-project",
        {
            "name": "parent-agent",
            "workspace_dir": str(workspace),
            "workspace_num": 8,
        },
        "--code",
        "20261027115900",
        workspace_num=8,
        agent_name_override="child-agent",
        prev_artifacts_dir=str(parent),
    )

    assert result == str(child)
    child_records = load_finalizer_baseline_records(child)
    assert child_records is not None
    inherited = next(item for item in child_records if item.path == original.path)
    assert inherited.fingerprints == original.fingerprints == {}
    dirty = collect_dirty_state(str(workspace), artifact_root=child)
    external_dirty = next(
        repo for repo in dirty.repos if repo.path == str(external.resolve())
    )
    assert external_dirty.changed_files == ("parent-work.txt",)
    assert opened_external_repo_records(child)["widget"]["reason"] == (
        "inspect in-process followup source"
    )
    events = filter_repo_open_events(
        read_repo_open_events(log_path=audit_log), agent_name="child-agent"
    )
    assert len(events) == 1
    assert events[0].artifacts_dir == str(child.resolve())
    assert events[0].workspace_num == 8
    assert events[0].reason == (
        "Inherited opened-repository responsibility from parent-agent"
    )
    assert events[0].agent_name != "stale-parent-env"
