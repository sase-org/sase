"""Coverage for finalizer declaration-channel deferral handling."""

from __future__ import annotations

import json
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
    write_run_start_baseline,
)


@pytest.mark.parametrize(
    "legacy_reason",
    [
        "no commit was requested for this turn",
        "The user did not ask to commit",
        "I lack context to authorize a commit",
        "Declaration-recovery turn: do not mutate repositories",
        "not mine",
    ],
)
def test_submit_rejects_legacy_refuse_action_as_unrepresentable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    legacy_reason: str,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    decision = manifest["payloads"][0]["payload"]["repositories"][0]
    decision["action"] = "refuse"
    decision.pop("message")
    decision["reason"] = legacy_reason

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_action_invalid"
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()


def test_submit_rejects_unknown_typed_deferral_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        reason="not_asked_to_commit",
    )

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_deferral_reason_invalid"
    assert "not_asked_to_commit" in str(exc_info.value)


@pytest.mark.parametrize("reason", ["foreign_work", "belongs_to_another_turn"])
def test_submit_rejects_run_owned_deferral_from_baseline_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    write_run_start_baseline(tmp_path, tmp_path, fingerprints={})
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    add_deferral(
        manifest, publication.context.obligations[0].obligation_id, reason=reason
    )

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_deferral_rejected"
    message = str(exc_info.value)
    assert "src/app.py" in message
    assert "new or changed after this run began" in message
    assert "commit message" in message


def test_submit_rejects_run_owned_deferral_from_direct_write_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    (tmp_path / "tool_calls.jsonl").write_text(
        json.dumps(
            {
                "event": "ToolUse",
                "tool_name": "Edit",
                "tool_input_summary": {"file_path": "src/app.py"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        reason="belongs_to_another_turn",
    )

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_deferral_rejected"
    assert "write/edit tool calls" in str(exc_info.value)


def test_submit_upholds_foreign_work_when_baseline_proves_pre_existing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    write_run_start_baseline(
        tmp_path,
        tmp_path,
        fingerprints={"src/app.py": ("M", "content")},
    )
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_git_status.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "content")},
    )
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        reason="foreign_work",
    )

    accepted = submit_final_manifest(manifest)

    assert accepted["accepted_deferrals"] == [
        {
            "instance_id": "commit",
            "repo_id": publication.context.obligations[0].obligation_id,
            "repo_display_name": "main",
            "reason": "foreign_work",
            "paths": ["src/app.py"],
        }
    ]


def test_submit_upholds_protected_path_deferral(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.finalizers.declaration_deferrals.protected_baseline_paths",
        lambda _root, _repo_path, *, get_changed_files: ("src/app.py",),
    )
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        reason="protected_paths",
    )

    accepted = submit_final_manifest(manifest)

    assert accepted["accepted_deferrals"][0]["reason"] == "protected_paths"


def test_submit_upholds_unsafe_content_deferral(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        reason="unsafe_content",
    )

    accepted = submit_final_manifest(manifest)

    assert accepted["accepted_deferrals"][0]["reason"] == "unsafe_content"


def test_submit_rejects_deferral_paths_outside_obligation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    add_deferral(
        manifest,
        publication.context.obligations[0].obligation_id,
        paths=["other.py"],
    )

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_deferral_path_unknown"
    assert "other.py" in str(exc_info.value)
