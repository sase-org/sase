"""Coverage for the beta finalizer declaration channel."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.feature_flags import override_flags
from sase.finalizers.declaration import (
    FINAL_CONTEXT_FILENAME,
    FINAL_SUBMISSION_ATTEMPTS_FILENAME,
    FINAL_SUBMISSION_FILENAME,
    SASE_FINAL_TURN_NONCE_ENV,
    FinalContextPublication,
    FinalizerDeclarationError,
    ensure_final_declaration_or_recover,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult
from sase.main.parser import create_parser
from sase.xprompt.directives import PromptDirectives


def _prepare_agent_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv(SASE_FINAL_TURN_NONCE_ENV, "nonce-1")


def _dirty_state(repo: Path) -> DirtyState:
    return DirtyState(
        project_dir=str(repo),
        repos=(
            DirtyRepo(
                name="main",
                path=str(repo),
                changed_files=("src/app.py",),
                kind="main",
            ),
        ),
        details="dirty",
    )


def _clean_state(repo: Path) -> DirtyState:
    return DirtyState(project_dir=str(repo), repos=(), details="")


def _persist_default_plan(tmp_path: Path) -> None:
    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(tmp_path),
    )


def _valid_manifest(publication: FinalContextPublication) -> dict[str, object]:
    manifest = deepcopy(publication.payload["manifest_template"])
    repositories = manifest["payloads"][0]["payload"]["repositories"]
    repositories[0]["message"] = "fix(final): submit declaration"
    return manifest


def test_final_parser_registers_context_and_submit() -> None:
    parser = create_parser(only="final")

    context_args = parser.parse_args(["final", "context", "-f", "json"])
    submit_args = parser.parse_args(["final", "submit", "-"])

    assert context_args.command == "final"
    assert context_args.final_subcommand == "context"
    assert context_args.format == "json"
    assert submit_args.final_subcommand == "submit"
    assert submit_args.manifest == "-"


def test_context_publishes_opaque_dirty_repository_obligation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )

    with override_flags(pluggable_finalizers=True):
        _persist_default_plan(tmp_path)
        publication = publish_final_context()

    context = publication.payload["context"]
    obligations = context["obligations"]
    assert publication.payload["submission_required"] is True
    assert context["run_id"] == "run-1"
    assert context["agent_id"] == "agent-1"
    assert context["turn_nonce"] == "nonce-1"
    assert context["requirements"][0]["trigger"] == "dirty_repository"
    assert context["requirements"][0]["submission_required"] is True
    assert obligations[0]["obligation_id"].startswith("repo-")
    assert obligations[0]["kind"] == "repository"
    assert obligations[0]["paths"] == ["src/app.py"]
    assert str(tmp_path) not in json.dumps(publication.payload)
    assert (tmp_path / FINAL_CONTEXT_FILENAME).is_file()


def test_submit_accepts_manifest_and_retains_invalid_attempt_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )

    with override_flags(pluggable_finalizers=True):
        _persist_default_plan(tmp_path)
        publication = publish_final_context()
        manifest = _valid_manifest(publication)
        accepted = submit_final_manifest(manifest)

        stale = deepcopy(manifest)
        stale["context_digest"] = "0" * 64
        with pytest.raises(FinalizerDeclarationError, match="context"):
            submit_final_manifest(stale)

    assert accepted["validation"]["accepted_instances"] == ["commit"]
    assert (tmp_path / FINAL_SUBMISSION_FILENAME).is_file()
    attempts = [
        json.loads(line)
        for line in (tmp_path / FINAL_SUBMISSION_ATTEMPTS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert attempts[-2]["accepted"] is True
    assert attempts[-1]["accepted"] is False
    assert attempts[-1]["content_digest"]


def test_clean_commit_context_does_not_spend_recovery_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _clean_state(tmp_path),
    )
    provider = MagicMock()
    original = InvokeResult(content="done")

    with override_flags(pluggable_finalizers=True):
        _persist_default_plan(tmp_path)
        result = ensure_final_declaration_or_recover(
            provider=provider,
            invoke_result=original,
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(tmp_path),
        )

    assert result is original
    provider.invoke.assert_not_called()


def test_missing_required_declaration_gets_one_fresh_recovery_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )

    provider = MagicMock()

    def recover(prompt: str, **_kwargs: object) -> InvokeResult:
        assert "single declaration-recovery turn" in prompt
        assert os.environ[SASE_FINAL_TURN_NONCE_ENV] != "nonce-1"
        publication = publish_final_context()
        submit_final_manifest(_valid_manifest(publication))
        return InvokeResult(content="recovered", usage={"input_tokens": 1})

    provider.invoke.side_effect = recover

    with override_flags(pluggable_finalizers=True):
        _persist_default_plan(tmp_path)
        result = ensure_final_declaration_or_recover(
            provider=provider,
            invoke_result=InvokeResult(content="initial", usage={"input_tokens": 2}),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(tmp_path),
        )

    assert provider.invoke.call_count == 1
    assert "initial" in result.content
    assert "recovered" in result.content
    assert result.usage == {"input_tokens": 3}
    assert os.environ[SASE_FINAL_TURN_NONCE_ENV] == "nonce-1"


def test_submit_rejects_stale_nonce_and_plan_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )

    with override_flags(pluggable_finalizers=True):
        _persist_default_plan(tmp_path)
        publication = publish_final_context()
        stale_nonce = deepcopy(_valid_manifest(publication))
        stale_nonce["turn_nonce"] = "other-nonce"
        with pytest.raises(FinalizerDeclarationError):
            submit_final_manifest(stale_nonce)

        stale_plan = deepcopy(_valid_manifest(publication))
        stale_plan["plan_digest"] = "0" * 64
        with pytest.raises(FinalizerDeclarationError):
            submit_final_manifest(stale_plan)


def test_handoff_skips_declaration_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(tmp_path),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "abc123")},
    )
    (tmp_path / ".sase_plan_pending").write_text("1\n", encoding="utf-8")
    provider = MagicMock()
    original = InvokeResult(content="planning")

    with override_flags(pluggable_finalizers=True):
        _persist_default_plan(tmp_path)
        result = ensure_final_declaration_or_recover(
            provider=provider,
            invoke_result=original,
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(tmp_path),
        )

    assert result is original
    provider.invoke.assert_not_called()
