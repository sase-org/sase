"""Audited terminal state for unrecoverable deferred prompt archives."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync._commit_publication_outbox import retired_count
from sase.agents_sync.git import run_git
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.deferred import (
    DeferredPromptRestoreFailure,
    restore_deferred_prompt_archives,
)
from sase.agents_sync.prompt_archive.terminal import (
    TERMINAL_PROMPT_ARCHIVE_REASON_PREFIX,
    is_terminal_prompt_archive_reason,
    record_terminal_prompt_transition,
    terminal_obligations_path,
)
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
    list_agent_publications,
    revive_agent_publications,
    update_agent_publications,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.prompt_artifact_staging_pool import prune_prompt_artifact_pool
from tests.agents_sync.commit_publication_fixtures import setup_target
from tests.agents_sync.test_deferred_prompt_archive._helpers import OWNER

_NOW = 2_000_000_000.0
_REVISION = "c" * 40
_POOL_REVISION = "a" * 40
_MAX_ATTEMPTS = 3


def _request(
    artifacts_dir: Path,
    *,
    created_at: float = 0.0,
    attempts: int = 0,
    quarantined: bool = False,
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
        attempts=attempts,
        quarantined=quarantined,
    )


def _restore(
    tmp_path: Path,
    request: AgentPublicationOutboxItem,
    *,
    now: float = _NOW,
    runs: tuple[object, ...] = (),
) -> dict[tuple[str, str], DeferredPromptRestoreFailure]:
    target, _remote = setup_target(tmp_path)
    return _restore_with_target(target, request, now=now, runs=runs)


def _restore_with_target(
    target: ProjectTarget,
    request: AgentPublicationOutboxItem,
    *,
    now: float = _NOW,
    runs: tuple[object, ...] = (),
) -> dict[tuple[str, str], DeferredPromptRestoreFailure]:
    return restore_deferred_prompt_archives(
        target,
        (request,),
        run_git,
        identity=AgentIdentitySnapshot(OWNER),
        inventory=ProjectHoodInventory(OWNER, "proj", runs),
        now=now,
    )


def _missing_dir(tmp_path: Path, name: str = "missing") -> Path:
    artifacts_dir = tmp_path / f"runs/{name}"
    artifacts_dir.mkdir(parents=True)
    return artifacts_dir


def test_young_exhausted_row_stays_pending_not_terminal(tmp_path: Path) -> None:
    """A young row is never terminal, even with its attempts spent."""

    request = _request(
        _missing_dir(tmp_path), created_at=_NOW - 60, attempts=_MAX_ATTEMPTS
    )

    failures = _restore(tmp_path, request)

    failure = failures[request.logical_key]
    assert failure.pending is True
    assert failure.terminal is False


def test_old_missing_source_at_final_attempt_is_terminal(tmp_path: Path) -> None:
    """Past grace with no source anywhere and the budget spent goes terminal."""

    request = _request(
        _missing_dir(tmp_path), created_at=0.0, attempts=_MAX_ATTEMPTS - 1
    )

    failures = _restore(tmp_path, request)

    failure = failures[request.logical_key]
    assert failure.pending is False
    assert failure.terminal is True
    assert TERMINAL_PROMPT_ARCHIVE_REASON_PREFIX in failure.message


def test_terminal_message_is_deterministic_across_passes(tmp_path: Path) -> None:
    """The retiring update matches on the recorded error, so it must be stable."""

    artifacts_dir = _missing_dir(tmp_path)
    target, _remote = setup_target(tmp_path)
    first = _restore_with_target(
        target,
        _request(artifacts_dir, created_at=0.0, attempts=_MAX_ATTEMPTS - 1),
    )
    second = _restore_with_target(
        target,
        _request(
            artifacts_dir,
            created_at=0.0,
            attempts=_MAX_ATTEMPTS + 5,
        ),
    )

    [first_key] = list(first)
    [second_key] = list(second)
    assert first_key == second_key
    assert first[first_key].message == second[second_key].message
    assert first[first_key].terminal is True
    assert second[second_key].terminal is True


def test_quarantined_missing_source_is_terminal(tmp_path: Path) -> None:
    """An already-quarantined row with no source anywhere goes terminal."""

    request = _request(
        _missing_dir(tmp_path), created_at=0.0, attempts=99, quarantined=True
    )

    failures = _restore(tmp_path, request)

    failure = failures[request.logical_key]
    assert failure.pending is False
    assert failure.terminal is True
    marker = TERMINAL_PROMPT_ARCHIVE_REASON_PREFIX + ":"
    assert marker in failure.message
    assert is_terminal_prompt_archive_reason(
        failure.message[failure.message.find(marker) :]
    )


def test_stale_artifacts_dir_with_live_run_source_restores(tmp_path: Path) -> None:
    """The row naming the wrong artifacts dir keeps its bytes via the run source."""

    stale_dir = _missing_dir(tmp_path, "stale")
    live_dir = _missing_dir(tmp_path, "live")
    (live_dir / "raw_prompt.md").write_text("Live prompt.\n", encoding="utf-8")
    request = _request(stale_dir, created_at=0.0, attempts=99, quarantined=True)
    run = SimpleNamespace(
        local_name="foo.land",
        global_name="alice.athena.foo.land",
        commits=(SimpleNamespace(sha=_REVISION),),
        source_label=str(live_dir),
    )

    failures = _restore(tmp_path, request, runs=(run,))

    assert failures == {}


def test_source_reappears_before_terminal_decision_restores(
    tmp_path: Path,
) -> None:
    """Bytes back in the artifacts dir restore normally instead of retiring."""

    artifacts_dir = _missing_dir(tmp_path, "returned")
    (artifacts_dir / "raw_prompt.md").write_text("Returned prompt.\n", encoding="utf-8")
    request = _request(artifacts_dir, created_at=0.0, attempts=_MAX_ATTEMPTS - 1)

    failures = _restore(tmp_path, request)

    assert failures == {}


def _terminal_error() -> str:
    return (
        "could not restore deferred prompt archive for "
        f"alice.athena.worker@{_POOL_REVISION[:12]}: "
        f"{TERMINAL_PROMPT_ARCHIVE_REASON_PREFIX}: unit under test"
    )


def test_terminal_transition_retires_audits_and_skips_revive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two terminal passes retire the row, audit once, and skip --retry-quarantined."""

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent="worker",
            global_agent="alice.athena.worker",
            primary_revision=_POOL_REVISION,
            local_hood="worker",
        )
    )
    [enqueued] = list_agent_publications("proj")
    error = _terminal_error()
    item = enqueued
    for _ in range(2):
        [item] = update_agent_publications(
            "proj",
            (item.logical_key,),
            error=error,
            increment_attempts=True,
            quarantine_threshold=None,
            terminal_reason=error,
        )
    assert item.terminal is True
    assert item.quarantined is False
    assert is_terminal_prompt_archive_reason(item.terminal_reason)

    before = replace(enqueued, terminal=False, terminal_reason=None)
    assert (
        record_terminal_prompt_transition(project_key="proj", before=before, after=item)
        is True
    )
    records = terminal_obligations_path().read_text(encoding="utf-8").splitlines()
    assert len(records) == 1
    audit = json.loads(records[0])
    assert audit["project_key"] == "proj"
    assert audit["global_agent"] == "alice.athena.worker"
    assert audit["primary_revision"] == _POOL_REVISION
    assert TERMINAL_PROMPT_ARCHIVE_REASON_PREFIX in audit["evidence"]

    # Recording the same transition again is a no-op: one row, one record.
    assert (
        record_terminal_prompt_transition(project_key="proj", before=item, after=item)
        is False
    )
    assert (
        len(terminal_obligations_path().read_text(encoding="utf-8").splitlines()) == 1
    )

    # --retry-quarantined revival never touches terminal rows.
    revived, _diagnostics = revive_agent_publications(
        "proj", retry_retired=False, retry_quarantined=True
    )
    assert revived == ()
    [still] = list_agent_publications("proj")
    assert still.terminal is True

    # The row is retired, never acknowledged as published.
    assert retired_count(list_agent_publications("proj")) == 1


