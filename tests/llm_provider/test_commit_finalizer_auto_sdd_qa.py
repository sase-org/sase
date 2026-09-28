"""Auto-commit coverage for external SDD prompt Q&A snapshot changes."""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase.finalizers.reconciliation import prepare_commit_dirty_state
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider import commit_finalizer_git_autocommit as finalizer_autocommit
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.sdd.files import set_prompt_qa
from sase.sdd.store import SDD_STORAGE_LOCAL, SddStore
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV

_BASE_PROMPT = """---
plan: 202607/test_plan.md
---

Original prompt.
"""
_QA = """%xprompts_enabled:false
### Questions and Answers

#### Q1: Choice

- [x] **A**

%xprompts_enabled:true"""
_UPDATED_QA = _QA.replace("Q1: Choice", "Q1: Updated choice")


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=repo,
        check=True,
    )


def _commit_all(repo: Path, message: str = "initial") -> None:
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", message)


def _create_prompt_repo(
    tmp_path: Path, head_text: str = _BASE_PROMPT
) -> tuple[Path, Path]:
    repo = tmp_path / "agents"
    _init_git_repo(repo)
    prompt = repo / "prompts" / "202607" / "test_plan.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(head_text, encoding="utf-8")
    _commit_all(repo)
    return repo, prompt


def _set_finalizer_env(monkeypatch: pytest.MonkeyPatch, project_dir: Path) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260713_120000")
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


def _configure_external_store(
    monkeypatch: pytest.MonkeyPatch,
    plans_repo: Path,
) -> SddStore:
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans_repo,
        repo_root=plans_repo,
    )
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)
    return store


def _disable_external_sdd_store(monkeypatch: pytest.MonkeyPatch, main: Path) -> None:
    store = SddStore(storage=SDD_STORAGE_LOCAL, sdd_dir=main, repo_root=main)
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)


def _resolve_agents_prompt_archive_to(
    monkeypatch: pytest.MonkeyPatch,
    agents: Path,
) -> None:
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.resolve_publication_project_key",
        lambda *_args, **_kwargs: "test-project",
    )
    monkeypatch.setattr(
        "sase.agents_sync.targets.resolve_sync_targets",
        lambda *_args, **_kwargs: SimpleNamespace(
            targets=(SimpleNamespace(sidecar_path=agents),)
        ),
    )


def _prepare(artifacts_dir: Path):
    return prepare_commit_dirty_state(
        resolve_finalizer_project_dir(),
        artifacts_dir,
    )


@pytest.mark.parametrize("head_text", [_BASE_PROMPT, _BASE_PROMPT.rstrip("\n")])
def test_qa_only_prover_accepts_append_with_or_without_trailing_newline(
    tmp_path: Path,
    head_text: str,
) -> None:
    repo, prompt = _create_prompt_repo(tmp_path, head_text)
    set_prompt_qa(prompt, _QA)

    assert finalizer_autocommit.has_only_prompt_qa_diff(
        str(repo), "prompts/202607/test_plan.md"
    )


def test_qa_only_prover_accepts_multi_round_replacement(tmp_path: Path) -> None:
    repo, prompt = _create_prompt_repo(tmp_path)
    set_prompt_qa(prompt, _QA)
    _commit_all(repo, "add first Q&A round")
    set_prompt_qa(prompt, _UPDATED_QA)

    assert finalizer_autocommit.has_only_prompt_qa_diff(
        str(repo), "prompts/202607/test_plan.md"
    )


def test_qa_only_prover_rejects_frontmatter_edit(tmp_path: Path) -> None:
    repo, prompt = _create_prompt_repo(tmp_path)
    set_prompt_qa(prompt, _QA)
    prompt.write_text(
        prompt.read_text(encoding="utf-8").replace(
            "plan: 202607/test_plan.md", "plan: 202607/other.md"
        ),
        encoding="utf-8",
    )

    assert not finalizer_autocommit.has_only_prompt_qa_diff(
        str(repo), "prompts/202607/test_plan.md"
    )


def test_external_qa_only_change_is_auto_committed_without_prompting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "main"
    _init_git_repo(main)
    (main / "README.md").write_text("main\n", encoding="utf-8")
    _commit_all(main)
    plans, prompt = _create_prompt_repo(tmp_path)
    set_prompt_qa(prompt, _QA)
    _set_finalizer_env(monkeypatch, main)
    _configure_external_store(monkeypatch, plans)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = _prepare(artifacts)

    assert state.sdd_prompt_qa_auto_committed is True
    assert state.dirty_state.is_clean
    assert _run_git(plans, "status", "--short") == ""
    commit_message = _run_git(plans, "log", "-1", "--pretty=%B")
    assert "Add Q&A to test_plan prompt" in commit_message
    assert "SASE_TYPE=sdd" in commit_message


@pytest.mark.parametrize("unsafe_change", ["mixed", "untracked", "non_prompt"])
def test_unsafe_external_sdd_changes_use_normal_finalizer_prompting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_change: str,
) -> None:
    main = tmp_path / "main"
    _init_git_repo(main)
    (main / "README.md").write_text("main\n", encoding="utf-8")
    _commit_all(main)
    plans, prompt = _create_prompt_repo(tmp_path)

    dirty_path = prompt
    if unsafe_change == "mixed":
        set_prompt_qa(prompt, _QA)
        prompt.write_text(
            prompt.read_text(encoding="utf-8").replace(
                "Original prompt.", "Agent-edited prompt."
            ),
            encoding="utf-8",
        )
    elif unsafe_change == "untracked":
        dirty_path = plans / "prompts" / "202607" / "new_prompt.md"
        dirty_path.write_text(_BASE_PROMPT + "\n" + _QA + "\n", encoding="utf-8")
    else:
        dirty_path = plans / "202607" / "archive" / "test_plan.md"
        dirty_path.parent.mkdir(parents=True)
        dirty_path.write_text(_BASE_PROMPT, encoding="utf-8")
        _commit_all(plans, "add archived prompt")
        set_prompt_qa(dirty_path, _QA)

    _set_finalizer_env(monkeypatch, main)
    _configure_external_store(monkeypatch, plans)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = _prepare(artifacts)

    assert not state.dirty_state.is_clean
    assert state.sdd_prompt_qa_auto_committed is False


