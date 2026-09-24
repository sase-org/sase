"""Submit-time live bead status for primary-repository close."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.finalizers.commit_declaration import load_accepted_commit_declaration
from sase.finalizers.declaration import (
    FINAL_CONTEXT_HOST_FILENAME,
    FinalizerDeclarationError,
    final_submission_is_current,
    publish_final_context,
    submit_final_manifest,
)
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState

from .finalizer_declaration_channel_test_helpers import (
    attempt_records,
    prepare_dirty_declaration,
    valid_manifest,
)


def _close_manifest(publication, *, bead_status: str | None = None) -> dict:
    manifest = valid_manifest(publication)
    decision = manifest["payloads"][0]["payload"]["repositories"][0]
    decision["bead_action"] = "close"
    if bead_status is not None:
        decision["bead_status"] = bead_status
    return manifest


def _patch_status(monkeypatch: pytest.MonkeyPatch, value: str, calls: list) -> None:
    def reader(bead_id: str, cwd: str) -> str:
        calls.append((bead_id, cwd))
        return value

    monkeypatch.setattr(
        "sase.finalizers.declaration_manifest._assigned_bead_status", reader
    )


def test_close_accepted_when_live_status_in_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_BEAD_ID", "sase-zq.1")
    publication = publish_final_context()
    repo_id = publication.context.obligations[0].obligation_id
    assert publication.context.assigned_bead is not None
    assert publication.context.assigned_bead.primary_repo_obligation_id == repo_id

    calls: list = []
    _patch_status(monkeypatch, "in_progress", calls)

    submit_final_manifest(_close_manifest(publication))

    assert calls == [("sase-zq.1", str(tmp_path))]


def test_close_accepted_when_live_status_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_BEAD_ID", "sase-17d.1")
    publication = publish_final_context()

    calls: list = []
    _patch_status(monkeypatch, "closed", calls)

    submit_final_manifest(_close_manifest(publication))

    assert calls == [("sase-17d.1", str(tmp_path))]


def test_close_refused_when_live_status_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_BEAD_ID", "sase-zq.1")
    publication = publish_final_context()

    calls: list = []
    _patch_status(monkeypatch, "other", calls)

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(_close_manifest(publication))

    assert exc_info.value.code == "commit_bead_action_invalid"
    assert "close_ineligible_status" in str(exc_info.value)
    assert calls == [("sase-zq.1", str(tmp_path))]
    records = attempt_records(tmp_path)
    assert records[-1]["accepted"] is False


def test_close_refused_when_live_status_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_BEAD_ID", "sase-zq.1")
    publication = publish_final_context()

    calls: list = []
    _patch_status(monkeypatch, "unreadable", calls)

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(_close_manifest(publication))

    assert exc_info.value.code == "commit_bead_action_invalid"
    assert "unreadable_bead_status" in str(exc_info.value)
    assert records_last_refused(tmp_path)


def test_close_refused_when_status_reader_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_BEAD_ID", "sase-zq.1")
    publication = publish_final_context()

    calls: list = []

    def boom(bead_id: str, cwd: str) -> str:
        calls.append((bead_id, cwd))
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "sase.finalizers.declaration_manifest._assigned_bead_status", boom
    )

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(_close_manifest(publication))

    assert exc_info.value.code == "commit_bead_action_invalid"
    assert "unreadable_bead_status" in str(exc_info.value)
    assert calls == [("sase-zq.1", str(tmp_path))]
    assert records_last_refused(tmp_path)


def records_last_refused(root: Path) -> bool:
    records = attempt_records(root)
    return records[-1]["accepted"] is False


def test_host_fact_wins_over_agent_authored_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_BEAD_ID", "sase-zq.1")
    publication = publish_final_context()

    calls: list = []
    _patch_status(monkeypatch, "other", calls)
    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(_close_manifest(publication, bead_status="closed"))
    assert exc_info.value.code == "commit_bead_action_invalid"
    assert "close_ineligible_status" in str(exc_info.value)

    _patch_status(monkeypatch, "unreadable", calls)
    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(_close_manifest(publication, bead_status="closed"))
    assert "unreadable_bead_status" in str(exc_info.value)

    calls.clear()
    _patch_status(monkeypatch, "in_progress", calls)
    submit_final_manifest(_close_manifest(publication, bead_status="unreadable"))
    assert calls == [("sase-zq.1", str(tmp_path))]


def test_keep_never_calls_status_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_BEAD_ID", "sase-zq.1")
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    manifest["payloads"][0]["payload"]["repositories"][0]["bead_action"] = "keep"

    calls: list = []

    def fail_reader(bead_id: str, cwd: str) -> str:
        calls.append((bead_id, cwd))
        raise AssertionError("status helper must not be called for keep")

    monkeypatch.setattr(
        "sase.finalizers.declaration_manifest._assigned_bead_status", fail_reader
    )

    submit_final_manifest(manifest)

    assert calls == []


def test_close_without_assigned_bead_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    manifest["payloads"][0]["payload"]["repositories"][0]["bead_action"] = "close"

    calls: list = []
    _patch_status(monkeypatch, "in_progress", calls)

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_bead_action_invalid"
    assert "close_without_assigned_bead" in str(exc_info.value)
    assert calls == []


def test_close_on_non_primary_refused_without_status_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    linked = tmp_path / "linked"
    linked.mkdir()
    dirty = DirtyState(
        project_dir=str(tmp_path),
        repos=(
            DirtyRepo(
                name="main",
                path=str(tmp_path),
                changed_files=("src/app.py",),
                kind="main",
            ),
            DirtyRepo(
                name="tooling",
                path=str(linked),
                changed_files=("tool.py",),
                kind="sibling",
            ),
        ),
        details="dirty",
    )
    prepare_dirty_declaration(monkeypatch, tmp_path, collect=lambda _root: dirty)
    monkeypatch.setenv("SASE_BEAD_ID", "sase-zq.1")
    publication = publish_final_context()
    assert publication.context.assigned_bead is not None
    primary_id = publication.context.assigned_bead.primary_repo_obligation_id

    manifest = valid_manifest(publication)
    repositories = manifest["payloads"][0]["payload"]["repositories"]
    assert len(repositories) == 2
    for decision in repositories:
        decision["message"] = "fix(final): submit declaration"
        if decision["repo_id"] == primary_id:
            decision["bead_action"] = "keep"
        else:
            decision["bead_action"] = "close"

    calls: list = []

    def fail_reader(bead_id: str, cwd: str) -> str:
        calls.append((bead_id, cwd))
        raise AssertionError("status helper must not be called for linked close")

    monkeypatch.setattr(
        "sase.finalizers.declaration_manifest._assigned_bead_status", fail_reader
    )

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "commit_bead_action_invalid"
    assert "close_requires_primary_repository" in str(exc_info.value)
    assert calls == []


def test_missing_primary_host_record_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_BEAD_ID", "sase-zq.1")
    publication = publish_final_context()
    (tmp_path / FINAL_CONTEXT_HOST_FILENAME).unlink()

    calls: list = []
    _patch_status(monkeypatch, "in_progress", calls)

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(_close_manifest(publication))

    assert exc_info.value.code == "commit_bead_action_invalid"
    assert "unreadable_bead_status" in str(exc_info.value)
    assert calls == []


def test_accepted_close_reloads_with_live_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_BEAD_ID", "sase-zq.1")
    publication = publish_final_context()

    calls: list = []
    _patch_status(monkeypatch, "in_progress", calls)
    submit_final_manifest(_close_manifest(publication))

    assert final_submission_is_current() is True
    _envelope, _context, _host_records, _deferrals = load_accepted_commit_declaration(
        str(tmp_path)
    )

    _patch_status(monkeypatch, "closed", calls)
    assert final_submission_is_current() is True
    load_accepted_commit_declaration(str(tmp_path))

    _patch_status(monkeypatch, "other", calls)
    with pytest.raises(FinalizerDeclarationError) as exc_info:
        load_accepted_commit_declaration(str(tmp_path))
    assert exc_info.value.code == "commit_bead_action_invalid"
    assert "close_ineligible_status" in str(exc_info.value)
