"""Auto-commit coverage for beads ``issues.jsonl`` reprojection diffs."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest.mock import MagicMock

import pytest

from sase.bead.model import IssueType, PhaseSize
from sase.core import bead_mutation_facade as rust_beads
from sase.finalizers.commit import execute_commit_finalizer
from sase.finalizers.config import ConfiguredFinalizerInstance
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.finalizers.reconciliation import prepare_commit_dirty_state
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider import commit_finalizer_git_autocommit as finalizer_autocommit
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.sdd.store import SddStore
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV
from sase.xprompt.directives import PromptDirectives


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _run_git(repo, "config", "user.name", "SASE Test")
    _run_git(repo, "config", "user.email", "sase-test@example.invalid")


def _commit_all(repo: Path, message: str) -> None:
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", message)


def _create_clean_main_repo(path: Path) -> None:
    _init_git_repo(path)
    (path / "README.md").write_text("main\n", encoding="utf-8")
    _commit_all(path, "initial main")


def _create_beads_repo_with_dirty_projection(tmp_path: Path) -> Path:
    root = tmp_path / "state"
    root.mkdir()
    rust_beads.init_store(root, "beads", issue_prefix="beads")
    beads = root / "beads"
    rust_beads.create(
        beads,
        title="One",
        issue_type=IssueType.TASK,
        size=PhaseSize.SMALL,
        task_type="bug",
        created_by="test",
    )

    correct_projection = (beads / "issues.jsonl").read_bytes()
    stale_projection = correct_projection.replace(b'"title":"One"', b'"title":"Stale"')
    assert stale_projection != correct_projection

    _init_git_repo(beads)
    (beads / "issues.jsonl").write_bytes(stale_projection)
    _commit_all(beads, "stale projection")
    (beads / "issues.jsonl").write_bytes(correct_projection)
    return beads


def _dirty_state_for(repo: Path) -> DirtyState:
    changed_files = tuple(finalizer_git.git_changed_files(str(repo)))
    return DirtyState(
        project_dir=str(repo.parent),
        repos=(
            DirtyRepo(
                name="beads",
                path=str(repo),
                changed_files=changed_files,
                kind="sdd",
            ),
        ),
        details="dirty",
    )


def _candidate(repo: Path):
    candidates = finalizer_autocommit.sdd_bead_reprojection_auto_commit_candidates(
        _dirty_state_for(repo)
    )
    assert len(candidates) == 1
    return candidates[0]


def _set_finalizer_env(monkeypatch: pytest.MonkeyPatch, project_dir: Path) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260906_120000")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(project_dir))
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    monkeypatch.delenv(SIBLING_REPOS_JSON_ENV, raising=False)

    def build(path: str) -> tuple[bool, list[str], str, str]:
        changed = finalizer_git.git_changed_files(path)
        if not changed:
            return (False, [], "", "")
        return (True, changed, "commit", "Uncommitted changes detected")

    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.build_commit_details",
        build,
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": False}},
    )
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )


def _configure_beads_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    *,
    plans_repo: Path,
    beads_repo: Path,
) -> None:
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans_repo,
        repo_root=plans_repo,
        beads_dir=beads_repo,
    )
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)


@pytest.mark.parametrize(
    ("staged", "expected_stage_path"),
    [(False, True), (True, False)],
)
def test_bead_projection_candidate_accepts_staged_and_unstaged_issues_jsonl(
    tmp_path: Path,
    staged: bool,
    expected_stage_path: bool,
) -> None:
    beads = _create_beads_repo_with_dirty_projection(tmp_path)
    if staged:
        _run_git(beads, "add", "issues.jsonl")

    candidate = _candidate(beads)

    assert candidate.path == "issues.jsonl"
    assert candidate.beads_dir == str(beads)
    assert candidate.stage_path is expected_stage_path


def test_bead_projection_candidate_rejects_extra_changed_file(tmp_path: Path) -> None:
    beads = _create_beads_repo_with_dirty_projection(tmp_path)
    (beads / "README.md").write_text("extra\n", encoding="utf-8")

    candidates = finalizer_autocommit.sdd_bead_reprojection_auto_commit_candidates(
        _dirty_state_for(beads)
    )

    assert candidates == ()


def test_bead_projection_candidate_rejects_event_stream_change(tmp_path: Path) -> None:
    beads = _create_beads_repo_with_dirty_projection(tmp_path)
    stream = next((beads / "events" / "streams").glob("*.jsonl"))
    stream.write_text(
        stream.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    candidates = finalizer_autocommit.sdd_bead_reprojection_auto_commit_candidates(
        _dirty_state_for(beads)
    )

    assert candidates == ()


def test_bead_projection_candidate_rejects_mismatched_projection(
    tmp_path: Path,
) -> None:
    beads = _create_beads_repo_with_dirty_projection(tmp_path)
    issues = beads / "issues.jsonl"
    issues.write_bytes(
        issues.read_bytes().replace(b'"title":"One"', b'"title":"Wrong"')
    )

    candidates = finalizer_autocommit.sdd_bead_reprojection_auto_commit_candidates(
        _dirty_state_for(beads)
    )

    assert candidates == ()


def test_bead_projection_candidate_commits_and_records_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads = _create_beads_repo_with_dirty_projection(tmp_path)
    _run_git(beads, "add", "issues.jsonl")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260906_120000")

    committed = finalizer_autocommit.auto_commit_sdd_bead_reprojection_candidate(
        _candidate(beads),
        artifacts_dir=artifacts,
    )

    assert committed is True
    assert _run_git(beads, "status", "--short") == ""
    message = _run_git(beads, "log", "-1", "--pretty=%B")
    assert "chore(beads): reproject issues.jsonl" in message
    assert "SASE_TYPE=beads" in message
    markers = json.loads((artifacts / "commit_results.json").read_text())
    assert markers[0]["cwd"] == str(beads)
    assert markers[0]["repo_name"] == "beads"
    assert markers[0]["message"] == message.strip()


def test_reprojection_only_beads_sidecar_is_clean_after_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "main"
    _create_clean_main_repo(main)
    plans = tmp_path / "plans"
    beads = _create_beads_repo_with_dirty_projection(tmp_path)
    _set_finalizer_env(monkeypatch, main)
    _configure_beads_sidecar(monkeypatch, plans_repo=plans, beads_repo=beads)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = prepare_commit_dirty_state(resolve_finalizer_project_dir(), artifacts)

    assert state.sdd_bead_projection_auto_committed is True
    assert state.dirty_state.is_clean
    assert _run_git(beads, "status", "--short") == ""


def test_commit_finalizer_succeeds_when_reprojection_is_the_only_dirty_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "main"
    _create_clean_main_repo(main)
    plans = tmp_path / "plans"
    beads = _create_beads_repo_with_dirty_projection(tmp_path)
    _set_finalizer_env(monkeypatch, main)
    _configure_beads_sidecar(monkeypatch, plans_repo=plans, beads_repo=beads)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )

    execution = execute_commit_finalizer(
        ConfiguredFinalizerInstance(
            instance_id="commit",
            provider_ref="builtin@commit",
        ),
        FinalizerExecutionContext(
            artifacts_dir=str(artifacts),
            plan_digest="plan",
            run_id="run",
            agent_id="agent-1",
            turn_nonce="nonce",
            selected=("commit",),
        ),
        provider=MagicMock(),
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
    )

    assert execution.invoke_result.content == "done"
    assert execution.result.status == "success"
    assert _run_git(beads, "status", "--short") == ""
