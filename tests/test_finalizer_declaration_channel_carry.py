"""Declaration-channel coverage for explicit carry repository decisions."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.finalizers.declaration import (
    FINAL_SUBMISSION_FILENAME,
    FinalizerDeclarationError,
    publish_final_context,
    submit_final_manifest,
)

from .finalizer_declaration_channel_test_helpers import (
    add_deferral,
    prepare_dirty_declaration,
    valid_manifest,
)
from .finalizers_carry_test_helpers import attach_inheriting_handoff


def test_submit_rejects_carry_without_inheriting_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    decision = manifest["payloads"][0]["payload"]["repositories"][0]
    decision["action"] = "carry"
    decision.pop("message", None)
    decision.pop("bead_action", None)

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_action_invalid"
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()


def test_submit_rejects_carry_commit_only_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    attach_inheriting_handoff(monkeypatch)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    decision = manifest["payloads"][0]["payload"]["repositories"][0]
    decision["action"] = "carry"
    decision["message"] = "fix(final): should not accompany carry"
    decision.pop("bead_action", None)

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_decision_unknown_key"
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()


def test_submit_rejects_carry_and_deferral_on_the_same_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    attach_inheriting_handoff(monkeypatch)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    repo_id = publication.context.obligations[0].obligation_id
    decision = manifest["payloads"][0]["payload"]["repositories"][0]
    decision["action"] = "carry"
    decision.pop("message", None)
    decision.pop("bead_action", None)
    add_deferral(manifest, repo_id, reason="unsafe_content")

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_carry_deferral_conflict"
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()


def test_submit_accepts_explicit_carry_with_inheriting_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    attach_inheriting_handoff(monkeypatch)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    decision = manifest["payloads"][0]["payload"]["repositories"][0]
    decision["action"] = "carry"
    decision.pop("message", None)
    decision.pop("bead_action", None)

    accepted = submit_final_manifest(manifest)

    assert (tmp_path / FINAL_SUBMISSION_FILENAME).is_file()
    assert (
        accepted["submission"]["payloads"][0]["payload"]["repositories"][0]["action"]
        == "carry"
    )
