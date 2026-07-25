from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import git_sync
from sase.agents_sync.git import _noninteractive_git_env, run_git
from sase.agents_sync.git_objects import LocalGitObjectReader
from sase.agents_sync.incoming_detection import capture_fetched_agent_updates
from sase.agents_sync.models import (
    IntegrationCounts,
    ProjectTarget,
    SyncOutcome,
    TargetSelection,
)
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
    list_agent_publications,
)
from sase.agents_sync.v2_models import V2PublicationCounts
from sase.core.agent_identity_facade import AgentOwnerIdentity


def test_default_sync_lock_timeout_waits_briefly() -> None:
    assert git_sync.DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS == 10.0


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def _setup_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init")
    _git(seed, "config", "user.name", "Tests")
    _git(seed, "config", "user.email", "tests@example.test")
    (seed / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "agents": {}}, indent=2) + "\n"
    )
    (seed / "agents").mkdir()
    (seed / "agents" / ".gitkeep").write_text("")
    (seed / "conflict.txt").write_text("base\n")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "HEAD")
    sidecar = tmp_path / "sidecar"
    _git(tmp_path, "clone", str(remote), str(sidecar))
    return remote, seed, sidecar


def _target(tmp_path: Path, remote: Path, sidecar: Path) -> ProjectTarget:
    primary = tmp_path / "primary"
    primary.mkdir(parents=True)
    return ProjectTarget(
        "proj",
        "Project",
        primary,
        (primary.resolve(),),
        sidecar,
        str(remote),
    )


def _patch_payload_pass(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr(
        git_sync,
        "integrate_agent_imports_with_receipts",
        lambda *_args, **_kwargs: IntegrationCounts(),
    )

    def reconcile(
        _target: ProjectTarget,
        repo: Path,
        **_kwargs: object,
    ) -> V2PublicationCounts:
        calls.append(1)
        (repo / "README.md").write_text("# Hoods\n")
        (repo / "schema.json").write_text("{}\n")
        manifest = repo / "users" / "local" / "machines" / "athena"
        manifest.mkdir(parents=True, exist_ok=True)
        (manifest / "manifest.json").write_text("{}\n")
        bundle = repo / "agents" / "local.athena.worker"
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "chat.md").write_text("chat\n")
        families = repo / "families"
        families.mkdir(exist_ok=True)
        (families / ".gitkeep").write_text("")
        return V2PublicationCounts(hoods_published=1, runs_published=1)

    monkeypatch.setattr(git_sync, "reconcile_agent_hoods", reconcile)
    return calls


def test_full_sync_reuses_one_name_registry_load_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    events: list[str] = []

    class _Session:
        def __enter__(self) -> None:
            events.append("enter")

        def __exit__(self, *_args: object) -> None:
            events.append("exit")

    monkeypatch.setattr(git_sync, "name_registry_load_session", _Session)

    def integrate(*_args: object, **_kwargs: object) -> IntegrationCounts:
        events.append("integrate")
        return IntegrationCounts()

    def reconcile(
        *_args: object,
        **_kwargs: object,
    ) -> V2PublicationCounts:
        events.append("reconcile")
        return V2PublicationCounts()

    monkeypatch.setattr(
        git_sync,
        "integrate_agent_imports_with_receipts",
        integrate,
    )
    monkeypatch.setattr(
        git_sync,
        "reconcile_agent_hoods",
        reconcile,
    )

    git_sync._integrate_export_pass(
        target,
        target.sidecar_path,
        AgentOwnerIdentity("alice", "athena"),
        run_git,
    )

    assert events == ["enter", "integrate", "reconcile", "exit"]


def test_full_sync_transaction_commits_and_pushes_only_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, _seed, sidecar = _setup_repo(tmp_path)
    target = _target(tmp_path, remote, sidecar)
    _patch_payload_pass(monkeypatch)

    outcome = git_sync._sync_project(target, "athena", git_runner=run_git)

    assert outcome.error is None
    assert outcome.pulled and outcome.committed and outcome.pushed
    assert outcome.hoods_published == 1
    verify = tmp_path / "verify"
    _git(tmp_path, "clone", str(remote), str(verify))
    assert (
        verify / "agents" / "local.athena.worker" / "chat.md"
    ).read_text() == "chat\n"
    assert _git(verify, "log", "-1", "--format=%s").stdout.strip() == (
        "chore(agents): sync from local.athena"
    )
    assert json.loads((verify / "manifest.json").read_text()) == {
        "schema_version": 1,
        "agents": {},
    }


