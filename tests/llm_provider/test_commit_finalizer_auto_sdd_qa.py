"""Auto-commit coverage for external SDD prompt Q&A snapshot changes."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest.mock import MagicMock

import pytest

from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer import run_commit_finalizer
from sase.llm_provider.types import InvokeResult
from sase.sdd.files import set_prompt_qa
from sase.sdd.store import SddStore
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
    repo = tmp_path / "plans"
    _init_git_repo(repo)
    prompt = repo / "202607" / "prompts" / "test_plan.md"
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
        "sase.llm_provider.commit_finalizer.build_commit_details",
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
        storage="companion_repos",
        sdd_dir=plans_repo,
        repo_root=plans_repo,
    )
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)
    return store


def _run_finalizer(provider: MagicMock, artifacts_dir: Path) -> InvokeResult:
    return run_commit_finalizer(
        provider=provider,
        original_prompt="primary prompt",
        invoke_result=InvokeResult(content="primary response"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts_dir),
    )


@pytest.mark.parametrize("head_text", [_BASE_PROMPT, _BASE_PROMPT.rstrip("\n")])
def test_qa_only_prover_accepts_append_with_or_without_trailing_newline(
    tmp_path: Path,
    head_text: str,
) -> None:
    repo, prompt = _create_prompt_repo(tmp_path, head_text)
    set_prompt_qa(prompt, _QA)

    assert finalizer_git._has_only_sdd_prompt_qa_diff(
        str(repo), "202607/prompts/test_plan.md"
    )


def test_qa_only_prover_accepts_multi_round_replacement(tmp_path: Path) -> None:
    repo, prompt = _create_prompt_repo(tmp_path)
    set_prompt_qa(prompt, _QA)
    _commit_all(repo, "add first Q&A round")
    set_prompt_qa(prompt, _UPDATED_QA)

    assert finalizer_git._has_only_sdd_prompt_qa_diff(
        str(repo), "202607/prompts/test_plan.md"
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

    assert not finalizer_git._has_only_sdd_prompt_qa_diff(
        str(repo), "202607/prompts/test_plan.md"
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
    provider = MagicMock()
    artifacts = tmp_path / "artifacts"

    result = _run_finalizer(provider, artifacts)

    provider.invoke.assert_not_called()
    assert result.content == "primary response"
    assert _run_git(plans, "status", "--short") == ""
    commit_message = _run_git(plans, "log", "-1", "--pretty=%B")
    assert "Add Q&A to test_plan prompt" in commit_message
    assert "SASE_TYPE=sdd" in commit_message
    result_data = json.loads(
        (artifacts / "commit_finalizer_result.json").read_text(encoding="utf-8")
    )
    assert result_data["status"] == "finalized"
    assert result_data["reason"] == "auto_committed_sdd_prompt_qa"


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
        dirty_path = plans / "202607" / "prompts" / "new_prompt.md"
        dirty_path.write_text(_BASE_PROMPT + "\n" + _QA + "\n", encoding="utf-8")
    else:
        dirty_path = plans / "202607" / "archive" / "test_plan.md"
        dirty_path.parent.mkdir(parents=True)
        dirty_path.write_text(_BASE_PROMPT, encoding="utf-8")
        _commit_all(plans, "add archived prompt")
        set_prompt_qa(dirty_path, _QA)

    _set_finalizer_env(monkeypatch, main)
    _configure_external_store(monkeypatch, plans)
    provider = MagicMock()

    def invoke(*_args: object, **_kwargs: object) -> InvokeResult:
        if unsafe_change == "untracked":
            dirty_path.unlink()
        else:
            dirty_path.write_text(_BASE_PROMPT, encoding="utf-8")
        return InvokeResult(content="provider finalized")

    provider.invoke.side_effect = invoke

    result = _run_finalizer(provider, tmp_path / "artifacts")

    assert provider.invoke.call_count == 1
    assert result.content == "primary response\n\nprovider finalized"
    assert _run_git(plans, "status", "--short") == ""
    expected_commits = "2" if unsafe_change == "non_prompt" else "1"
    assert _run_git(plans, "rev-list", "--count", "HEAD").strip() == expected_commits


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
    provider = MagicMock()

    def invoke(*_args: object, **_kwargs: object) -> InvokeResult:
        _commit_all(main, "add feature")
        set_prompt_qa(prompt, _QA)
        return InvokeResult(content="provider finalized")

    provider.invoke.side_effect = invoke

    result = _run_finalizer(provider, tmp_path / "artifacts")

    assert provider.invoke.call_count == 1
    assert result.content == "primary response\n\nprovider finalized"
    assert _run_git(main, "status", "--short") == ""
    assert _run_git(plans, "status", "--short") == ""
    assert "Add Q&A to test_plan prompt" in _run_git(plans, "log", "-1", "--pretty=%B")
