"""Coverage for declaration-channel recovery turns."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.finalizers.controller_context import declaration_recovery_spent
from sase.finalizers.declaration import (
    FINAL_DECLARATION_RECOVERY_EVIDENCE_FILENAME,
    FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME,
    SASE_FINAL_TURN_NONCE_ENV,
    FinalContextPublication,
    FinalizerDeclarationError,
    ensure_final_declaration_or_recover,
    publish_final_context,
    submit_final_manifest,
)
from sase.llm_provider.commit_finalizer_baseline import FINALIZER_BASELINE_FILENAME
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult

from .finalizer_declaration_channel_test_helpers import (
    clean_state,
    persist_default_plan,
    prepare_agent_env,
    prepare_dirty_declaration,
    valid_manifest,
)

_INCIDENT_PATHS = (
    "Justfile",
    "src/sase/ace/query_profile/__init__.py",
    "src/sase/ace/query_profile/pane_registry.py",
    "src/sase/ace/query_profile/profiles.py",
    "src/sase/ace/tui/_proc_query.py",
    "tests/ace/tui/test_proc_query.py",
    "tests/test_query_profile.py",
)


def _foreign_work_deferral_manifest(
    publication: FinalContextPublication,
) -> dict[str, object]:
    manifest = deepcopy(publication.payload["manifest_template"])
    payload = manifest["payloads"][0]["payload"]
    repo_id = publication.context.obligations[0].obligation_id
    payload["deferrals"].append(
        {
            "repo_id": repo_id,
            "reason": "foreign_work",
            "paths": list(_INCIDENT_PATHS),
        }
    )
    return manifest


def _incident_dirty_state(repo: Path) -> DirtyState:
    return DirtyState(
        project_dir=str(repo),
        repos=(
            DirtyRepo(
                name="main",
                path=str(repo),
                changed_files=_INCIDENT_PATHS,
                kind="main",
            ),
        ),
        details="dirty",
    )


def test_clean_commit_context_does_not_spend_recovery_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_agent_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: clean_state(tmp_path),
    )
    provider = MagicMock()
    original = InvokeResult(content="done")

    persist_default_plan(tmp_path)
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
    prepare_dirty_declaration(monkeypatch, tmp_path)
    provider = MagicMock()

    def recover(prompt: str, **_kwargs: object) -> InvokeResult:
        assert "single declaration-recovery turn" in prompt
        assert "Declaring a commit is not an edit you perform" in prompt
        assert "/sase_final" in prompt
        assert "src/app.py" in prompt
        assert "A deferral needs a typed reason" in prompt
        assert "`protected_paths`, `foreign_work`, `unsafe_content`" in prompt
        assert os.environ[SASE_FINAL_TURN_NONCE_ENV] != "nonce-1"
        publication = publish_final_context()
        submit_final_manifest(valid_manifest(publication))
        return InvokeResult(content="recovered", usage={"input_tokens": 1})

    provider.invoke.side_effect = recover
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


@pytest.mark.parametrize("include_prompt", [True, False])
def test_recovery_prompt_includes_original_prompt_excerpt_when_supplied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    include_prompt: bool,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    original = "Implement the query profile pane registry"
    captured: dict[str, str] = {}
    provider = MagicMock()

    def recover(prompt: str, **_kwargs: object) -> InvokeResult:
        captured["prompt"] = prompt
        publication = publish_final_context()
        submit_final_manifest(valid_manifest(publication))
        return InvokeResult(content="recovered")

    provider.invoke.side_effect = recover
    ensure_final_declaration_or_recover(
        provider=provider,
        invoke_result=InvokeResult(content="initial"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(tmp_path),
        original_prompt=original if include_prompt else None,
    )

    prompt = captured["prompt"]
    if include_prompt:
        assert "## What this run was asked to do" in prompt
        assert original in prompt
    else:
        assert "## What this run was asked to do" not in prompt
        assert original not in prompt


def test_recovery_writes_evidence_artifact_and_spent_keys_off_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    provider = MagicMock()

    def recover(prompt: str, **_kwargs: object) -> InvokeResult:
        publication = publish_final_context()
        submit_final_manifest(valid_manifest(publication))
        return InvokeResult(content="recovered")

    provider.invoke.side_effect = recover
    ensure_final_declaration_or_recover(
        provider=provider,
        invoke_result=InvokeResult(content="initial"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(tmp_path),
        original_prompt="do the work",
    )

    evidence = tmp_path / FINAL_DECLARATION_RECOVERY_EVIDENCE_FILENAME
    prompt_file = tmp_path / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME
    assert evidence.is_file()
    assert "do the work" in evidence.read_text(encoding="utf-8")
    assert prompt_file.is_file()
    assert declaration_recovery_spent(str(tmp_path)) is True
    evidence.unlink()
    assert declaration_recovery_spent(str(tmp_path)) is True
    prompt_file.unlink()
    assert declaration_recovery_spent(str(tmp_path)) is False


def test_incident_shaped_recovery_prompt_attributes_paths_to_this_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(
        monkeypatch,
        tmp_path,
        collect=lambda _root: _incident_dirty_state(tmp_path),
        fingerprints=dict.fromkeys(_INCIDENT_PATHS, ("M", "abc123")),
    )
    (tmp_path / FINALIZER_BASELINE_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repositories": [
                    {
                        "repo_id": "linked:beads",
                        "path": normalize_path(str(tmp_path / "beads")),
                        "kind": "linked",
                        "name": "beads",
                        "scope": "run_start",
                        "fingerprints": {"issue.jsonl": ["M", "def"]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, str] = {}
    provider = MagicMock()

    def recover(prompt: str, **_kwargs: object) -> InvokeResult:
        captured["prompt"] = prompt
        publication = publish_final_context()
        with pytest.raises(FinalizerDeclarationError) as exc_info:
            submit_final_manifest(_foreign_work_deferral_manifest(publication))
        assert exc_info.value.code == "commit_deferral_rejected"
        submit_final_manifest(valid_manifest(publication))
        return InvokeResult(content="recovered")

    provider.invoke.side_effect = recover
    ensure_final_declaration_or_recover(
        provider=provider,
        invoke_result=InvokeResult(content="implemented the pane registry"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(tmp_path),
        original_prompt="implement the query profile pane",
    )

    prompt = captured["prompt"]
    assert "this run's own work" in prompt
    for path in _INCIDENT_PATHS:
        assert path in prompt
        assert f"- `{path}` — new since run start" in prompt


def test_handoff_skips_declaration_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    (tmp_path / ".sase_plan_pending").write_text("1\n", encoding="utf-8")
    provider = MagicMock()
    original = InvokeResult(content="planning")

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
