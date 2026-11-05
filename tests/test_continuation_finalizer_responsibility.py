"""Repository responsibility survives session-root attachment and late opens."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Literal

import pytest

from sase._linked_repo_markers import opened_repo_records, record_opened_repo
from sase.agent.agent_session_attach import load_agent_session_attach_plan_from_env
from sase.agent.detached_child import agent_session_attach_env
from sase.axe.run_agent_runner_bootstrap import _capture_commit_finalizer_baseline
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.linked_repos import LINKED_REPOS_JSON_ENV
from sase.llm_provider.commit_finalizer_baseline import (
    FINALIZER_BASELINE_FILENAME,
    bind_run_start_baseline_to_workspace,
    capture_dirty_baseline,
    load_finalizer_baseline_records,
)
from sase.llm_provider.commit_finalizer_inheritance import (
    INHERITANCE_DIAGNOSTICS_FILENAME,
)
from sase.macro.directives import PromptDirectives
from tests.finalizers_live_e2e_test_helpers import (
    attach_bare_remote,
    commit_instance,
    config_for,
    init_live_repo,
    isolate_host_config,
    prepare_live_env,
    run_controller,
    run_git,
    submit_from_context,
    use_config,
    use_real_git_stitch,
)
from tests.test_run_agent_runner_bootstrap_baseline import _agent_session_attach_plan


@pytest.mark.parametrize("kind", ["linked", "external"])
def test_bootstrap_inherits_starter_across_multiple_root_attached_continuations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: Literal["linked", "external"]
) -> None:
    isolate_host_config(monkeypatch, tmp_path)
    workspace = init_live_repo(tmp_path / "workspace")
    root, starter = tmp_path / "root", tmp_path / "starter"
    capture_dirty_baseline(str(workspace), str(root))
    starter.mkdir()
    (starter / FINALIZER_BASELINE_FILENAME).write_bytes(
        (root / FINALIZER_BASELINE_FILENAME).read_bytes()
    )
    linked = init_live_repo(workspace / "sase" / "repos" / "widget")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(starter))
    record_opened_repo("widget", str(linked), kind=kind, reason="starter opened it")
    (linked / "session.txt").write_text("owned by this session\n")
    original = load_finalizer_baseline_records(starter)
    assert original is not None
    assert next(row for row in original if row.path == str(linked)).fingerprints == {}
    monkeypatch.setattr(
        "sase.repo_open_log._repo_open_log_path",
        lambda _project: tmp_path / "opens.jsonl",
    )
    plan = replace(
        _agent_session_attach_plan(parent_artifacts_dir=str(root)),
        parent_workspace_dir=str(workspace),
        parent_workspace_num=3,
        predecessor_artifacts_dir=str(starter),
        predecessor_name="session--code",
    )
    for index in range(2):
        child = tmp_path / f"child-{index}"
        for key, value in agent_session_attach_env(plan).items():
            monkeypatch.setenv(key, value)
        assert _capture_commit_finalizer_baseline(
            str(child), workspace_dir=str(workspace), workspace_num=3
        )
        assert load_finalizer_baseline_records(child) == original
        assert opened_repo_records(child)["widget"]["reason"] == "starter opened it"
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(child))
        record_opened_repo("widget", str(linked), kind=kind, reason="repair opens it")
        assert load_finalizer_baseline_records(child) == original
        plan = replace(plan, predecessor_artifacts_dir=str(child))
        # The second continuation inherits this child's marker, not the root's.
        record_opened_repo("widget", str(linked), kind=kind, reason="starter opened it")


@pytest.mark.parametrize("legacy", [False, True])
def test_attach_env_round_trip_optional_predecessor(
    tmp_path: Path, legacy: bool
) -> None:
    plan = replace(
        _agent_session_attach_plan(parent_artifacts_dir=str(tmp_path / "root")),
        predecessor_artifacts_dir=str(tmp_path / "starter"),
        predecessor_name="session--code",
    )
    env = agent_session_attach_env(plan)
    if legacy:
        payload = json.loads(env["SASE_AGENT_SESSION_ATTACH"])
        payload.pop("predecessor_artifacts_dir")
        payload.pop("predecessor_name")
        env["SASE_AGENT_SESSION_ATTACH"] = json.dumps(payload)
        plan = replace(plan, predecessor_artifacts_dir=None, predecessor_name=None)
    assert load_agent_session_attach_plan_from_env(env) == plan


@pytest.mark.parametrize("missing_timestamp", [False, True])
def test_missing_starter_falls_back_with_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_timestamp: bool
) -> None:
    isolate_host_config(monkeypatch, tmp_path)
    workspace = init_live_repo(tmp_path / "workspace")
    root = tmp_path / "root"
    capture_dirty_baseline(str(workspace), str(root))
    plan = replace(
        _agent_session_attach_plan(parent_artifacts_dir=str(root)),
        predecessor_artifacts_dir=None if missing_timestamp else str(tmp_path / "gone"),
        predecessor_name="missing starter",
    )
    for key, value in agent_session_attach_env(plan).items():
        monkeypatch.setenv(key, value)
    child = tmp_path / "child"
    assert _capture_commit_finalizer_baseline(str(child))
    assert load_finalizer_baseline_records(child) == load_finalizer_baseline_records(
        root
    )
    diagnostics = json.loads((child / INHERITANCE_DIAGNOSTICS_FILENAME).read_text())
    assert "missing starter" in diagnostics["diagnostics"][0]
    assert "attach parent" in diagnostics["diagnostics"][0]


@pytest.mark.parametrize("existing_scope", [None, "run_start", "opened_repo"])
def test_inherited_boot_completes_only_missing_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing_scope: str | None
) -> None:
    isolate_host_config(monkeypatch, tmp_path)
    workspace = init_live_repo(tmp_path / "workspace")
    artifacts = tmp_path / "artifacts"
    capture_dirty_baseline(str(workspace), str(artifacts))
    linked = init_live_repo(workspace / "sase" / "repos" / "widget")
    (linked / "session.txt").write_text("session work\n")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    if existing_scope:
        record_opened_repo("widget", str(linked), kind="linked")
        path = artifacts / FINALIZER_BASELINE_FILENAME
        payload = json.loads(path.read_text())
        for record in payload["repositories"]:
            if record["path"] == str(linked):
                record["scope"] = existing_scope
        path.write_text(json.dumps(payload))
    before = load_finalizer_baseline_records(artifacts)
    assert before is not None
    bind_run_start_baseline_to_workspace(str(workspace), str(artifacts), inherited=True)
    after = load_finalizer_baseline_records(artifacts)
    assert after is not None
    assert all(row in after for row in before)
    linked_record = next(row for row in after if row.path == str(linked))
    if existing_scope is None:
        assert linked_record.scope == "run_start"
        assert linked_record.fingerprints == {}
    else:
        assert linked_record.scope == existing_scope
        assert "session.txt" in linked_record.fingerprints
    record_opened_repo("widget", str(linked), kind="linked", reason="late open")
    assert load_finalizer_baseline_records(artifacts) == after
    bound_bytes = (artifacts / FINALIZER_BASELINE_FILENAME).read_bytes()
    bind_run_start_baseline_to_workspace(str(workspace), str(artifacts), inherited=True)
    assert (artifacts / FINALIZER_BASELINE_FILENAME).read_bytes() == bound_bytes


def test_late_repair_open_after_declaration_still_commits_linked_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolate_host_config(monkeypatch, tmp_path)
    workspace = init_live_repo(tmp_path / "workspace")
    artifacts = tmp_path / "artifacts"
    prepare_live_env(monkeypatch, artifacts, workspace)
    capture_dirty_baseline(str(workspace), str(artifacts))
    linked = init_live_repo(tmp_path / "linked")
    attach_bare_remote(linked, tmp_path / "linked-remote.git")
    monkeypatch.setenv(
        LINKED_REPOS_JSON_ENV,
        json.dumps([{"name": "widget", "workspace_dir": str(linked)}]),
    )
    (linked / "session.txt").write_text("session work\n")
    bind_run_start_baseline_to_workspace(str(workspace), str(artifacts), inherited=True)
    records = load_finalizer_baseline_records(artifacts)
    assert records is not None
    assert next(row for row in records if row.path == str(linked)).fingerprints == {}
    use_config(monkeypatch, config_for({"commit": commit_instance()}, ("commit",)))
    use_real_git_stitch(monkeypatch)
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    submit_from_context(artifacts)
    head = run_git(linked, "rev-parse", "HEAD").stdout
    record_opened_repo("widget", str(linked), kind="linked", reason="conflict repair")

    assert run_controller(artifacts).content == "done"
    assert run_git(linked, "rev-parse", "HEAD").stdout != head
    assert run_git(linked, "status", "--porcelain").stdout == ""
    assert run_git(linked, "show", "HEAD:session.txt").stdout == "session work\n"
