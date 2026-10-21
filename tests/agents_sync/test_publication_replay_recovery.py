from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import sase_core_rs

from sase.agents_sync.git import run_git
from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication import publish_agent_hood
from sase.agents_sync.publication_replay_recovery import (
    BUNDLE_NAME,
    CHECKSUMS_NAME,
    OBJECTS_DIR,
    PRESERVED_DIR,
    PROGRESS_NAME,
    REVISIONS_NAME,
    recover_stale_replay,
)
from sase.agents_sync.publication_validation import load_validated_publication
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.agent_publication_recovery import (
    REPLAY_APPLY_ACTION_ALREADY_COMPLETE,
    REPLAY_APPLY_ACTION_APPLY,
    REPLAY_APPLY_ACTION_REFUSE,
    REPLAY_APPLY_ACTION_REPORT,
)
from sase.plan_chain import AGENT_SESSION_KEY
from sase.sase_agent import agent_session_page_path

from tests.agents_sync.git_sync_fixtures import git, setup_repo, target

ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "agents_publication_recover_replay"

SHARED_CHAT = b"shared chat\n"
LOCAL_CHAT = b"LOCAL UNIQUE CHAT\n"
REMOTE_CHAT = b"REMOTE UNIQUE CHAT\n"
SESSION_CHAT = b"LOCAL SESSION CHAT\n"
STALE_BROWSING = "STALE LOCAL BROWSING\n"
PENDING_OBJECT = b"pending unique object\n"


@dataclass(frozen=True, slots=True)
class _ReplayFixture:
    remote: Path
    sidecar: Path
    target: ProjectTarget
    owner: AgentOwnerIdentity
    backup: Path
    head: str
    object_relpath: str


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("agents_publication_recover_replay", str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "agents_publication_recover_replay", TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(
    owner: AgentOwnerIdentity,
    name: str,
    suffix: str,
    *,
    chat: bytes,
    agent_session: str | None = None,
) -> InventoryRun:
    metadata: tuple[tuple[str, object], ...] = (("model", "gpt"),)
    if agent_session is not None:
        metadata += ((AGENT_SESSION_KEY, agent_session),)
    return InventoryRun(
        f"run-{suffix}",
        name,
        f"{owner.username}.{owner.machine_name}.{name}",
        "completed",
        "2026-07-23T12:00:00+00:00",
        "2026-07-23T12:01:00+00:00",
        None,
        metadata,
        (),
        f"prompt for {name}\n".encode(),
        chat,
        agent_session,
        None,
        (),
        f"20260723120{suffix}",
    )


def _publish(
    sync_target: ProjectTarget,
    repo: Path,
    owner: AgentOwnerIdentity,
    runs: tuple[InventoryRun, ...],
) -> None:
    publish_agent_hood(
        sync_target,
        repo,
        "foo",
        identity=AgentIdentitySnapshot(owner),
        inventory=ProjectHoodInventory(owner, "proj", runs),
    )


def _commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _chat(repo: Path, owner: AgentOwnerIdentity, name: str) -> Path:
    return repo / "agents" / f"{owner.username}.{owner.machine_name}.{name}" / "chat.md"


def _manifest(repo: Path, owner: AgentOwnerIdentity) -> Path:
    return (
        repo
        / "users"
        / owner.username
        / "machines"
        / owner.machine_name
        / "manifest.json"
    )


def _readme(repo: Path, owner: AgentOwnerIdentity, name: str) -> Path:
    return (
        repo / "agents" / f"{owner.username}.{owner.machine_name}.{name}" / "README.md"
    )


def _plant_pending_object(repo: Path) -> str:
    digest = hashlib.sha256(PENDING_OBJECT).hexdigest()
    relative = str(sase_core_rs.artifact_object_relpath(digest))
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PENDING_OBJECT)
    return relative


