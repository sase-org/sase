from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync.git import run_git
from sase.agents_sync.git_objects import FetchedAgentsCommit, LocalGitObjectReader
from sase.agents_sync.incoming_detection import capture_fetched_agent_updates
from sase.agents_sync.io import atomic_write_json, read_manifest
from sase.agents_sync.models import (
    AgentsManifest,
    ManifestEntry,
    ProjectTarget,
    TargetSelection,
)
from sase.agents_sync.v1_retirement import (
    _apply_v1_retirement,
    _plan_v1_retirement,
    retire_v1_payloads,
)
from sase.agents_sync.v2_io import (
    content_digest,
    owner_manifest_path,
    v2_json_bytes,
)
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity

OWNER = AgentOwnerIdentity("alice", "athena")
PROJECT = V2ProjectIdentity("proj", "Project")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _entry(machine: str, hood: str, *, timestamp: str) -> ManifestEntry:
    return ManifestEntry(
        f"{machine}.{hood}",
        machine,
        hashlib.sha256(hood.encode()).hexdigest(),
        timestamp,
        "2026-07-25T12:00:00+00:00",
    )


def _write_payload(repo: Path, entries: tuple[ManifestEntry, ...]) -> None:
    atomic_write_json(
        repo / "manifest.json",
        AgentsManifest(entries).to_json_dict(),
    )
    for entry in entries:
        bundle = repo / "agents" / entry.name
        bundle.mkdir(parents=True)
        (bundle / "chat.md").write_text(f"{entry.name}\n", encoding="utf-8")


def _write_owner_manifest(repo: Path, *hoods: str) -> None:
    entries: list[tuple[str, V2OwnerHoodEntry]] = []
    for hood in sorted(hoods):
        snapshot = V2HoodSnapshot(
            OWNER,
            PROJECT,
            hood,
            f"{OWNER.username}.{OWNER.machine_name}.{hood}",
            (f"{OWNER.username}.{OWNER.machine_name}.{hood}",),
        )
        snapshot_bytes = v2_json_bytes(snapshot.to_json_dict())
        root = (
            repo
            / "users"
            / OWNER.username
            / "machines"
            / OWNER.machine_name
            / "hoods"
            / hood
        )
        root.mkdir(parents=True, exist_ok=True)
        (root / "snapshot.json").write_bytes(snapshot_bytes)
        (root / "README.md").write_text(f"# {hood}\n", encoding="utf-8")
        entries.append(
            (
                hood,
                V2OwnerHoodEntry(
                    content_digest(snapshot_bytes),
                    tuple(
                        sorted(
                            (
                                (root / "README.md").relative_to(repo).as_posix(),
                                (root / "snapshot.json").relative_to(repo).as_posix(),
                            )
                        )
                    ),
                    0,
                    0,
                ),
            )
        )
    manifest = V2OwnerManifest(
        OWNER,
        PROJECT,
        tuple(entries),
    )
    atomic_write_json(
        repo / owner_manifest_path(OWNER),
        manifest.to_json_dict(),
    )


def _target(
    primary: Path, sidecar: Path, remote: Path | str = "remote"
) -> ProjectTarget:
    return ProjectTarget(
        PROJECT.key,
        PROJECT.name,
        primary,
        (primary.resolve(),),
        sidecar,
        str(remote),
    )


