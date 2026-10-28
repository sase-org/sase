"""Opened-repository responsibility transfer across continuation artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase._linked_repo_markers import (
    OPENED_LINKED_FILENAME,
    OPENED_SIBLINGS_FILENAME,
    opened_external_repo_records,
    opened_linked_repo_records,
    opened_repo_records,
    record_opened_external_repo,
    merge_opened_repo_records,
)
from sase.llm_provider.commit_finalizer_baseline import (
    FINALIZER_BASELINE_FILENAME,
    capture_dirty_baseline,
    capture_opened_repo_dirty_baseline,
    load_finalizer_baseline_records,
)
from sase.llm_provider.commit_finalizer_inheritance import (
    INHERITANCE_DIAGNOSTICS_FILENAME,
    inherit_commit_finalizer_responsibility,
)
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.repo_open_log import filter_repo_open_events, read_repo_open_events

from tests.finalizers_live_e2e_test_helpers import init_live_repo, run_git


def _inherit(
    parent: Path,
    child: Path,
    workspace: Path,
    *,
    predecessor: str = "agent-0",
    successor: str = "agent-1",
    workspace_num: int = 3,
) -> bool:
    return inherit_commit_finalizer_responsibility(
        parent_artifacts_dir=str(parent),
        child_artifacts_dir=str(child),
        predecessor_name=predecessor,
        successor_name=successor,
        project_name="sase-test-project",
        parent_workspace_dir=str(workspace),
        child_workspace_dir=str(workspace),
        workspace_num=workspace_num,
    )


def test_inheritance_preserves_protection_and_is_idempotent_across_two_handoffs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = init_live_repo(tmp_path / "workspace")
    external = init_live_repo(
        workspace / "sase" / "repos" / "external" / "projects" / "widget"
    )
    (external / "protected.txt").write_text("foreign\n", encoding="utf-8")
    parent = tmp_path / "parent-artifacts"
    parent.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(parent))
    record_opened_external_repo(
        "widget",
        str(external),
        reason="inspect the widget source",
        opened_at="2026-10-27T11:00:00+00:00",
    )
    original_records = load_finalizer_baseline_records(parent)
    assert original_records is not None
    original = next(
        record for record in original_records if record.scope == "opened_repo"
    )
    (external / "README.md").write_text("predecessor edit\n", encoding="utf-8")
    (external / "agent-created.txt").write_text(
        "successor should commit\n", encoding="utf-8"
    )

    audit_log = tmp_path / "repo_opens.jsonl"
    monkeypatch.setattr(
        "sase.repo_open_log._repo_open_log_path", lambda _project: audit_log
    )
    monkeypatch.setenv("SASE_AGENT_NAME", "stale-predecessor-env")
    child = tmp_path / "child-artifacts"
    assert _inherit(parent, child, workspace)

    child_records = load_finalizer_baseline_records(child)
    assert child_records is not None
    inherited = next(
        record for record in child_records if record.scope == "opened_repo"
    )
    assert inherited == original
    marker = opened_external_repo_records(child)["widget"]
    assert marker["reason"] == "inspect the widget source"
    assert marker["opened_at"] == "2026-10-27T11:00:00+00:00"
    assert marker["ref"] == "widget"

    dirty = collect_dirty_state(str(workspace), artifact_root=child)
    external_dirty = next(repo for repo in dirty.repos if repo.kind == "external")
    assert external_dirty.name == "widget"
    assert set(external_dirty.changed_files) == {"README.md", "agent-created.txt"}

    first_child_baseline_bytes = (child / FINALIZER_BASELINE_FILENAME).read_bytes()
    assert _inherit(parent, child, workspace)
    assert (
        child / FINALIZER_BASELINE_FILENAME
    ).read_bytes() == first_child_baseline_bytes
    assert len(opened_external_repo_records(child)) == 1
    first_events = filter_repo_open_events(
        read_repo_open_events(log_path=audit_log), agent_name="agent-1"
    )
    assert len(first_events) == 1
    assert first_events[0].artifacts_dir == str(child.resolve())
    assert first_events[0].reason == (
        "Inherited opened-repository responsibility from agent-0"
    )
    assert first_events[0].agent_name == "agent-1"
    assert first_events[0].agent_source == "agent_meta"

    second = tmp_path / "second-continuation-artifacts"
    assert _inherit(
        child, second, workspace, predecessor="agent-1", successor="agent-2"
    )
    second_records = load_finalizer_baseline_records(second)
    assert second_records is not None
    assert (
        next(record for record in second_records if record.scope == "opened_repo")
        == original
    )
    assert len(opened_external_repo_records(second)) == 1
    second_events = filter_repo_open_events(
        read_repo_open_events(log_path=audit_log), agent_name="agent-2"
    )
    assert len(second_events) == 1
    assert second_events[0].artifacts_dir == str(second.resolve())


def test_inheritance_recovers_only_canonical_opened_repo_baselines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = init_live_repo(tmp_path / "workspace")
    # Keep this checkout outside the workspace scan so the canonical record
    # below is specifically an opened_repo baseline, not a run_start record.
    external = init_live_repo(tmp_path / "external-repos" / "recoverable")
    parent = tmp_path / "parent"
    parent.mkdir()
    capture_dirty_baseline(str(workspace), str(parent))
    assert (
        capture_opened_repo_dirty_baseline(
            "external:recoverable",
            str(external),
            kind="external",
            name="recoverable",
            artifacts_dir=str(parent),
        )
        is None
    )
    (external / "later.txt").write_text("agent work\n", encoding="utf-8")
    audit_log = tmp_path / "repo_opens.jsonl"
    monkeypatch.setattr(
        "sase.repo_open_log._repo_open_log_path", lambda _project: audit_log
    )

    child = tmp_path / "child"
    assert _inherit(parent, child, workspace)

    record = opened_external_repo_records(child)["recoverable"]
    assert record["workspace_dir"] == str(external.resolve())
    assert record["reason"] == "Recovered from an inherited opened_repo baseline"
    assert not opened_linked_repo_records(child)
    events = filter_repo_open_events(
        read_repo_open_events(log_path=audit_log), agent_name="agent-1"
    )
    assert len(events) == 1
    assert events[0].repo == "recoverable"


def test_inheritance_reads_legacy_markers_and_merges_child_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = init_live_repo(tmp_path / "workspace")
    linked = init_live_repo(workspace / "sase" / "repos" / "linked" / "core")
    external = init_live_repo(
        workspace / "sase" / "repos" / "external" / "projects" / "widget"
    )
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    parent.mkdir()
    child.mkdir()
    (parent / OPENED_SIBLINGS_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "siblings": [
                    {
                        "name": "core",
                        "workspace_dir": str(linked),
                        "reason": "legacy open reason",
                        "opened_at": "2026-10-27T09:00:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    merge_opened_repo_records(
        child,
        {
            "widget": {
                "name": "widget",
                "workspace_dir": str(external),
                "reason": "opened by child",
                "opened_at": "2026-10-27T10:00:00+00:00",
                "kind": "external",
                "ref": "widget",
            }
        },
    )
    audit_log = tmp_path / "repo_opens.jsonl"
    monkeypatch.setattr(
        "sase.repo_open_log._repo_open_log_path", lambda _project: audit_log
    )

    assert not _inherit(parent, child, workspace)

    assert opened_linked_repo_records(child)["core"]["reason"] == "legacy open reason"
    assert opened_external_repo_records(child)["widget"]["reason"] == "opened by child"
    assert len(opened_repo_records(child)) == 2
    canonical = json.loads((child / OPENED_LINKED_FILENAME).read_text(encoding="utf-8"))
    legacy = json.loads((child / OPENED_SIBLINGS_FILENAME).read_text(encoding="utf-8"))
    assert {row["name"] for row in canonical["linked_repos"]} == {"core", "widget"}
    assert [row["name"] for row in legacy["siblings"]] == ["core"]
    # The child marker is authoritative and already has its own open audit.
    events = read_repo_open_events(log_path=audit_log)
    assert [event.repo for event in events] == ["core"]


def test_clean_inherited_external_repo_does_not_create_dirty_obligation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = init_live_repo(tmp_path / "workspace")
    external = init_live_repo(
        workspace / "sase" / "repos" / "external" / "projects" / "clean"
    )
    parent = tmp_path / "parent"
    parent.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(parent))
    record_opened_external_repo("clean", str(external), reason="inspect clean repo")
    child = tmp_path / "child"
    assert _inherit(parent, child, workspace)

    assert opened_external_repo_records(child)["clean"]
    assert collect_dirty_state(str(workspace), artifact_root=child).is_clean


def test_mismatched_workspace_does_not_adopt_predecessor_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_workspace = init_live_repo(tmp_path / "workspace-1")
    external = init_live_repo(
        parent_workspace / "sase" / "repos" / "external" / "projects" / "widget"
    )
    child_workspace = init_live_repo(tmp_path / "workspace-2")
    parent = tmp_path / "parent"
    parent.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(parent))
    record_opened_external_repo("widget", str(external), reason="inspect upstream")
    (external / "stranded.txt").write_text("belongs to predecessor\n", encoding="utf-8")
    child = tmp_path / "child"

    assert not inherit_commit_finalizer_responsibility(
        parent_artifacts_dir=str(parent),
        child_artifacts_dir=str(child),
        predecessor_name="agent-0",
        successor_name="agent-1",
        project_name="sase-test-project",
        parent_workspace_dir=str(parent_workspace),
        child_workspace_dir=str(child_workspace),
        workspace_num=4,
    )

    assert not opened_repo_records(child)
    assert not (child / FINALIZER_BASELINE_FILENAME).exists()
    diagnostics = json.loads(
        (child / INHERITANCE_DIAGNOSTICS_FILENAME).read_text(encoding="utf-8")
    )
    assert any("different workspace" in item for item in diagnostics["diagnostics"])
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(child_workspace))
    assert collect_dirty_state(str(child_workspace), artifact_root=child).is_clean
    assert run_git(external, "status", "--short").stdout.strip() == "?? stranded.txt"