def _prepare_stale_replay(tmp_path: Path) -> _ReplayFixture:
    remote, _seed, sidecar = setup_repo(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    sync_target = target(tmp_path, remote, sidecar)
    shared = (_run(owner, "foo", "01", chat=SHARED_CHAT),)
    _publish(sync_target, sidecar, owner, shared)
    _commit(sidecar, "shared hood")
    git(sidecar, "push", "origin", "HEAD")

    peer = tmp_path / "peer"
    git(tmp_path, "clone", str(remote), str(peer))
    git(peer, "config", "user.name", "Tests")
    git(peer, "config", "user.email", "tests@example.test")
    peer_primary = tmp_path / "peer-primary"
    peer_primary.mkdir()
    peer_target = ProjectTarget(
        "proj",
        "Project",
        peer_primary,
        (peer_primary.resolve(),),
        peer,
        str(remote),
    )
    _publish(
        peer_target,
        peer,
        owner,
        (
            *shared,
            _run(owner, "foo.remote", "remote", chat=REMOTE_CHAT),
        ),
    )
    _commit(peer, "remote unique owner content")
    git(peer, "push", "origin", "HEAD")

    _publish(
        sync_target,
        sidecar,
        owner,
        (
            *shared,
            _run(owner, "foo.local", "local", chat=LOCAL_CHAT),
            _run(
                owner,
                "foo.bar--code",
                "sess",
                chat=SESSION_CHAT,
                agent_session="foo.bar",
            ),
        ),
    )
    _readme(sidecar, owner, "foo").write_text(STALE_BROWSING, encoding="utf-8")
    manifest = json.loads(_manifest(sidecar, owner).read_text(encoding="utf-8"))
    manifest["hoods"]["foo"]["files"] = [
        "agents/alice.athena.foo/README.md",
        "agents/alice.athena.foo.retired/README.md",
    ]
    _manifest(sidecar, owner).write_text(json.dumps(manifest), encoding="utf-8")
    head = _commit(sidecar, "unpublished unique local content")
    object_relpath = _plant_pending_object(sidecar)
    git(sidecar, "fetch")
    return _ReplayFixture(
        remote,
        sidecar,
        sync_target,
        owner,
        tmp_path / "backup",
        head,
        object_relpath,
    )


def _recover(fixture: _ReplayFixture, *, apply: bool) -> object:
    return recover_stale_replay(
        expected_head=fixture.head,
        backup_dir=fixture.backup,
        target=fixture.target,
        apply=apply,
        owner=fixture.owner,
        git_runner=run_git,
        lock_timeout_seconds=2.0,
    )


def test_report_only_writes_a_verified_backup_without_resetting(
    tmp_path: Path,
) -> None:
    fixture = _prepare_stale_replay(tmp_path)
    before = git(fixture.sidecar, "rev-parse", "HEAD").stdout.strip()

    report = _recover(fixture, apply=False)

    assert report.error is None
    assert report.action == REPLAY_APPLY_ACTION_REPORT
    assert report.ahead == 1
    assert report.behind == 1
    assert git(fixture.sidecar, "rev-parse", "HEAD").stdout.strip() == before
    assert (fixture.backup / BUNDLE_NAME).is_file()
    assert (fixture.backup / CHECKSUMS_NAME).is_file()
    assert (fixture.backup / REVISIONS_NAME).is_file()
    revisions = json.loads(
        (fixture.backup / REVISIONS_NAME).read_text(encoding="utf-8")
    )
    checksums = json.loads(
        (fixture.backup / CHECKSUMS_NAME).read_text(encoding="utf-8")
    )
    assert revisions["head"] == fixture.head
    assert REVISIONS_NAME in checksums
    assert CHECKSUMS_NAME not in checksums
    assert PROGRESS_NAME not in checksums
    progress = json.loads((fixture.backup / PROGRESS_NAME).read_text(encoding="utf-8"))
    assert progress["stage"] == "verified"
    snapshot = (
        fixture.backup
        / PRESERVED_DIR
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "foo"
        / "snapshot.json"
    )
    assert snapshot.is_file()
    assert (fixture.backup / OBJECTS_DIR / fixture.object_relpath).is_file()
    assert any("foo.local" in path for path in report.owner_content_paths)


def test_apply_keeps_both_sides_unique_content_and_pending_objects(
    tmp_path: Path,
) -> None:
    fixture = _prepare_stale_replay(tmp_path)
    report = _recover(fixture, apply=False)
    assert report.error is None

    applied = _recover(fixture, apply=True)

    assert applied.error is None
    assert applied.action == REPLAY_APPLY_ACTION_APPLY
    assert applied.outcome is not None
    assert applied.outcome.committed and applied.outcome.pushed
    assert _chat(fixture.sidecar, fixture.owner, "foo.local").read_bytes() == LOCAL_CHAT
    assert (
        _chat(fixture.sidecar, fixture.owner, "foo.remote").read_bytes() == REMOTE_CHAT
    )
    assert (
        _chat(fixture.sidecar, fixture.owner, "foo.bar--code").read_bytes()
        == SESSION_CHAT
    )
    assert STALE_BROWSING not in _readme(
        fixture.sidecar, fixture.owner, "foo"
    ).read_text(encoding="utf-8")
    assert (fixture.sidecar / fixture.object_relpath).read_bytes() == PENDING_OBJECT
    assert (fixture.sidecar / agent_session_page_path("alice.athena.foo.bar")).is_file()
    manifests, snapshots, _diagnostics = load_validated_publication(fixture.sidecar)
    assert manifests
    hood = snapshots[("alice", "athena", "foo")]
    names = {run.global_name for run in hood.runs}
    assert "alice.athena.foo.local" in names
    assert "alice.athena.foo.remote" in names
    alice = next(item for item in manifests if item.owner.username == "alice")
    assert dict(alice.hoods)["foo"].files is None
    verify = tmp_path / "verify"
    git(tmp_path, "clone", str(fixture.remote), str(verify))
    load_validated_publication(verify)
    assert _chat(verify, fixture.owner, "foo.local").read_bytes() == LOCAL_CHAT
    assert _chat(verify, fixture.owner, "foo.remote").read_bytes() == REMOTE_CHAT
    assert (verify / fixture.object_relpath).read_bytes() == PENDING_OBJECT


def test_interrupted_apply_resumes_and_second_apply_is_already_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _prepare_stale_replay(tmp_path)
    _recover(fixture, apply=False)

    def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("interrupted export pass")

    with monkeypatch.context() as patched:
        patched.setattr(
            "sase.agents_sync.publication_replay_recovery._replay_export_pass",
            boom,
        )
        interrupted = _recover(fixture, apply=True)
        assert interrupted.error is not None
        assert "interrupted export pass" in interrupted.error
        progress = json.loads(
            (fixture.backup / PROGRESS_NAME).read_text(encoding="utf-8")
        )
        assert progress["stage"] == "replaying"
        assert not _chat(fixture.sidecar, fixture.owner, "foo.local").is_file()

    resumed = _recover(fixture, apply=True)
    assert resumed.error is None
    assert resumed.action == REPLAY_APPLY_ACTION_APPLY
    assert _chat(fixture.sidecar, fixture.owner, "foo.local").read_bytes() == LOCAL_CHAT
    assert (
        _chat(fixture.sidecar, fixture.owner, "foo.remote").read_bytes() == REMOTE_CHAT
    )

    again = _recover(fixture, apply=True)
    assert again.error is None
    assert again.already_complete
    assert again.action == REPLAY_APPLY_ACTION_ALREADY_COMPLETE


def test_apply_refuses_when_head_changes_after_report_only(tmp_path: Path) -> None:
    fixture = _prepare_stale_replay(tmp_path)
    report = _recover(fixture, apply=False)
    assert report.error is None
    git(fixture.sidecar, "commit", "--allow-empty", "-m", "head moved after report")

    refused = _recover(fixture, apply=True)

    assert refused.action == REPLAY_APPLY_ACTION_REFUSE
    assert refused.error is not None
    assert "HEAD changed" in refused.error
    assert (
        json.loads((fixture.backup / PROGRESS_NAME).read_text(encoding="utf-8"))[
            "stage"
        ]
        == "verified"
    )


def test_unreconcilable_same_run_bytes_refuse_before_reset(tmp_path: Path) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    sync_target = target(tmp_path, remote, sidecar)
    _publish(
        sync_target,
        sidecar,
        owner,
        (_run(owner, "foo", "01", chat=b"bbbb\n"),),
    )
    _commit(sidecar, "upstream chat")
    git(sidecar, "push", "origin", "HEAD")
    _publish(
        sync_target,
        sidecar,
        owner,
        (_run(owner, "foo", "01", chat=b"aaaaaaaaaa\n"),),
    )
    head = _commit(sidecar, "diverging unpublished chat")
    git(sidecar, "fetch")
    backup = tmp_path / "backup"
    before = git(sidecar, "rev-parse", "HEAD").stdout.strip()

    report = recover_stale_replay(
        expected_head=head,
        backup_dir=backup,
        target=sync_target,
        apply=True,
        owner=owner,
        git_runner=run_git,
        lock_timeout_seconds=2.0,
    )

    assert report.action == REPLAY_APPLY_ACTION_REFUSE
    assert report.refused_divergences
    assert git(sidecar, "rev-parse", "HEAD").stdout.strip() == before
    assert (backup / PROGRESS_NAME).is_file()


def test_recover_replay_cli_requires_backup_and_expected_head() -> None:
    tool = _load_tool()
    with pytest.raises(SystemExit):
        tool._parse_args([])
    args = tool._parse_args(
        ["-p", "bob-cli", "-H", "abc123", "-b", "/tmp/backup", "-a"]
    )
    assert args.project == "bob-cli"
    assert args.expected_head == "abc123"
    assert args.backup_dir == "/tmp/backup"
    assert args.apply is True


def test_recover_replay_cli_prints_json_report(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _load_tool()
    fake = SimpleNamespace(
        project_key="proj",
        action=REPLAY_APPLY_ACTION_REPORT,
        stage="verified",
        apply=False,
        already_complete=False,
        observed_head="a" * 40,
        expected_head="a" * 40,
        upstream="b" * 40,
        ahead=1,
        behind=2,
        error=None,
        browsing_paths=("README.md",),
        owner_content_paths=("agents/alice.athena.foo/chat.md",),
        archive_object_paths=(),
        unknown_paths=(),
        preserved_hoods=("foo",),
        refused_divergences=(),
        backup_dir="/tmp/backup",
        outcome=None,
    )
    monkeypatch.setattr(tool, "recover_stale_replay", lambda **_kwargs: fake)

    assert tool.main(["-p", "proj", "-H", "a" * 40, "-b", "/tmp/backup"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == REPLAY_APPLY_ACTION_REPORT
    assert payload["project"] == "proj"
    assert payload["ahead"] == 1
