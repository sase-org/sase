from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import status
from sase.agents_sync.git_objects import FetchedAgentsCommit
from sase.agents_sync.incoming_detection import (
    _IncomingCaptureReport,
    capture_fetched_agent_updates,
)
from sase.agents_sync.io import atomic_write_json
from sase.agents_sync.models import (
    STATUS_SCHEMA_VERSION,
    AgentsManifest,
    ProjectSyncStatus,
    ProjectTarget,
    SyncStatusSnapshot,
    TargetSelection,
)
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
    enqueue_bead_pages_publication,
    update_agent_publications,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity


def _target(tmp_path: Path) -> ProjectTarget:
    primary = tmp_path / "primary"
    primary.mkdir()
    repo = tmp_path / "agents"
    (repo / ".git").mkdir(parents=True)
    atomic_write_json(repo / "manifest.json", AgentsManifest().to_json_dict())
    return ProjectTarget(
        "proj",
        "Project",
        primary,
        (primary.resolve(),),
        repo,
        "remote",
    )


def _patch_selection(
    monkeypatch: pytest.MonkeyPatch,
    target: ProjectTarget,
) -> None:
    monkeypatch.setattr(
        status,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        status,
        "require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )


def test_plain_status_reconciles_cache_without_running_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path)
    cache = tmp_path / "status.json"
    previous = SyncStatusSnapshot(
        100.0,
        (
            ProjectSyncStatus(
                "proj",
                "Project",
                "ready",
                2,
                3,
                last_fetch_time=90.0,
            ),
        ),
    )
    status._write_agents_sync_status_snapshot(previous, path=cache)
    _patch_selection(monkeypatch, target)

    def runner(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"short status must not run Git: {args}")

    snapshot = status.get_agents_sync_status(
        now=101.0,
        ttl_seconds=0.0,
        git_runner=runner,
        path=cache,
    )

    current = snapshot.projects[0]
    assert (current.ahead, current.behind) == (2, 3)
    assert current.last_fetch_time == 90.0


def test_plain_status_reports_publication_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target = _target(tmp_path)
    _patch_selection(monkeypatch, target)
    item = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent="bad--code",
            global_agent="alice.athena.bad--code",
            primary_revision="a" * 40,
            local_hood="bad",
        )
    )
    update_agent_publications(
        "proj",
        (item.logical_key,),
        error="broken history",
        increment_attempts=True,
        quarantine_threshold=1,
    )

    snapshot = status.get_agents_sync_status(
        now=101.0,
        path=tmp_path / "status.json",
    )

    diagnostics = snapshot.projects[0].quarantine_diagnostics
    assert len(diagnostics) == 1
    assert "alice.athena.bad--code" in diagnostics[0]
    assert "--retry-quarantined" in diagnostics[0]


def test_plain_status_reports_pending_typed_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target = _target(tmp_path)
    _patch_selection(monkeypatch, target)
    enqueue_bead_pages_publication(
        project_key="proj",
        project="Project",
        bead_id="proj-1.2",
        primary_revision="b" * 40,
    )

    snapshot = status.get_agents_sync_status(
        now=101.0,
        path=tmp_path / "status.json",
    )

    diagnostics = snapshot.projects[0].quarantine_diagnostics
    assert len(diagnostics) == 1
    assert "bead lineage proj-1@bbbbbbbbbbbb" in diagnostics[0]
    assert "queued for the publications lane" in diagnostics[0]
    assert "sidecar_publication" in diagnostics[0]


@pytest.mark.parametrize("cache_contents", [None, "{broken"])
def test_missing_or_corrupt_status_never_implies_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cache_contents: str | None,
) -> None:
    target = _target(tmp_path)
    cache = tmp_path / "status.json"
    if cache_contents is not None:
        cache.write_text(cache_contents)
    _patch_selection(monkeypatch, target)

    def runner(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"plain status must not run Git: {args}")

    snapshot = status.get_agents_sync_status(
        now=1000.0,
        git_runner=runner,
        path=cache,
    )

    assert snapshot.projects[0].state == "ready"
    assert snapshot.projects[0].last_fetch_time is None


