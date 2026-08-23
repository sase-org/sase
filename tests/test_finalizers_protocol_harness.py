"""Skip, noop, and empty-plan coverage for the finalizer protocol."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.agent.pending_handoff import PLAN_PENDING_MARKER
from sase.finalizers.controller import run_finalizers
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.types import InvokeResult
from sase.xprompt.directives import PromptDirectives, extract_prompt_directives

from .finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    patch_dirty,
    prepare_agent_env,
    run_controller,
)


def test_outside_sase_agent_is_a_safe_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
    provider = MagicMock()
    result = run_finalizers(
        provider=provider,
        original_prompt="do work",
        invoke_result=InvokeResult(content="outside"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )
    assert result.content == "outside"
    provider.invoke.assert_not_called()
    assert not (artifacts / "finalizer_result.json").exists()
    assert not (artifacts / "final_context.json").exists()


def test_missing_artifacts_dir_is_a_safe_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="no-artifacts"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=None,
    )
    assert result.content == "no-artifacts"


def test_handoff_skips_generic_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    prepare_agent_env(monkeypatch, artifacts, repo)
    (artifacts / PLAN_PENDING_MARKER).write_text("1\n", encoding="utf-8")
    dirty = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)
    provider = MagicMock()

    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )
    result = run_controller(artifacts, provider)

    assert result.content == "done"
    provider.invoke.assert_not_called()
    assert not (artifacts / "finalizer_result.json").exists()


def test_final_none_writes_empty_success_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": ()}
    patch_dirty(monkeypatch, repo, dirty)
    _, directives = extract_prompt_directives("%final:none\nDo work")

    resolve_and_persist_finalizer_plan(directives, artifacts_dir=str(artifacts))
    result = run_controller(artifacts)

    assert result.content == "done"
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "success"
    assert payload["instances"] == []


def test_clean_commit_only_does_not_recover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": ()}
    patch_dirty(monkeypatch, repo, dirty)
    provider = MagicMock()

    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )
    result = run_controller(artifacts, provider)

    assert result.content == "done"
    provider.invoke.assert_not_called()
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "success"
    assert payload["cycles"] == 1