def test_qa_only_change_created_during_pass_is_auto_committed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "main"
    _init_git_repo(main)
    (main / "README.md").write_text("main\n", encoding="utf-8")
    _commit_all(main)
    feature = main / "feature.py"
    feature.write_text("VALUE = 1\n", encoding="utf-8")
    plans, prompt = _create_prompt_repo(tmp_path)
    _set_finalizer_env(monkeypatch, main)
    _configure_external_store(monkeypatch, plans)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = _prepare(artifacts)

    assert not state.dirty_state.is_clean
    remaining = [
        path
        for repo_item in state.dirty_state.repos
        for path in repo_item.changed_files
    ]
    assert any("feature.py" in path for path in remaining)


def test_agents_archive_qa_edit_with_foreign_scratch_is_auto_committed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run's Q&A edit is auto-committed even while foreign scratch coexists.

    Regression for the incident where a concurrent agent's half-written
    prompt-archive publication (untracked prompt + README row) left the
    machine-wide agents checkout dirty; that scratch must not block this
    run's own Q&A auto-commit or surface as this run's dirty work.
    """
    main = tmp_path / "main"
    _init_git_repo(main)
    (main / "README.md").write_text("main\n", encoding="utf-8")
    _commit_all(main)
    agents, prompt = _create_prompt_repo(tmp_path)
    readme = agents / "prompts" / "202607" / "README.md"
    readme.write_text("| plan | agent |\n", encoding="utf-8")
    _commit_all(agents, "seed prompt archive readme")
    set_prompt_qa(prompt, _QA)
    readme.write_text("| plan | agent |\n| other | other-agent |\n", encoding="utf-8")
    other_prompt = agents / "prompts" / "202607" / "other_prompt.md"
    other_prompt.write_text(_BASE_PROMPT, encoding="utf-8")
    _set_finalizer_env(monkeypatch, main)
    _disable_external_sdd_store(monkeypatch, main)
    _resolve_agents_prompt_archive_to(monkeypatch, agents)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = _prepare(artifacts)

    assert state.sdd_prompt_qa_auto_committed is True
    assert state.dirty_state.is_clean
    commit_message = _run_git(agents, "log", "-1", "--pretty=%B")
    assert "Add Q&A to test_plan prompt" in commit_message
    remaining_status = _run_git(
        agents, "status", "--porcelain=v1", "--untracked-files=all"
    )
    assert "prompts/202607/README.md" in remaining_status
    assert "prompts/202607/other_prompt.md" in remaining_status


def test_incident_regression_agents_archive_foreign_scratch_is_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign agents-archive scratch alone never fails an unrelated run.

    Direct regression for the ``research.2v.final`` incident: the archive is
    dirty only with another agent's orphaned publication scratch (no Q&A
    edit of this run's own), so the dirty state must come back clean instead
    of prompting ``dirty_after_commit_decisions``.
    """
    main = tmp_path / "main"
    _init_git_repo(main)
    (main / "README.md").write_text("main\n", encoding="utf-8")
    _commit_all(main)
    agents, _prompt = _create_prompt_repo(tmp_path)
    readme = agents / "prompts" / "202607" / "README.md"
    readme.write_text("| plan | agent |\n", encoding="utf-8")
    _commit_all(agents, "seed prompt archive readme")
    readme.write_text("| plan | agent |\n| other | other-agent |\n", encoding="utf-8")
    other_prompt = agents / "prompts" / "202607" / "other_prompt.md"
    other_prompt.write_text(_BASE_PROMPT, encoding="utf-8")
    _set_finalizer_env(monkeypatch, main)
    _disable_external_sdd_store(monkeypatch, main)
    _resolve_agents_prompt_archive_to(monkeypatch, agents)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = _prepare(artifacts)

    assert state.sdd_prompt_qa_auto_committed is False
    assert state.dirty_state.is_clean


def test_prompt_qa_auto_commit_reproves_under_lock_and_rejects_stale_candidate(
    tmp_path: Path,
) -> None:
    """A path that turned non-Q&A between the scan and the lock aborts the commit."""
    repo, prompt = _create_prompt_repo(tmp_path)
    set_prompt_qa(prompt, _QA)
    dirty_state = DirtyState(
        project_dir=str(repo),
        repos=(
            DirtyRepo(
                name="agents prompt archive",
                path=str(repo),
                changed_files=("prompts/202607/test_plan.md",),
                kind="sdd",
            ),
        ),
        details="",
    )

    candidates = finalizer_autocommit.sdd_prompt_qa_auto_commit_candidates(dirty_state)
    assert len(candidates) == 1
    candidate = candidates[0]

    # Simulate a concurrent rewrite between the outside-the-lock scan and the
    # lock-held commit: the content is no longer Q&A-only.
    prompt.write_text(
        prompt.read_text(encoding="utf-8").replace(
            "plan: 202607/test_plan.md", "plan: 202607/other.md"
        ),
        encoding="utf-8",
    )

    committed = finalizer_autocommit.auto_commit_sdd_prompt_qa_candidate(candidate)

    assert committed is False
    remaining_status = _run_git(
        repo, "status", "--porcelain=v1", "--untracked-files=all"
    )
    assert "prompts/202607/test_plan.md" in remaining_status