def test_pool_protection_released_for_terminal_prompt_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pool GC treats the terminal revision as collectible again."""

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "source.txt"
    source.write_text("still needed", encoding="utf-8")
    artifacts_dir = workspace / "run"
    pool_relpath = _stage_pool_file(workspace, artifacts_dir, source)
    pool_path = workspace / ".sase/artifacts" / pool_relpath
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "done.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8"
    )
    (artifacts_dir / "commit_state.json").write_text(
        json.dumps(
            {
                "completed_steps": ["publish_prompt_archive"],
                "primary_revision": _POOL_REVISION,
            }
        ),
        encoding="utf-8",
    )
    item = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent="worker",
            global_agent="alice.athena.worker",
            primary_revision=_POOL_REVISION,
            local_hood="worker",
            artifacts_dir=str(artifacts_dir),
            run_id=artifacts_dir.name,
        )
    )
    error = _terminal_error()
    for _ in range(2):
        [item] = update_agent_publications(
            "proj",
            (item.logical_key,),
            error=error,
            increment_attempts=True,
            quarantine_threshold=None,
            terminal_reason=error,
        )
    [terminal] = list_agent_publications("proj")
    assert terminal.terminal is True
    assert is_terminal_prompt_archive_reason(terminal.terminal_reason)

    monkeypatch.setattr(
        "sase.core.prompt_artifact_staging_pool.get_artifact_capture_pool_max_bytes",
        lambda: 1,
    )
    assert prune_prompt_artifact_pool(workspace) == 1
    assert not pool_path.exists()


def _stage_pool_file(workspace: Path, artifacts_dir: Path, source: Path) -> str:
    from sase.core.prompt_artifact_staging import stage_prompt_artifact

    record = stage_prompt_artifact(
        raw_ref="@source.txt",
        expanded_ref="@source.txt",
        resolved_path=source,
        ref_kind="file",
        label=source.name,
        workspace_root=workspace,
        agent_artifacts_dir=str(artifacts_dir),
    )
    relpath = record["pool_relpath"]
    assert isinstance(relpath, str)
    return relpath
