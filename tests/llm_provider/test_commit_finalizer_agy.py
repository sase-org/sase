"""Phase 7 hardening: the Antigravity (`agy`) provider participates in the
shared, provider-neutral commit finalizer exactly like Claude and Codex.

The commit finalizer takes any ``LLMProvider`` and re-invokes it until the
project workspace is clean. These tests drive a *real* :class:`AgyProvider`
instance through :func:`run_commit_finalizer` in a controlled git workspace,
stubbing only the ``agy`` subprocess boundary. They prove there is no
``agy``-specific finalizer branch: the same orchestration that commits Claude's
and Codex's leftover work also commits an Antigravity agent's leftover work.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.agy import AgyProvider
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.commit_finalizer import run_commit_finalizer
from sase.llm_provider.types import InvokeResult
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV


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


def _commit_all(repo: Path, message: str) -> None:
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", message)


def _create_clean_repo(repo: Path) -> None:
    _init_git_repo(repo)
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _commit_all(repo, "initial")


def _set_agent_env(monkeypatch: pytest.MonkeyPatch, project_dir: Path) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260619_230000")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(project_dir))
    monkeypatch.setenv("SASE_AGY_PATH", str(project_dir / "missing-agy"))
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    monkeypatch.delenv(SIBLING_REPOS_JSON_ENV, raising=False)


def _use_git_dirty_details(monkeypatch: pytest.MonkeyPatch) -> None:
    """Detect dirtiness from real git status, like the production resolver."""

    def build(project_dir: str) -> tuple[bool, list[str], str, str]:
        changed_files = finalizer_git.git_changed_files(project_dir)
        if not changed_files:
            return (False, [], "", "")
        details = "Uncommitted changes detected:\n" + "\n".join(changed_files)
        return (True, changed_files, "commit", details)

    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer.build_commit_details",
        build,
    )


def _read_result_json(artifacts_dir: Path) -> dict[str, object]:
    return json.loads(
        (artifacts_dir / "commit_finalizer_result.json").read_text(encoding="utf-8")
    )


def test_agy_provider_finalizes_dirty_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real ``AgyProvider`` flows through the finalizer and converges to clean.

    The repo starts dirty (the agent left uncommitted work). The finalizer
    re-invokes the *real* ``AgyProvider.invoke()`` — only the ``agy`` subprocess
    is stubbed — and that follow-up turn commits the work, just as a live
    Antigravity agent running ``/sase_git_commit`` would. The finalizer then
    sees a clean tree and reports ``finalized``.
    """
    repo = tmp_path / "sase_10"
    _create_clean_repo(repo)
    # Leftover, uncommitted work from the primary agent turn.
    (repo / "feature.py").write_text("print('agy work')\n", encoding="utf-8")
    _set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)

    provider = AgyProvider()
    assert isinstance(provider, LLMProvider)

    seen_prompts: list[str] = []

    def _fake_run_subprocess(
        args: list[str],
        suppress_output: bool,
        *,
        cwd: str,
    ) -> tuple[str, str, int]:
        # The prompt is the value of `agy --print` (final argv element). The
        # follow-up turn "commits" the leftover work like a real agy agent.
        assert cwd == str(repo.resolve())
        seen_prompts.append(args[-1])
        _commit_all(repo, "feat: finalize agy leftover work")
        return ("Committed the outstanding changes.", "", 0)

    monkeypatch.setattr(provider, "_run_subprocess", _fake_run_subprocess)

    artifacts_dir = tmp_path / "artifacts"
    result = run_commit_finalizer(
        provider=provider,
        original_prompt="implement the feature",
        invoke_result=InvokeResult(content="primary agy response"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts_dir),
    )

    # The real AgyProvider.invoke() was driven by the finalizer (one pass).
    assert len(seen_prompts) == 1
    # The wrapped print prompt still contains the shared finalizer prompt.
    assert "implement the feature" in seen_prompts[0]

    # The workspace is clean and the leftover work is committed.
    assert _run_git(repo, "status", "--short") == ""
    assert "feature.py" in _run_git(repo, "show", "--stat", "--oneline", "HEAD")

    # The accumulated content includes both the primary and finalizer responses.
    assert "primary agy response" in result.content
    assert "Committed the outstanding changes." in result.content

    # The shared finalizer recorded a successful, provider-neutral result.
    payload = _read_result_json(artifacts_dir)
    assert payload["status"] == "finalized"
    assert payload["passes"] == 1
    # The follow-up prompt artifact was written by the shared path.
    assert (artifacts_dir / "commit_finalizer_pass_1_prompt.md").is_file()
    assert (artifacts_dir / "commit_finalizer_pass_1_response.md").is_file()


def test_agy_provider_finalizer_clean_workspace_is_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean workspace short-circuits without re-invoking ``agy``.

    This pins that the finalizer's clean-tree fast path is provider-neutral: an
    already-committed Antigravity turn needs no follow-up ``agy`` invocation.
    """
    repo = tmp_path / "sase_10"
    _create_clean_repo(repo)
    _set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)

    provider = AgyProvider()
    invoked = False

    def _fail_if_invoked(
        args: list[str], suppress_output: bool
    ) -> tuple[str, str, int]:
        nonlocal invoked
        invoked = True
        return ("", "", 0)

    monkeypatch.setattr(provider, "_run_subprocess", _fail_if_invoked)

    artifacts_dir = tmp_path / "artifacts"
    result = run_commit_finalizer(
        provider=provider,
        original_prompt="implement the feature",
        invoke_result=InvokeResult(content="primary agy response"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts_dir),
    )

    assert invoked is False
    assert result.content == "primary agy response"
    payload = _read_result_json(artifacts_dir)
    assert payload["status"] == "clean"
    assert payload["passes"] == 0