def test_payload_commit_force_stages_user_ignored_hood(
    tmp_path: Path,
) -> None:
    _remote, _seed, sidecar = _setup_repo(tmp_path)
    (sidecar / "README.md").write_text("# Hoods\n")
    (sidecar / "schema.json").write_text("{}\n")
    for directory in ("users", "families"):
        root = sidecar / directory
        root.mkdir()
        (root / ".gitkeep").write_text("")
    _git(sidecar, "add", "README.md", "schema.json", "users", "families")
    _git(
        sidecar,
        "-c",
        "user.name=Tests",
        "-c",
        "user.email=tests@example.test",
        "commit",
        "-m",
        "complete sidecar baseline",
    )
    excludes = tmp_path / "global-excludes"
    excludes.write_text("*.gz\n")
    _git(sidecar, "config", "core.excludesFile", str(excludes))
    readme = sidecar / "agents" / "alice.athena.gz" / "README.md"
    readme.parent.mkdir()
    readme.write_text("# Ignored hood\n")
    assert _git(sidecar, "check-ignore", "-v", str(readme)).stdout

    owner = AgentOwnerIdentity("alice", "athena")
    assert git_sync.commit_agents_payload_if_dirty(sidecar, owner, run_git) is True
    head = _git(sidecar, "rev-parse", "HEAD").stdout.strip()
    assert (
        _git(sidecar, "show", "HEAD:agents/alice.athena.gz/README.md").stdout
        == "# Ignored hood\n"
    )

    assert git_sync.commit_agents_payload_if_dirty(sidecar, owner, run_git) is False
    assert _git(sidecar, "rev-parse", "HEAD").stdout.strip() == head


def test_owner_manifest_missing_file_diagnostic_names_ignore_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote, seed, sidecar = _setup_repo(tmp_path)
    manifest = seed / "users" / "alice" / "machines" / "athena" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "owner": {"username": "alice", "machine_name": "athena"},
                "project": {"key": "proj", "name": "Project"},
                "hoods": {
                    "gz": {
                        "digest": "a" * 64,
                        "files": ["agents/alice.athena.gz/README.md"],
                        "run_count": 1,
                        "family_count": 0,
                    }
                },
            }
        )
        + "\n"
    )
    _git(seed, "add", str(manifest.relative_to(seed)))
    _git(seed, "commit", "-m", "publish manifest without ignored hood")
    _git(seed, "push")
    _git(sidecar, "pull")
    excludes = tmp_path / "global-excludes"
    excludes.write_text("*.gz\n")
    _git(sidecar, "config", "core.excludesFile", str(excludes))
    ignored_readme = sidecar / "agents" / "alice.athena.gz" / "README.md"
    ignored_readme.parent.mkdir()
    ignored_readme.write_text("# Stranded hood\n")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))

    report = capture_fetched_agent_updates(
        _target(tmp_path, remote, sidecar),
        AgentOwnerIdentity("alice", "athena"),
        reader=LocalGitObjectReader(sidecar),
        now=1.0,
    )

    assert len(report.diagnostics) == 1
    diagnostic = report.diagnostics[0]
    assert "owner manifest references 'agents/alice.athena.gz/README.md'" in diagnostic
    assert "missing from commit" in diagnostic
    assert "local ignore rule:" in diagnostic
    assert "*.gz" in diagnostic


def test_non_fast_forward_recomputes_and_retries_push_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, _seed, sidecar = _setup_repo(tmp_path)
    target = _target(tmp_path, remote, sidecar)
    export_calls = _patch_payload_pass(monkeypatch)
    intruder = tmp_path / "intruder"
    _git(tmp_path, "clone", str(remote), str(intruder))
    _git(intruder, "config", "user.name", "Intruder")
    _git(intruder, "config", "user.email", "intruder@example.test")
    push_calls = 0

    def rejecting_runner(
        cwd: Path, args: list[str], *, network: bool = False, op: str = ""
    ) -> subprocess.CompletedProcess[str]:
        nonlocal push_calls
        if args == ["push"]:
            push_calls += 1
            if push_calls == 1:
                (intruder / "remote.txt").write_text("remote\n")
                _git(intruder, "add", "remote.txt")
                _git(intruder, "commit", "-m", "remote race")
                _git(intruder, "push")
        return run_git(cwd, args, network=network, op=op)

    outcome = git_sync._sync_project(target, "athena", git_runner=rejecting_runner)

    assert outcome.error is None
    assert outcome.push_attempts == 2
    assert outcome.pushed
    assert push_calls == 2
    assert len(export_calls) == 2
    assert not (sidecar / ".git" / "rebase-merge").exists()
    assert not (sidecar / ".git" / "rebase-apply").exists()


def test_bounded_lock_contention_is_a_benign_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, _seed, sidecar = _setup_repo(tmp_path)
    target = _target(tmp_path, remote, sidecar)
    _patch_payload_pass(monkeypatch)
    lock_path = sidecar / ".git" / "sase-agents-sync.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        outcome = git_sync._sync_project(
            target,
            "athena",
            git_runner=run_git,
            lock_timeout_seconds=0,
        )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    assert outcome.error is None
    assert outcome.skip_reason == "agents sync lock is busy"


def test_missing_configured_remote_is_not_created(tmp_path: Path) -> None:
    missing = tmp_path / "missing.git"
    target = _target(tmp_path, missing, tmp_path / "sidecar")

    outcome = git_sync._sync_project(target, "athena", git_runner=run_git)

    assert outcome.error is not None
    assert "could not clone" in outcome.error
    assert not missing.exists()


