"""Grace window for unresolved deferred prompt archives."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agents_sync.git import run_git
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.prompt_archive.deferred import (
    DEFERRED_PROMPT_GRACE_SECONDS,
    UNRESOLVED_PROMPT_ARCHIVE_REASON,
    DeferredPromptRestoreFailure,
    _deferred_prompt_restore_is_pending,
    restore_deferred_prompt_archives,
)
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.agent_publication_recovery import (
    PROMPT_STATUS_FAILED,
    PROMPT_STATUS_UNAVAILABLE,
)
from tests.agents_sync.commit_publication_fixtures import setup_target
from tests.agents_sync.test_deferred_prompt_archive._helpers import OWNER

_NOW = 2_000_000_000.0
_REVISION = "c" * 40


def _unavailable_request(
    artifacts_dir: Path, *, created_at: float
) -> AgentPublicationOutboxItem:
    return AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent="foo.land",
        global_agent="alice.athena.foo.land",
        primary_revision=_REVISION,
        local_hood="foo.land",
        artifacts_dir=str(artifacts_dir),
        created_at=created_at,
    )


def _restore(
    tmp_path: Path,
    request: AgentPublicationOutboxItem,
    *,
    now: float = _NOW,
) -> dict[tuple[str, str], DeferredPromptRestoreFailure]:
    target, _remote = setup_target(tmp_path)
    return restore_deferred_prompt_archives(
        target,
        (request,),
        run_git,
        identity=AgentIdentitySnapshot(OWNER),
        inventory=ProjectHoodInventory(OWNER, "proj", ()),
        now=now,
    )


def test_pending_predicate_young_unavailable() -> None:
    assert (
        _deferred_prompt_restore_is_pending(
            status=PROMPT_STATUS_UNAVAILABLE,
            reason=UNRESOLVED_PROMPT_ARCHIVE_REASON,
            restore_error=None,
            created_at=_NOW - 60,
            now=_NOW,
        )
        is True
    )


def test_pending_predicate_past_grace() -> None:
    assert (
        _deferred_prompt_restore_is_pending(
            status=PROMPT_STATUS_UNAVAILABLE,
            reason=UNRESOLVED_PROMPT_ARCHIVE_REASON,
            restore_error=None,
            created_at=_NOW - DEFERRED_PROMPT_GRACE_SECONDS,
            now=_NOW,
        )
        is False
    )


def test_pending_predicate_legacy_created_at_is_past_grace() -> None:
    assert (
        _deferred_prompt_restore_is_pending(
            status=PROMPT_STATUS_UNAVAILABLE,
            reason=UNRESOLVED_PROMPT_ARCHIVE_REASON,
            restore_error=None,
            created_at=0.0,
            now=_NOW,
        )
        is False
    )


def test_pending_predicate_restore_error_is_never_pending() -> None:
    assert (
        _deferred_prompt_restore_is_pending(
            status=PROMPT_STATUS_UNAVAILABLE,
            reason=UNRESOLVED_PROMPT_ARCHIVE_REASON,
            restore_error="could not restore deferred prompt archive",
            created_at=_NOW - 60,
            now=_NOW,
        )
        is False
    )


def test_pending_predicate_rejects_non_unavailable_status() -> None:
    assert (
        _deferred_prompt_restore_is_pending(
            status=PROMPT_STATUS_FAILED,
            reason=UNRESOLVED_PROMPT_ARCHIVE_REASON,
            restore_error=None,
            created_at=_NOW - 60,
            now=_NOW,
        )
        is False
    )


def test_pending_predicate_rejects_other_reasons() -> None:
    assert (
        _deferred_prompt_restore_is_pending(
            status=PROMPT_STATUS_UNAVAILABLE,
            reason="prompt archive restore failed: disk full",
            restore_error=None,
            created_at=_NOW - 60,
            now=_NOW,
        )
        is False
    )


def test_restore_marks_young_unavailable_request_pending(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "runs/missing"
    artifacts_dir.mkdir(parents=True)
    request = _unavailable_request(artifacts_dir, created_at=_NOW - 60)

    failures = _restore(tmp_path, request)

    failure = failures[request.logical_key]
    assert failure.pending is True
    assert UNRESOLVED_PROMPT_ARCHIVE_REASON in failure.message


def test_restore_escalates_old_unavailable_request(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "runs/missing"
    artifacts_dir.mkdir(parents=True)
    request = _unavailable_request(
        artifacts_dir, created_at=_NOW - DEFERRED_PROMPT_GRACE_SECONDS
    )

    failures = _restore(tmp_path, request)

    failure = failures[request.logical_key]
    assert failure.pending is False
    assert UNRESOLVED_PROMPT_ARCHIVE_REASON in failure.message


def test_restore_escalates_legacy_created_at(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "runs/missing"
    artifacts_dir.mkdir(parents=True)
    request = _unavailable_request(artifacts_dir, created_at=0.0)

    failures = _restore(tmp_path, request)

    assert failures[request.logical_key].pending is False


def test_restore_error_is_not_pending_even_when_young(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir = tmp_path / "runs/missing"
    artifacts_dir.mkdir(parents=True)
    request = _unavailable_request(artifacts_dir, created_at=_NOW - 60)

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("prompt pool is unreadable")

    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.deferred.prepare_deferred_prompt_archive",
        explode,
    )

    failures = _restore(tmp_path, request)

    failure = failures[request.logical_key]
    assert failure.pending is False
    assert "prompt pool is unreadable" in failure.message