def test_retirement_refuses_uncovered_current_machine_hood(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    repo = tmp_path / "sidecar"
    (repo / ".git").mkdir(parents=True)
    _write_payload(
        repo,
        (_entry("athena", "missing", timestamp="20260725120000"),),
    )
    _write_owner_manifest(repo, "other")
    target = _target(primary, repo)

    plan = _plan_v1_retirement(target, repo, OWNER)

    assert plan.uncovered_hoods == ("missing",)
    with pytest.raises(ValueError, match="does not cover: missing"):
        _apply_v1_retirement(repo, OWNER, plan)
    assert (repo / "manifest.json").is_file()
    assert (repo / "agents" / "athena.missing").is_dir()


def test_retirement_is_dry_run_by_default_and_mutates_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    repo = tmp_path / "sidecar"
    (repo / ".git").mkdir(parents=True)
    _write_payload(
        repo,
        (_entry("athena", "covered", timestamp="20260725120000"),),
    )
    _write_owner_manifest(repo, "covered")
    target = _target(primary, repo)
    before = {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(
        "sase.agents_sync.v1_retirement.resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        "sase.agents_sync.v1_retirement.require_agent_owner_identity",
        lambda: OWNER,
    )

    outcome = retire_v1_payloads()[0]

    after = {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file()
    }
    assert outcome.dry_run
    assert outcome.payload_paths == (
        "manifest.json",
        "agents/athena.covered",
    )
    assert before == after


def test_apply_removes_owner_only_manifest_and_payload(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    repo = tmp_path / "sidecar"
    repo.mkdir()
    _write_payload(
        repo,
        (_entry("athena", "covered", timestamp="20260725120000"),),
    )
    _write_owner_manifest(repo, "covered")
    target = _target(primary, repo)
    plan = _plan_v1_retirement(target, repo, OWNER)

    _apply_v1_retirement(repo, OWNER, plan)

    assert not (repo / "manifest.json").exists()
    assert not (repo / "agents" / "athena.covered").exists()
    assert (repo / owner_manifest_path(OWNER)).is_file()


def test_plan_does_not_report_an_already_missing_bundle_as_removed(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    repo = tmp_path / "sidecar"
    repo.mkdir()
    entry = _entry("athena", "covered", timestamp="20260725120000")
    atomic_write_json(
        repo / "manifest.json",
        AgentsManifest((entry,)).to_json_dict(),
    )
    _write_owner_manifest(repo, "covered")

    plan = _plan_v1_retirement(_target(primary, repo), repo, OWNER)

    assert plan.manifest_entries == ("athena.covered",)
    assert plan.payload_paths == ("manifest.json",)


def test_retired_owner_only_sidecar_detects_zero_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    primary = tmp_path / "primary"
    primary.mkdir()
    repo = tmp_path / "sidecar"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Tests")
    _git(repo, "config", "user.email", "tests@example.test")
    entry = _entry("athena", "covered", timestamp="20260725120000")
    _write_payload(repo, (entry,))
    _write_owner_manifest(repo, "covered")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "legacy and v2")
    target = _target(primary, repo)
    plan = _plan_v1_retirement(target, repo, OWNER)
    _apply_v1_retirement(repo, OWNER, plan)
    _git(repo, "add", "--all")
    _git(repo, "commit", "-m", "retire v1")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    class _HeadReader(LocalGitObjectReader):
        def resolve_fetched_commit(self) -> FetchedAgentsCommit:
            return FetchedAgentsCommit("HEAD", head)

    report = capture_fetched_agent_updates(
        target,
        OWNER,
        reader=_HeadReader(repo),
        now=1.0,
    )

    assert report.pending_updates == ()
    assert report.exact_owner_count == 1
    assert report.diagnostics == ()


def test_apply_preserves_other_machine_and_commits_through_sync_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init")
    _git(seed, "config", "user.name", "Tests")
    _git(seed, "config", "user.email", "tests@example.test")
    owned = _entry("athena", "covered", timestamp="20260725120000")
    foreign = _entry("zeus", "foreign", timestamp="20260725120001")
    _write_payload(seed, (owned, foreign))
    _write_owner_manifest(seed, "covered")
    for path in ("README.md", "schema.json"):
        (seed / path).write_text("{}\n", encoding="utf-8")
    (seed / "families").mkdir()
    (seed / "families" / ".gitkeep").write_text("", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "HEAD")

    sidecar = tmp_path / "sidecar"
    _git(tmp_path, "clone", str(remote), str(sidecar))
    primary = tmp_path / "primary"
    primary.mkdir()
    target = _target(primary, sidecar, remote)
    monkeypatch.setattr(
        "sase.agents_sync.v1_retirement.resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        "sase.agents_sync.v1_retirement.require_agent_owner_identity",
        lambda: OWNER,
    )

    outcome = retire_v1_payloads(apply=True, git_runner=run_git)[0]

    assert outcome.ok
    assert outcome.committed and outcome.pushed
    assert outcome.manifest_entries == ("athena.covered",)
    assert outcome.payload_paths == ("agents/athena.covered",)
    verify = tmp_path / "verify"
    _git(tmp_path, "clone", str(remote), str(verify))
    assert read_manifest(verify / "manifest.json") == AgentsManifest((foreign,))
    assert not (verify / "agents" / "athena.covered").exists()
    assert (verify / "agents" / "zeus.foreign" / "chat.md").is_file()
    assert _git(verify, "log", "-1", "--format=%s").stdout.strip() == (
        "chore(agents): sync from alice.athena"
    )


def test_retirement_outcome_json_names_every_removed_item(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    repo = tmp_path / "sidecar"
    repo.mkdir()
    entry = _entry("athena", "covered", timestamp="20260725120000")
    _write_payload(repo, (entry,))
    _write_owner_manifest(repo, "covered")

    plan = _plan_v1_retirement(_target(primary, repo), repo, OWNER)
    payload = {
        "manifest_entries": list(plan.manifest_entries),
        "payload_paths": list(plan.payload_paths),
    }

    assert json.dumps(payload, sort_keys=True) == (
        '{"manifest_entries": ["athena.covered"], "payload_paths": '
        '["manifest.json", "agents/athena.covered"]}'
    )
