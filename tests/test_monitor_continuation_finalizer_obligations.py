"""A monitor session-attach continuation keeps opened-repository obligations."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

import sase.monitor.followup as followup_module
from sase.agent._agent_session_attach_types import (
    AGENT_SESSION_ATTACH_ENV,
    AgentSessionAttachDirective,
)
from sase.agent._agent_session_attach_resolution import (
    resolve_agent_session_attach_plan,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.axe.run_agent_runner_bootstrap import _capture_commit_finalizer_baseline
from sase.finalizers.declaration import publish_final_context
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.linked_repos import record_opened_external_repo
from sase.llm_provider.commit_finalizer_baseline import load_finalizer_baseline_records
from sase.llm_provider.commit_finalizer_git import git_changed_files
from sase.repo_open_log import filter_repo_open_events, read_repo_open_events
from sase.macro.directives import PromptDirectives
from tests.finalizers_live_e2e_test_helpers import (
    attach_bare_remote,
    commit_instance,
    config_for,
    load_result,
    real_git_stitch,
    run_controller,
    run_git,
    submit_from_context,
    use_config,
)
from tests.monitor._followup_fixtures import (
    _SETTLE_TIMEOUT,
    _capture_with_output,
    _fake_result,
    _promote_and_start_monitor,
)


def _init_root_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=path,
        check=True,
    )
    (path / ".gitignore").write_text(
        ".sase/\n"
        "sase/repos/\n"
        "sase-home/\n"
        "empty-config/\n"
        "continuation-artifacts/\n"
        "repo_opens.jsonl\n"
        "repo_opens.lock\n"
        "widget.git/\n",
        encoding="utf-8",
    )
    (path / "README.md").write_text("workspace\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=path, check=True)


def _init_nested_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.name", "SASE Live Test"], cwd=path, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "sase-live@example.invalid"],
        cwd=path,
        check=True,
    )
    (path / ".gitignore").write_text("", encoding="utf-8")
    (path / "README.md").write_text("external fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=path, check=True)
    return path


def test_monitor_continuation_discovers_and_commits_inherited_external_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.finalizers_live_e2e_test_helpers import isolate_host_config

    isolate_host_config(monkeypatch, tmp_path)
    _init_root_repo(tmp_path)
    with monkeypatch.context() as monitor_monkeypatch:
        monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
            tmp_path, monitor_monkeypatch
        )
    monitor_meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())

    # Resolve through the same session-attach entry point as the monitor
    # launcher so the marker is stored under the actual continuation parent.
    source_plan = resolve_agent_session_attach_plan(
        AgentSessionAttachDirective(parent="acme", suffix="@"),
        project_name="proj",
    )
    predecessor_artifacts = Path(source_plan.parent_artifacts_dir)
    assert predecessor_artifacts.exists()

    external = _init_nested_repo(
        tmp_path / "sase" / "repos" / "external" / "projects" / "widget"
    )
    attach_bare_remote(external, tmp_path / "widget.git")
    (external / "protected.txt").write_text(
        "pre-existing foreign content\n", encoding="utf-8"
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(predecessor_artifacts))
    record_opened_external_repo(
        "widget",
        str(external),
        reason="inspect the widget checkout",
        opened_at="2026-10-27T10:00:00+00:00",
    )
    parent_baselines = load_finalizer_baseline_records(predecessor_artifacts)
    assert parent_baselines is not None
    original_external_baseline = next(
        record for record in parent_baselines if record.scope == "opened_repo"
    )
    (external / "README.md").write_text("predecessor tracked work\n", encoding="utf-8")
    (external / "created-by-predecessor.txt").write_text(
        "predecessor untracked work\n", encoding="utf-8"
    )

    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result(workspace_dir=str(tmp_path), workspace_num=3)

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)
    launched = followup_module.launch_followup_agent(
        monitor_dir,
        monitor_meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        capture=_capture_with_output(monitor_dir, "check finished\n"),
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )
    assert launched.launched is True
    child_attach = json.loads(captured["extra_env"][AGENT_SESSION_ATTACH_ENV])
    assert child_attach["parent_artifacts_dir"] == str(predecessor_artifacts)
    assert child_attach["parent_workspace_dir"] == str(tmp_path)

    audit_log = tmp_path / "repo_opens.jsonl"
    monkeypatch.setattr(
        "sase.repo_open_log._repo_open_log_path", lambda _project: audit_log
    )
    child_artifacts = tmp_path / "continuation-artifacts"
    monkeypatch.setenv(AGENT_SESSION_ATTACH_ENV, json.dumps(child_attach))
    assert _capture_commit_finalizer_baseline(
        str(child_artifacts),
        workspace_dir=str(tmp_path),
        workspace_num=3,
        project_name="proj",
    )

    child_baselines = load_finalizer_baseline_records(child_artifacts)
    assert child_baselines is not None
    inherited_external_baseline = next(
        record for record in child_baselines if record.scope == "opened_repo"
    )
    assert inherited_external_baseline == original_external_baseline
    assert (child_artifacts / "opened_linked_workspaces.json").is_file()

    child_name = child_attach["agent_name"]
    child_events = filter_repo_open_events(
        read_repo_open_events(log_path=audit_log), agent_name=child_name
    )
    assert len(child_events) == 1
    assert child_events[0].artifacts_dir == str(child_artifacts.resolve())
    assert child_events[0].workspace_num == 3
    assert child_events[0].reason == (
        f"Inherited opened-repository responsibility from {source_plan.parent_name}"
    )

    monkeypatch.setenv("SASE_LINKED_REPOS_JSON", "[]")
    monkeypatch.delenv("SASE_SIBLING_REPOS_JSON", raising=False)
    use_config(
        monkeypatch,
        config_for({"commit": commit_instance()}, ("commit",)),
    )
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", real_git_stitch
    )
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_resume",
        lambda repo, context, *, bead_action=None: real_git_stitch(
            repo,
            "fix(final): resume inherited continuation work",
            (),
            context,
            bead_action=bead_action,
        ),
    )
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "continuation-run")
    monkeypatch.setenv("SASE_AGENT_NAME", child_name)
    monkeypatch.setenv("SASE_FINAL_TURN_NONCE", "continuation-nonce")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(child_artifacts))

    resolve_and_persist_finalizer_plan(
        PromptDirectives(), artifacts_dir=str(child_artifacts)
    )
    publication = publish_final_context(artifacts_dir=str(child_artifacts))
    external_obligations = [
        item for item in publication.context.obligations if item.kind == "repository"
    ]
    assert [(item.display_name, item.paths) for item in external_obligations] == [
        ("external:widget", ["README.md", "created-by-predecessor.txt"])
    ]
    external_obligation_id = external_obligations[0].obligation_id
    context = json.loads((child_artifacts / "final_context.json").read_text())
    assert (
        context["context"]["obligations"][0]["obligation_id"] == external_obligation_id
    )
    host_context = json.loads((child_artifacts / "final_context_host.json").read_text())
    host_repo = next(
        item
        for item in host_context["repositories"]
        if item["obligation_id"] == external_obligation_id
    )
    assert host_repo["path"] == str(external.resolve())
    assert host_repo["kind"] == "external"
    assert host_repo["name"] == "widget"
    assert host_repo["path_count"] == 2

    submit_from_context(child_artifacts)
    result = run_controller(child_artifacts)
    assert result.content == "done"
    assert load_result(child_artifacts)["status"] == "success"
    commits = json.loads((child_artifacts / "commit_results.json").read_text())
    assert [item["cwd"] for item in commits] == [str(external)]
    committed_sha = run_git(external, "rev-parse", "HEAD").stdout.strip()
    assert commits[0]["commit_sha"] == committed_sha
    assert (
        run_git(external, "show", "HEAD:README.md").stdout
        == "predecessor tracked work\n"
    )
    assert run_git(external, "show", "HEAD:created-by-predecessor.txt").stdout == (
        "predecessor untracked work\n"
    )
    assert git_changed_files(str(external)) == ["protected.txt"]
    assert (external / "protected.txt").read_text(encoding="utf-8") == (
        "pre-existing foreign content\n"
    )
    assert git_changed_files(str(tmp_path)) == []
    remote_sha = run_git(
        tmp_path / "widget.git", "rev-parse", "refs/heads/main"
    ).stdout.strip()
    assert remote_sha == committed_sha