def test_pull_rebase_conflict_is_aborted_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, _seed, sidecar = _setup_repo(tmp_path)
    target = _target(tmp_path, remote, sidecar)
    _git(sidecar, "config", "user.name", "Local")
    _git(sidecar, "config", "user.email", "local@example.test")
    (sidecar / "conflict.txt").write_text("local\n")
    _git(sidecar, "add", "conflict.txt")
    _git(sidecar, "commit", "-m", "local ahead")

    intruder = tmp_path / "conflict-intruder"
    _git(tmp_path, "clone", str(remote), str(intruder))
    _git(intruder, "config", "user.name", "Remote")
    _git(intruder, "config", "user.email", "remote@example.test")
    (intruder / "conflict.txt").write_text("remote\n")
    _git(intruder, "add", "conflict.txt")
    _git(intruder, "commit", "-m", "remote ahead")
    _git(intruder, "push")
    monkeypatch.setattr(
        git_sync,
        "integrate_agent_imports_with_receipts",
        lambda *_args, **_kwargs: pytest.fail("integration must not run"),
    )

    outcome = git_sync._sync_project(target, "athena", git_runner=run_git)

    assert outcome.error is not None
    assert "pull --rebase failed" in outcome.error
    assert _git(sidecar, "log", "-1", "--format=%s").stdout.strip() == "local ahead"
    assert (sidecar / "conflict.txt").read_text() == "local\n"
    assert not (sidecar / ".git" / "rebase-merge").exists()
    assert not (sidecar / ".git" / "rebase-apply").exists()


def test_all_project_sync_isolates_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _target(tmp_path / "one", tmp_path / "one.git", tmp_path / "one-sidecar")
    second = _target(tmp_path / "two", tmp_path / "two.git", tmp_path / "two-sidecar")
    first = ProjectTarget(
        "one",
        "One",
        first.primary_checkout,
        first.primary_roots,
        first.sidecar_path,
        first.remote_url,
    )
    second = ProjectTarget(
        "two",
        "Two",
        second.primary_checkout,
        second.primary_roots,
        second.sidecar_path,
        second.remote_url,
    )
    monkeypatch.setattr(
        git_sync,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((first, second), ()),
    )
    monkeypatch.setattr(
        git_sync,
        "require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        git_sync,
        "_sync_project",
        lambda target, *_args, **_kwargs: (
            (_ for _ in ()).throw(RuntimeError("broken"))
            if target.project_key == "one"
            else SyncOutcome("two", "Two", pulled=True)
        ),
    )
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )

    outcomes = git_sync.sync_agents()

    assert [outcome.project_key for outcome in outcomes] == ["one", "two"]
    assert outcomes[0].error == "agents sync failed: broken"
    assert outcomes[1].pulled is True


def test_full_sync_acknowledges_publication_outbox_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target = _target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    published_page = target.sidecar_path / "agents" / "alice.athena.foo" / "README.md"
    published_page.parent.mkdir(parents=True)
    published_page.write_text("# foo\n")
    enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=target.project_key,
            project=target.project,
            local_agent="foo",
            global_agent="alice.athena.foo",
            primary_revision="a" * 40,
            local_hood="foo",
        )
    )
    monkeypatch.setattr(
        git_sync,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        git_sync,
        "require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        git_sync,
        "_sync_project",
        lambda *_args, **_kwargs: SyncOutcome("proj", "Project", pulled=True),
    )
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )

    assert git_sync.sync_agents() == (SyncOutcome("proj", "Project", pulled=True),)
    assert list_agent_publications("proj") == ()


def test_full_sync_keeps_outbox_request_when_agent_page_did_not_materialize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target = _target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    item = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=target.project_key,
            project=target.project,
            local_agent="missing",
            global_agent="alice.athena.missing",
            primary_revision="a" * 40,
            local_hood="missing",
        )
    )
    monkeypatch.setattr(
        git_sync,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        git_sync,
        "require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        git_sync,
        "_sync_project",
        lambda *_args, **_kwargs: SyncOutcome("proj", "Project", pulled=True),
    )
    monkeypatch.setattr(
        "sase.agents_sync.status.rewrite_agents_sync_status_after_sync",
        lambda _projects: None,
    )

    assert git_sync.sync_agents() == (SyncOutcome("proj", "Project", pulled=True),)
    remaining = list_agent_publications("proj")
    assert len(remaining) == 1
    assert remaining[0].logical_key == item.logical_key
    assert remaining[0].attempts == 1
    assert remaining[0].last_error == (
        "published agent page for 'alice.athena.missing' did not materialize "
        "during full sync"
    )


def test_network_git_environment_is_noninteractive() -> None:
    original = {"PATH": "/bin", "GIT_TERMINAL_PROMPT": "1"}

    env = _noninteractive_git_env(original)

    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
    assert original["GIT_TERMINAL_PROMPT"] == "1"
