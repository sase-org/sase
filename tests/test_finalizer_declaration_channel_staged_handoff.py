"""Declaration context and host carry for validated staged handoffs."""

from __future__ import annotations

from copy import deepcopy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from sase.agent.staged_handoff import (
    STAGED_HANDOFF_FILENAME,
    acquire_staging_reservation,
    write_staged_handoff,
)
from sase.core.finalizer_wire import FinalizerHandoffWire
from sase.finalizers.controller_context import ensure_current_declaration
from sase.finalizers.declaration import (
    FINAL_SUBMISSION_FILENAME,
    FinalizerDeclarationError,
    final_submission_is_current,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.declaration_format import format_context_pretty
from sase.finalizers.declaration_store import build_context_requirements
from sase.finalizers.declaration import load_finalizer_plan
from sase.llm_provider.types import InvokeResult

from .finalizer_declaration_channel_test_helpers import (
    dirty_state,
    prepare_dirty_declaration,
    valid_manifest,
)

_STAGED_ID = "123e4567-e89b-12d3-a456-426614174000"


def _stage(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: Path,
    *,
    kind: str = "questions",
    successor_workspace: str = "inherit",
    carry_allowed: bool = True,
    staged_id: str = _STAGED_ID,
    prepared_intent_ref: str | None = None,
) -> dict[str, Any]:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.delenv("SASE_FINALIZER_OWNED_TURN", raising=False)
    monkeypatch.delenv("SASE_NATIVE_HELPER", raising=False)
    payload: dict[str, Any] = {}
    if kind == "plan":
        payload.update(
            plan_file=str(artifacts / "archived.md"),
            original_file=str(artifacts / "draft.md"),
        )
    if prepared_intent_ref is not None:
        payload["prepared_intent_ref"] = prepared_intent_ref
    record = {
        "schema_version": 1,
        "staged_id": staged_id,
        "kind": kind,
        "created_at": "2026-10-29T12:00:00Z",
        "payload": payload,
        "successor_workspace": successor_workspace,
        "carry_allowed": carry_allowed,
        "dirty_obligations_at_stage": [],
    }
    write_staged_handoff(record, artifacts_dir=str(artifacts), command="test stage")
    return record


def _ensure(
    artifacts: Path,
    *,
    provider: object | None = None,
) -> InvokeResult:
    return ensure_current_declaration(
        provider=provider or object(),
        invoke_result=InvokeResult(content="provider response"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
        options=None,
        original_prompt="test",
    )


def test_inheriting_handoff_publishes_descriptor_and_optional_commit_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _stage(monkeypatch, tmp_path)

    publication = publish_final_context()

    assert publication.context.handoff == FinalizerHandoffWire(
        kind="questions",
        staged_ref=_STAGED_ID,
        successor_workspace="inherit",
        carry_allowed=True,
    )
    assert publication.submission_required is False
    assert publication.context.requirements[0].trigger == "dirty_repository"
    assert publication.context.requirements[0].submission_required is False
    decision = publication.payload["manifest_template"]["payloads"][0]["payload"][
        "repositories"
    ][0]
    assert decision == {
        "repo_id": publication.context.obligations[0].obligation_id,
        "action": "commit",
        "message": "feat(scope): describe the completed work",
    }
    commit_context = publication.payload["commit_declaration"]
    assert commit_context["default_action"] == "commit"
    assert commit_context["allowed_repository_actions"] == ["commit", "carry"]
    assert commit_context["handoff"] == {
        "kind": "questions",
        "staged_ref": _STAGED_ID,
        "successor_workspace": "inherit",
        "carry_allowed": True,
    }
    pretty = format_context_pretty(publication.payload)
    assert "questions (staged ref: " + _STAGED_ID in pretty
    assert "Allowed repository actions: commit, carry" in pretty


def test_missing_declaration_synthesizes_host_carry_for_inheriting_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _stage(monkeypatch, tmp_path)

    result = _ensure(tmp_path)

    assert result.content == "provider response"
    accepted = json.loads(
        (tmp_path / FINAL_SUBMISSION_FILENAME).read_text(encoding="utf-8")
    )
    assert accepted["synthesized"] == {
        "kind": "handoff_carry",
        "source": "host",
        "staged_ref": _STAGED_ID,
    }
    decision = accepted["submission"]["payloads"][0]["payload"]["repositories"][0]
    assert decision == {
        "repo_id": accepted["accepted_context"]["obligations"][0]["obligation_id"],
        "action": "carry",
    }
    assert final_submission_is_current(artifacts_dir=str(tmp_path)) is True


def test_existing_explicit_commit_is_preserved_without_synthesis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _stage(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    submit_final_manifest(manifest)

    _ensure(tmp_path)

    accepted = json.loads(
        (tmp_path / FINAL_SUBMISSION_FILENAME).read_text(encoding="utf-8")
    )
    decision = accepted["submission"]["payloads"][0]["payload"]["repositories"][0]
    assert decision["action"] == "commit"
    assert "synthesized" not in accepted


def test_stale_explicit_submission_enters_recovery_instead_of_synthesizing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    record = _stage(monkeypatch, tmp_path)
    publication = publish_final_context()
    submit_final_manifest(valid_manifest(publication))
    recovery_calls: list[bool] = []

    record["staged_id"] = "323e4567-e89b-12d3-a456-426614174000"
    (tmp_path / STAGED_HANDOFF_FILENAME).write_text(
        json.dumps(record),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.finalizers.controller_context.ensure_final_declaration_or_recover",
        lambda **_kwargs: (
            recovery_calls.append(True) or InvokeResult(content="recovered")
        ),
    )

    result = _ensure(tmp_path)

    accepted = json.loads(
        (tmp_path / FINAL_SUBMISSION_FILENAME).read_text(encoding="utf-8")
    )
    assert result.content == "recovered"
    assert recovery_calls == [True]
    assert (
        accepted["submission"]["payloads"][0]["payload"]["repositories"][0]["action"]
        == "commit"
    )
    assert "synthesized" not in accepted


def test_staged_identity_change_rejects_old_carry_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    record = _stage(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = deepcopy(publication.payload["manifest_template"])
    decision = manifest["payloads"][0]["payload"]["repositories"][0]
    decision["action"] = "carry"
    decision.pop("message")

    record["staged_id"] = "223e4567-e89b-12d3-a456-426614174000"
    (tmp_path / STAGED_HANDOFF_FILENAME).write_text(
        json.dumps(record),
        encoding="utf-8",
    )
    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "stale_final_context"
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()


@pytest.mark.parametrize(
    ("kind", "successor_workspace", "carry_allowed", "prepared_intent_ref"),
    [
        ("plan", "none", False, None),
        ("gate", "none", False, None),
        ("monitor", "inherit", False, "intent-123"),
    ],
)
def test_commit_only_handoffs_keep_dirty_submission_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    successor_workspace: str,
    carry_allowed: bool,
    prepared_intent_ref: str | None,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _stage(
        monkeypatch,
        tmp_path,
        kind=kind,
        successor_workspace=successor_workspace,
        carry_allowed=carry_allowed,
        prepared_intent_ref=prepared_intent_ref,
    )

    publication = publish_final_context()

    assert publication.submission_required is True
    assert publication.context.requirements[0].submission_required is True
    assert publication.payload["manifest_template"]["payloads"]
    assert publication.payload["commit_declaration"]["allowed_repository_actions"] == [
        "commit"
    ]


@pytest.mark.parametrize(
    ("kind", "successor_workspace", "carry_allowed"),
    [("plan", "none", False), ("gate", "none", False)],
)
def test_commit_only_handoff_uses_one_shot_declaration_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    successor_workspace: str,
    carry_allowed: bool,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _stage(
        monkeypatch,
        tmp_path,
        kind=kind,
        successor_workspace=successor_workspace,
        carry_allowed=carry_allowed,
    )
    recovery_calls: list[bool] = []
    monkeypatch.setattr(
        "sase.finalizers.controller_context.ensure_final_declaration_or_recover",
        lambda **_kwargs: (
            recovery_calls.append(True) or InvokeResult(content="recovered")
        ),
    )

    result = _ensure(tmp_path)

    assert result.content == "recovered"
    assert recovery_calls == [True]
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()


def test_prepared_handoff_intent_is_rendered_but_not_used_as_carry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _stage(
        monkeypatch,
        tmp_path,
        kind="monitor",
        successor_workspace="inherit",
        carry_allowed=False,
        prepared_intent_ref="intent-123",
    )

    publication = publish_final_context()

    assert publication.payload["context"]["handoff"]["prepared_intent_ref"] == (
        "intent-123"
    )
    assert "Prepared intent: intent-123" in format_context_pretty(publication.payload)
    assert publication.submission_required is True


def test_stage_reservation_does_not_publish_a_handoff_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    acquire_staging_reservation(artifacts_dir=str(tmp_path), command="test stage")

    publication = publish_final_context()

    assert publication.context.handoff is None
    assert publication.submission_required is True


def test_staged_handoff_read_failure_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    (tmp_path / STAGED_HANDOFF_FILENAME).write_text("{", encoding="utf-8")

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        publish_final_context()

    assert exc_info.value.code == "invalid_staged_handoff"


def test_external_provider_remains_required_when_repository_carry_is_legal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    plan = load_finalizer_plan(tmp_path)
    external_entry = replace(
        plan.entries[0],
        instance_id="external-required",
        provider_ref="test-provider@required",
        resolved_index=1,
    )
    plan = replace(plan, entries=[*plan.entries, external_entry])
    handoff = FinalizerHandoffWire(
        kind="questions",
        staged_ref=_STAGED_ID,
        successor_workspace="inherit",
        carry_allowed=True,
    )

    requirements, _obligations = build_context_requirements(
        plan,
        dirty_state(tmp_path),
        handoff=handoff,
    )

    assert requirements[0].submission_required is False
    assert requirements[1].submission_required is True