def test_explicit_refresh_fetches_once_and_updates_cached_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path)
    cache = tmp_path / "status.json"
    calls: list[tuple[tuple[str, ...], bool]] = []
    _patch_selection(monkeypatch, target)
    monkeypatch.setattr(
        status,
        "capture_fetched_agent_updates",
        lambda *_args, **_kwargs: _IncomingCaptureReport(
            FetchedAgentsCommit("refs/remotes/origin/main", "a" * 40),
            (),
            2,
            1,
            (),
            1000.0,
        ),
    )

    def runner(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        calls.append((tuple(args), network))
        if args == ["rev-parse", "--git-dir"]:
            return subprocess.CompletedProcess(args, 0, ".git\n", "")
        if args[0] == "fetch":
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ["rev-parse", "--verify"]:
            return subprocess.CompletedProcess(args, 0, "upstream\n", "")
        if args[0] == "rev-list":
            return subprocess.CompletedProcess(args, 0, "2 3\n", "")
        raise AssertionError(args)

    snapshot = status.get_agents_sync_status(
        refresh=True,
        now=1000.0,
        git_runner=runner,
        path=cache,
    )

    assert sum(network for _args, network in calls) == 1
    current = snapshot.projects[0]
    assert (current.ahead, current.behind) == (2, 3)
    assert "unexported_agents" not in current.to_json_dict()
    assert current.fetched_sha == "a" * 40
    assert current.validated_foreign_count == 2
    assert current.exact_owner_count == 1


def test_refresh_aborts_before_git_when_shutdown_is_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target = _target(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    prior = ProjectSyncStatus(
        "proj",
        "Project",
        "ready",
        2,
        3,
        last_fetch_time=90.0,
    )
    calls: list[tuple[str, ...]] = []

    def runner(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del network, op
        calls.append(tuple(args))
        return subprocess.CompletedProcess(args, 0, "", "")

    refreshed = status._refresh_project_status(
        target,
        owner,
        prior=prior,
        checked_at=1000.0,
        git_runner=runner,
        lock_timeout_seconds=0.0,
        shutdown_requested=lambda: True,
    )

    assert calls == []
    assert refreshed == status._reconcile_project_status(target, owner, prior)


def test_capture_aborts_before_next_object_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync import incoming_detection

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(incoming_detection, "read_project_receipts", lambda _key: ())
    target = _target(tmp_path)
    checks = 0
    object_reads: list[str] = []

    class _Reader:
        def resolve_fetched_commit(self) -> FetchedAgentsCommit:
            return FetchedAgentsCommit("refs/remotes/origin/main", "a" * 40)

        def manifest_paths(self, _sha: str) -> tuple[str, ...]:
            return ("manifest.json",)

        def read_bytes(
            self,
            _sha: str,
            relative: str,
            *,
            maximum: int,
        ) -> bytes:
            del maximum
            object_reads.append(relative)
            return b"{}"

    def shutdown_requested() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    report = capture_fetched_agent_updates(
        target,
        AgentOwnerIdentity("alice", "athena"),
        reader=_Reader(),  # type: ignore[arg-type]
        now=1000.0,
        shutdown_requested=shutdown_requested,
    )

    assert report is None
    assert object_reads == []


def test_revalidate_only_never_runs_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path)
    cache = tmp_path / "status.json"
    status._write_agents_sync_status_snapshot(
        SyncStatusSnapshot(
            1.0,
            (
                ProjectSyncStatus(
                    "proj",
                    "Project",
                    "ready",
                    1,
                    2,
                    last_fetch_time=0.5,
                ),
            ),
        ),
        path=cache,
    )
    _patch_selection(monkeypatch, target)

    def runner(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"revalidation must not run Git: {args}")

    snapshot = status.get_agents_sync_status(
        now=1000.0,
        revalidate_only=True,
        git_runner=runner,
        path=cache,
    )

    current = snapshot.projects[0]
    assert (current.ahead, current.behind) == (1, 2)


def test_status_rejects_conflicting_network_modes() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        status.get_agents_sync_status(refresh=True, revalidate_only=True)


def test_post_sync_rewrite_never_runs_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path)
    _patch_selection(monkeypatch, target)
    monkeypatch.setattr(
        status,
        "_status_snapshot_path",
        lambda: tmp_path / "cache.json",
    )

    def runner(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"post-sync rewrite must not run Git: {args}")

    snapshot = status.rewrite_agents_sync_status_after_sync(
        now=50.0,
        git_runner=runner,
    )

    assert snapshot.projects[0].state == "ready"


def test_status_decoder_rejects_non_finite_times(tmp_path: Path) -> None:
    cache = tmp_path / "status.json"
    cache.write_text(
        '{"schema_version":2,"checked_at":NaN,"projects":[]}',
        encoding="utf-8",
    )

    assert status._read_agents_sync_status_snapshot(path=cache) is None


def test_status_decoder_discards_previous_schema_version(tmp_path: Path) -> None:
    cache = tmp_path / "status.json"
    payload = SyncStatusSnapshot(1.0).to_json_dict()
    payload["schema_version"] = STATUS_SCHEMA_VERSION - 1
    cache.write_text(json.dumps(payload), encoding="utf-8")

    assert status._read_agents_sync_status_snapshot(path=cache) is None
