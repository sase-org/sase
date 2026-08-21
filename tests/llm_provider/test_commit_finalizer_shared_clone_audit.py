"""Attributable shared-clone classification events and git provenance.

Controlled races exercise the discarded-work guard against real git, not
mocks. Positive cases cover foreign-agent, already-published, and
pending-publication transitions in opened-external and sdd-kind clones, and
prove the dirty blob is still reachable from the new HEAD. Negative controls
keep main/sibling clones, unattributable owned-repo commits, and genuine
resets fail-closed.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Literal

import pytest

from sase.feature_flags import override_flags
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer_git_progress import (
    SHARED_CLONE_CLASSIFICATION_EVENT,
    SHARED_CLONE_CLASSIFICATION_FILENAME,
    discarded_dirty_work_evidence,
    progress_fingerprint,
)
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState

from ._commit_finalizer_sibling_helpers import init_git_repo

_RepoKind = Literal["main", "sibling", "external", "sdd"]
_DIRTY_RELPATH = "payload.txt"
_DIRTY_CONTENT = "unique-agent-payload\n"


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _current_branch(repo: Path) -> str:
    return _run_git(repo, "branch", "--show-current").strip()


def _hash_file(path: Path) -> str:
    result = subprocess.run(
        ["git", "hash-object", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _head_blob(repo: Path, relpath: str) -> str:
    return _run_git(repo, "rev-parse", f"HEAD:{relpath}").strip()


def _head_sha(repo: Path) -> str:
    return _run_git(repo, "rev-parse", "HEAD").strip()


def _init_repo_with_upstream(base: Path, name: str) -> Path:
    origin = base / f"{name}-origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
    repo = base / name
    init_git_repo(repo)
    _run_git(repo, "remote", "add", "origin", str(origin))
    _run_git(repo, "push", "-u", "origin", _current_branch(repo))
    return repo


def _dirty_state(
    repo: Path,
    changed_files: tuple[str, ...],
    *,
    kind: _RepoKind,
) -> DirtyState:
    return DirtyState(
        project_dir=finalizer_git.normalize_path(str(repo)),
        repos=(
            DirtyRepo(
                name="research",
                path=finalizer_git.normalize_path(str(repo)),
                changed_files=changed_files,
                kind=kind,
            ),
        ),
        details="",
    )


def _clean_state(repo: Path) -> DirtyState:
    return DirtyState(
        project_dir=finalizer_git.normalize_path(str(repo)),
        repos=(),
        details="",
    )


def _write_dirty_payload(repo: Path) -> str:
    path = repo / _DIRTY_RELPATH
    path.write_text(_DIRTY_CONTENT, encoding="utf-8")
    return _hash_file(path)


def _read_events(artifacts_dir: Path) -> list[dict[str, Any]]:
    path = artifacts_dir / SHARED_CLONE_CLASSIFICATION_FILENAME
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _assert_event_is_path_free(event: dict[str, Any], repo: Path) -> None:
    blob = json.dumps(event)
    assert str(repo) not in blob
    assert _DIRTY_RELPATH not in blob
    assert _DIRTY_CONTENT.strip() not in blob
    assert event["event"] == SHARED_CLONE_CLASSIFICATION_EVENT
    assert isinstance(event["event_id"], str) and event["event_id"]


def _snapshot_dirty(
    repo: Path,
    *,
    kind: _RepoKind,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[DirtyState, tuple[tuple[str, str, tuple[str, ...]], ...], str, str]:
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    dirty_blob = _write_dirty_payload(repo)
    before = _dirty_state(repo, (_DIRTY_RELPATH,), kind=kind)
    return before, progress_fingerprint(before), dirty_blob, _head_sha(repo)


def _classify(
    repo: Path,
    *,
    before: DirtyState,
    fingerprint_before: tuple[tuple[str, str, tuple[str, ...]], ...],
    artifacts_dir: Path,
) -> tuple[tuple[Any, ...], dict[str, Any] | None]:
    evidence = discarded_dirty_work_evidence(
        before,
        _clean_state(repo),
        fingerprint_before=fingerprint_before,
        artifacts_dir=str(artifacts_dir),
    )
    events = _read_events(artifacts_dir)
    return evidence, events[-1] if events else None


def test_log_message_omits_paths_and_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo = tmp_path / "research"
    init_git_repo(repo)
    before, fingerprint_before, dirty_blob, _before_head = _snapshot_dirty(
        repo, kind="sdd", monkeypatch=monkeypatch
    )
    _run_git(repo, "add", "-A")
    _run_git(
        repo,
        "commit",
        "-q",
        "-m",
        "commit dirty payload\n\nSASE_AGENT=other-agent",
    )
    caplog.set_level(
        logging.WARNING,
        logger="sase.llm_provider.commit_finalizer_git_progress",
    )
    evidence, event = _classify(
        repo,
        before=before,
        fingerprint_before=fingerprint_before,
        artifacts_dir=tmp_path / "artifacts",
    )
    assert evidence == ()
    assert event is not None
    assert _head_blob(repo, _DIRTY_RELPATH) == dirty_blob
    messages = [record.getMessage() for record in caplog.records]
    joined = "\n".join(messages)
    assert str(repo) not in joined
    assert _DIRTY_RELPATH not in joined
    assert _DIRTY_CONTENT.strip() not in joined
    assert event["event_id"] in joined


@pytest.mark.parametrize("kind", ["sdd", "external"])
def test_foreign_agent_commit_is_race_and_preserves_blob(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: _RepoKind,
) -> None:
    repo = tmp_path / "research"
    init_git_repo(repo)
    before, fingerprint_before, dirty_blob, before_head = _snapshot_dirty(
        repo, kind=kind, monkeypatch=monkeypatch
    )
    _run_git(repo, "add", "-A")
    _run_git(
        repo,
        "commit",
        "-q",
        "-m",
        "commit dirty payload\n\nSASE_AGENT=other-agent",
    )
    evidence, event = _classify(
        repo,
        before=before,
        fingerprint_before=fingerprint_before,
        artifacts_dir=tmp_path / "artifacts",
    )
    assert evidence == ()
    assert event is not None
    _assert_event_is_path_free(event, repo)
    assert event["repo_kind"] == kind
    assert event["attribution_class"] == "foreign_agent"
    assert event["classification"] == "race"
    assert event["before_head"] == before_head
    assert event["after_head"] == _head_sha(repo)
    assert event["upstream_ahead"] is None
    assert _head_blob(repo, _DIRTY_RELPATH) == dirty_blob


@pytest.mark.parametrize("kind", ["sdd", "external"])
def test_already_published_transition_preserves_blob(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: _RepoKind,
) -> None:
    repo = _init_repo_with_upstream(tmp_path, "research")
    before, fingerprint_before, dirty_blob, before_head = _snapshot_dirty(
        repo, kind=kind, monkeypatch=monkeypatch
    )
    origin = _run_git(repo, "remote", "get-url", "origin").strip()
    clone = tmp_path / "foreign-clone"
    subprocess.run(["git", "clone", "-q", origin, str(clone)], check=True)
    subprocess.run(
        ["git", "config", "user.name", "Foreign Agent"], cwd=clone, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "foreign@example.invalid"],
        cwd=clone,
        check=True,
    )
    (clone / _DIRTY_RELPATH).write_text(_DIRTY_CONTENT, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "publish absorbed payload"],
        cwd=clone,
        check=True,
    )
    subprocess.run(
        ["git", "push", "-q", "origin", _current_branch(clone)],
        cwd=clone,
        check=True,
    )
    _run_git(repo, "fetch", "-q", "origin")
    _run_git(repo, "reset", "-q", "--hard", f"origin/{_current_branch(repo)}")
    assert _run_git(repo, "rev-list", "--count", "@{upstream}..HEAD").strip() == "0"

    evidence, event = _classify(
        repo,
        before=before,
        fingerprint_before=fingerprint_before,
        artifacts_dir=tmp_path / "artifacts",
    )
    assert evidence == ()
    assert event is not None
    _assert_event_is_path_free(event, repo)
    assert event["repo_kind"] == kind
    assert event["attribution_class"] == "unattributed"
    assert event["classification"] == "published"
    assert event["before_head"] == before_head
    assert event["after_head"] == _head_sha(repo)
    assert event["upstream_ahead"] == 0
    assert _head_blob(repo, _DIRTY_RELPATH) == dirty_blob


@pytest.mark.parametrize("kind", ["sdd", "external"])
def test_pending_publication_transition_preserves_blob(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: _RepoKind,
) -> None:
    repo = _init_repo_with_upstream(tmp_path, "research")
    before, fingerprint_before, dirty_blob, before_head = _snapshot_dirty(
        repo, kind=kind, monkeypatch=monkeypatch
    )
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "local unattributed commit")
    assert _run_git(repo, "rev-list", "--count", "@{upstream}..HEAD").strip() == "1"

    evidence, event = _classify(
        repo,
        before=before,
        fingerprint_before=fingerprint_before,
        artifacts_dir=tmp_path / "artifacts",
    )
    assert evidence == ()
    assert event is not None
    _assert_event_is_path_free(event, repo)
    assert event["repo_kind"] == kind
    assert event["attribution_class"] == "unattributed"
    assert event["classification"] == "published"
    assert event["before_head"] == before_head
    assert event["after_head"] == _head_sha(repo)
    assert event["upstream_ahead"] == 1
    assert _head_blob(repo, _DIRTY_RELPATH) == dirty_blob


@pytest.mark.parametrize("kind", ["main", "sibling"])
def test_owned_repo_foreign_agent_commit_is_discard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: _RepoKind,
) -> None:
    repo = tmp_path / "workspace"
    init_git_repo(repo)
    before, fingerprint_before, dirty_blob, _before_head = _snapshot_dirty(
        repo, kind=kind, monkeypatch=monkeypatch
    )
    _run_git(repo, "add", "-A")
    _run_git(
        repo,
        "commit",
        "-q",
        "-m",
        "commit dirty payload\n\nSASE_AGENT=other-agent",
    )
    evidence, event = _classify(
        repo,
        before=before,
        fingerprint_before=fingerprint_before,
        artifacts_dir=tmp_path / "artifacts",
    )
    assert [item.reason for item in evidence] == ["missing_agent_provenance"]
    assert event is not None
    _assert_event_is_path_free(event, repo)
    assert event["repo_kind"] == kind
    assert event["attribution_class"] == "foreign_agent"
    assert event["classification"] == "discard"
    assert _head_blob(repo, _DIRTY_RELPATH) == dirty_blob


@pytest.mark.parametrize("kind", ["main", "sibling"])
def test_owned_repo_unattributed_commit_is_discard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: _RepoKind,
) -> None:
    repo = tmp_path / "workspace"
    init_git_repo(repo)
    before, fingerprint_before, _dirty_blob, _before_head = _snapshot_dirty(
        repo, kind=kind, monkeypatch=monkeypatch
    )
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "local unattributed commit")
    evidence, event = _classify(
        repo,
        before=before,
        fingerprint_before=fingerprint_before,
        artifacts_dir=tmp_path / "artifacts",
    )
    assert [item.reason for item in evidence] == ["missing_agent_provenance"]
    assert event is not None
    assert event["attribution_class"] == "unattributed"
    assert event["classification"] == "discard"


def test_reset_without_commit_is_head_not_advanced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "workspace"
    init_git_repo(repo)
    _write_dirty_payload(repo)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    before = _dirty_state(repo, (_DIRTY_RELPATH,), kind="main")
    fingerprint_before = progress_fingerprint(before)
    _run_git(repo, "checkout", "--", ".")
    artifacts_dir = tmp_path / "artifacts"
    evidence = discarded_dirty_work_evidence(
        before,
        _clean_state(repo),
        fingerprint_before=fingerprint_before,
        artifacts_dir=str(artifacts_dir),
    )
    assert [item.reason for item in evidence] == ["head_not_advanced"]
    assert _read_events(artifacts_dir) == []


def test_current_agent_commit_emits_no_classification_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "workspace"
    init_git_repo(repo)
    dirty_blob = _write_dirty_payload(repo)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    before = _dirty_state(repo, (_DIRTY_RELPATH,), kind="sdd")
    fingerprint_before = progress_fingerprint(before)
    _run_git(repo, "add", "-A")
    _run_git(
        repo,
        "commit",
        "-q",
        "-m",
        "commit dirty payload\n\nSASE_AGENT=current-agent",
    )
    artifacts_dir = tmp_path / "artifacts"
    evidence = discarded_dirty_work_evidence(
        before,
        _clean_state(repo),
        fingerprint_before=fingerprint_before,
        artifacts_dir=str(artifacts_dir),
    )
    assert evidence == ()
    assert _read_events(artifacts_dir) == []
    assert _head_blob(repo, _DIRTY_RELPATH) == dirty_blob


def test_flag_off_keeps_external_foreign_agent_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "widget"
    init_git_repo(repo)
    before, fingerprint_before, _dirty_blob, _before_head = _snapshot_dirty(
        repo, kind="external", monkeypatch=monkeypatch
    )
    _run_git(repo, "add", "-A")
    _run_git(
        repo,
        "commit",
        "-q",
        "-m",
        "commit dirty payload\n\nSASE_AGENT=other-agent",
    )
    artifacts_dir = tmp_path / "artifacts"
    with override_flags(commit_finalizer_shared_clone_exempt=False):
        evidence = discarded_dirty_work_evidence(
            before,
            _clean_state(repo),
            fingerprint_before=fingerprint_before,
            artifacts_dir=str(artifacts_dir),
        )
    events = _read_events(artifacts_dir)
    assert [item.reason for item in evidence] == ["missing_agent_provenance"]
    assert events[-1]["classification"] == "discard"
    assert events[-1]["repo_kind"] == "external"
    assert events[-1]["attribution_class"] == "foreign_agent"


def test_shared_clone_counter_increments_for_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict[str, str]] = []

    class _Metric:
        def labels(self, **kwargs: str) -> _Metric:
            recorded.append(dict(kwargs))
            return self

        def inc(self) -> None:
            recorded[-1]["inc"] = "1"

    monkeypatch.setattr(
        "sase.telemetry.metrics.FINALIZER_SHARED_CLONE",
        _Metric(),
    )
    repo = tmp_path / "research"
    init_git_repo(repo)
    before, fingerprint_before, _dirty_blob, _before_head = _snapshot_dirty(
        repo, kind="sdd", monkeypatch=monkeypatch
    )
    _run_git(repo, "add", "-A")
    _run_git(
        repo,
        "commit",
        "-q",
        "-m",
        "commit dirty payload\n\nSASE_AGENT=other-agent",
    )
    evidence, event = _classify(
        repo,
        before=before,
        fingerprint_before=fingerprint_before,
        artifacts_dir=tmp_path / "artifacts",
    )
    assert evidence == ()
    assert event is not None
    assert recorded == [
        {
            "repo_kind": "sdd",
            "attribution_class": "foreign_agent",
            "classification": "race",
            "upstream_ahead": "none",
            "inc": "1",
        }
    ]
