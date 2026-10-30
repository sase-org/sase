"""Transcript publication protection: withhold unsafe bytes, keep clean ones."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import (
    _publication_protection_ledger as protection_ledger,
    _publication_protection_scan as protection_scan,
    publication_protection as protection,
)
from sase.agents_sync._git_sync_ops_payload import _verify_agents_payload_protection
from sase.agents_sync.git import run_git
from sase.agents_sync.git_sync_ops import commit_agents_payload_if_dirty
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.publication import publish_agent_hood, reconcile_agent_hoods
from sase.agents_sync.publication_planning import plan_hoods, plan_targeted_hoods
from sase.agents_sync.publication_snapshot import HoodWithheldError, build_hood_snapshot
from sase.agents_sync.publication_validation import snapshot_path
from sase.agents_sync.v2_io import owner_manifest_path, read_hood_snapshot
from sase.agents_sync.v2_models import V2ProjectIdentity
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.publication_fixtures import (
    _assert_summary_anchors_resolve,
    _identity,
    _run,
    _target,
)

MARKER = b"SYNTHETIC-TRANSCRIPT-SECRET-1oh"
UNVERIFIED_MARKER = b"SYNTHETIC-TRANSCRIPT-UNVERIFIED-1oh"
SCANNER_UNAVAILABLE = "SYNTHETIC-SCANNER-UNAVAILABLE-1oh"


def _install_marker_scanner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake only the scanner binding; keep the real Rust policy core."""

    import sase.core.rust as rust

    real_require = rust.require_rust_binding

    def require_binding(name: str):
        if name == "attachment_scan_file":

            def scan(
                path: str,
                max_bytes: int,
                _env: dict[str, str],
                _home: str,
                _sase_home: str,
            ) -> dict[str, object]:
                data = Path(path).read_bytes()
                if MARKER in data:
                    return {
                        "outcome": "hit",
                        "hit": {
                            "kind": "credential_pattern",
                            "rule_id": "synthetic-marker",
                            "line": 1,
                            "rules_version": 1,
                        },
                        "bytes_scanned": len(data),
                        "rules_version": 1,
                    }
                if UNVERIFIED_MARKER in data:
                    raise RuntimeError(SCANNER_UNAVAILABLE)
                return {
                    "outcome": "clean",
                    "hit": None,
                    "bytes_scanned": len(data),
                    "rules_version": 1,
                }

            return scan
        return real_require(name)

    monkeypatch.setattr(rust, "require_rust_binding", require_binding)


def _isolate_protection_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    projects_root = tmp_path / "protection-home" / "projects"
    monkeypatch.setattr(
        protection_scan, "sase_home", lambda: tmp_path / "protection-home"
    )
    monkeypatch.setattr(protection_ledger, "sase_projects_dir", lambda: projects_root)
    return projects_root


def _inventory_with_blocked_prompt(owner: AgentOwnerIdentity) -> ProjectHoodInventory:
    clean = _run("foo.clean", "21", chat=b"clean chat\n")
    blocked = replace(
        _run("foo.blocked", "22", chat=b"clean chat\n"),
        prompt_bytes=b"prompt with " + MARKER + b" inside\n",
    )
    return ProjectHoodInventory(owner, "proj", (clean, blocked))


def _payload_blobs(repo: Path) -> dict[str, bytes]:
    return {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file()
    }


def test_blocked_prompt_withheld_but_clean_sibling_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    projects_root = _isolate_protection_state(tmp_path, monkeypatch)
    owner = AgentOwnerIdentity("alice", "athena")
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory_with_blocked_prompt(owner)

    counts = publish_agent_hood(
        target,
        repo,
        "foo.clean",
        identity=_identity(),
        inventory=inventory,
    )

    snapshot = read_hood_snapshot(
        repo
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "foo"
        / "snapshot.json"
    )
    assert {run.local_name for run in snapshot.runs} == {"foo.blocked", "foo.clean"}
    by_name = {run.local_name: run for run in snapshot.runs}
    assert dict(by_name["foo.blocked"].files).get("prompt") is None
    assert dict(by_name["foo.clean"].files).get("prompt") is not None
    assert any("withheld" in item for item in counts.diagnostics)
    blobs = _payload_blobs(repo)
    assert not any(MARKER in content for content in blobs.values())
    assert "agents/alice.athena.foo.clean/prompt.md" in blobs
    assert "agents/alice.athena.foo.blocked/prompt.md" not in blobs
    blocked_page = (
        repo / "agents" / "alice.athena.foo.blocked" / "README.md"
    ).read_text()
    assert "prompt.md" not in blocked_page
    agent_page = (repo / "agents" / "alice.athena.foo.clean" / "README.md").read_text()
    _assert_summary_anchors_resolve(agent_page)
    _assert_summary_anchors_resolve(blocked_page)

    ledger_path = (
        projects_root / "proj" / protection.AGENT_PUBLICATION_PROTECTION_FILENAME
    )
    persisted = ledger_path.read_text(encoding="utf-8")
    assert MARKER.decode() not in persisted
    assert "synthetic-marker" in persisted
    digest = hashlib.sha256(b"prompt with " + MARKER + b" inside\n").hexdigest()
    assert not protection.publication_content_retry_allowed(
        "proj",
        repository_identity="unused",
        relative_destination="agents/alice.athena.foo.blocked/prompt.md",
        sha256=digest,
    )

    # A repeat drain with identical bytes is stable and stays clean.
    second = publish_agent_hood(
        target,
        repo,
        "foo.clean",
        identity=_identity(),
        inventory=inventory,
    )
    assert second.hoods_unchanged == 1
    assert _payload_blobs(repo) == blobs


def test_blocked_output_variable_withholds_whole_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    _isolate_protection_state(tmp_path, monkeypatch)
    owner = AgentOwnerIdentity("alice", "athena")
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    clean = _run("foo.clean", "21")
    tainted = replace(
        _run("foo.tainted", "22"),
        metadata=(("model", "gpt"), ("output_variables", {"note": MARKER.decode()})),
    )
    inventory = ProjectHoodInventory(owner, "proj", (clean, tainted))

    counts = publish_agent_hood(
        target,
        repo,
        "foo.clean",
        identity=_identity(),
        inventory=inventory,
    )

    snapshot = read_hood_snapshot(
        repo
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "foo"
        / "snapshot.json"
    )
    assert {run.local_name for run in snapshot.runs} == {"foo.clean"}
    blobs = _payload_blobs(repo)
    assert not any(MARKER in content for content in blobs.values())
    assert not (repo / "agents" / "alice.athena.foo.tainted").exists()
    assert ("alice.athena.foo.tainted", "blocked") in counts.withheld_runs
    assert counts.withheld_hoods == ()


def test_blocked_prior_bytes_never_merge_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    _isolate_protection_state(tmp_path, monkeypatch)
    owner = AgentOwnerIdentity("alice", "athena")
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    long_chat = b"clean chat padding " * 64 + b"\n"
    first = replace(_run("foo.merge", "23"), chat_bytes=long_chat)
    inventory = ProjectHoodInventory(owner, "proj", (first,))
    publish_agent_hood(
        target, repo, "foo.merge", identity=_identity(), inventory=inventory
    )
    assert (repo / "agents" / "alice.athena.foo.merge" / "chat.md").read_bytes() == (
        long_chat
    )

    short_blocked = replace(
        _run("foo.merge", "23"), chat_bytes=b"short " + MARKER + b"\n"
    )
    refreshed = ProjectHoodInventory(owner, "proj", (short_blocked,))
    publish_agent_hood(
        target, repo, "foo.merge", identity=_identity(), inventory=refreshed
    )

    blobs = _payload_blobs(repo)
    assert not any(MARKER in content for content in blobs.values())
    snapshot = read_hood_snapshot(
        repo
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "foo"
        / "snapshot.json"
    )
    (record,) = snapshot.runs
    assert dict(record.files).get("chat") is None


def test_clean_prior_bytes_still_merge_for_shorter_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    _isolate_protection_state(tmp_path, monkeypatch)
    owner = AgentOwnerIdentity("alice", "athena")
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    long_chat = b"clean chat padding " * 64 + b"\n"
    first = replace(_run("foo.merge", "23"), chat_bytes=long_chat)
    publish_agent_hood(
        target,
        repo,
        "foo.merge",
        identity=_identity(),
        inventory=ProjectHoodInventory(owner, "proj", (first,)),
    )

    short_clean = replace(_run("foo.merge", "23"), chat_bytes=b"short\n")
    publish_agent_hood(
        target,
        repo,
        "foo.merge",
        identity=_identity(),
        inventory=ProjectHoodInventory(owner, "proj", (short_clean,)),
    )

    assert (repo / "agents" / "alice.athena.foo.merge" / "chat.md").read_bytes() == (
        long_chat
    )


def test_full_sync_withholds_blocked_run_and_keeps_other_hood(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    _isolate_protection_state(tmp_path, monkeypatch)
    owner = AgentOwnerIdentity("alice", "athena")
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    clean = _run("foo.clean", "21", commit=True)
    blocked = replace(
        _run("foo.blocked", "22", commit=True),
        prompt_bytes=b"prompt with " + MARKER + b" inside\n",
    )
    other = _run("zap.solo", "09", commit=True)
    inventory = ProjectHoodInventory(owner, "proj", (clean, blocked, other))

    counts = reconcile_agent_hoods(
        target, repo, identity=_identity(), inventory=inventory
    )

    assert counts.hoods_published == 2
    assert any("withheld" in item for item in counts.diagnostics)
    blobs = _payload_blobs(repo)
    assert not any(MARKER in content for content in blobs.values())
    assert (repo / "agents" / "alice.athena.zap.solo" / "prompt.md").exists()
    assert (repo / "agents" / "alice.athena.foo.clean" / "prompt.md").exists()


def _init_payload_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@localhost"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "agents").mkdir()
    (path / "agents" / "chat.md").write_bytes(b"clean chat\n")
    (path / "schema.json").write_bytes(b"{}\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)
    return path


def test_pre_stage_verification_blocks_dirty_secret_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    _isolate_protection_state(tmp_path, monkeypatch)
    repo = _init_payload_repo(tmp_path / "sidecar")
    (repo / "agents" / "chat.md").write_bytes(b"dirty " + MARKER + b"\n")

    error = _verify_agents_payload_protection(repo, run_git)

    assert error is not None and "withheld" in error
    owner = AgentOwnerIdentity("alice", "athena")
    assert isinstance(commit_agents_payload_if_dirty(repo, owner, run_git), str)
    assert (
        subprocess.run(
            ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True
        ).stdout.count("\n")
        == 1
    )


def test_pre_stage_verification_detects_digest_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    _isolate_protection_state(tmp_path, monkeypatch)
    repo = _init_payload_repo(tmp_path / "sidecar")

    real_scan = protection.scan_publication_bytes

    def mismatched_digest(data: bytes, *, max_bytes: int, env=None):
        verdict = real_scan(data, max_bytes=max_bytes, env=env)
        return protection.PublicationBytesVerdict(
            sha256="0" * 64,
            byte_count=verdict.byte_count,
            disposition=verdict.disposition,
        )

    monkeypatch.setattr(protection, "scan_publication_bytes", mismatched_digest)
    (repo / "schema.json").write_bytes(b'{"dirty": true}\n')

    error = _verify_agents_payload_protection(repo, run_git)

    assert error is not None and "changed between scanning and writing" in error


def test_pre_stage_verification_passes_clean_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    _isolate_protection_state(tmp_path, monkeypatch)
    repo = _init_payload_repo(tmp_path / "sidecar")

    assert _verify_agents_payload_protection(repo, run_git) is None
    owner = AgentOwnerIdentity("alice", "athena")
    assert commit_agents_payload_if_dirty(repo, owner, run_git) is False


def _three_hood_runs(*, tainted: bool) -> tuple:
    keep = _run("keep.one", "21", commit=True)
    blocked = _run(
        "block.one",
        "22",
        commit=True,
        output_variables={"note": MARKER.decode()} if tainted else None,
    )
    unverified = _run(
        "probe.one",
        "23",
        commit=True,
        output_variables={"note": UNVERIFIED_MARKER.decode()} if tainted else None,
    )
    return keep, blocked, unverified


def _assert_value_free(items: tuple[str, ...]) -> None:
    blob = "\n".join(items)
    assert MARKER.decode() not in blob
    assert UNVERIFIED_MARKER.decode() not in blob
    assert SCANNER_UNAVAILABLE not in blob


def test_hood_withheld_error_is_not_a_format_error() -> None:
    assert not issubclass(HoodWithheldError, AgentsSyncFormatError)


def test_empty_inventory_still_raises_no_publishable_runs(tmp_path: Path) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = ProjectHoodInventory(owner, "proj", ())
    with pytest.raises(AgentsSyncFormatError, match="has no publishable runs"):
        build_hood_snapshot(
            repo,
            V2ProjectIdentity("proj", "Project"),
            owner,
            "empty",
            inventory,
            None,
        )
    with pytest.raises(AgentsSyncFormatError, match="has no publishable runs"):
        publish_agent_hood(
            target,
            repo,
            "empty.none",
            identity=_identity(),
            inventory=inventory,
        )


def test_full_sync_skips_fully_withheld_hoods_and_keeps_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    _isolate_protection_state(tmp_path, monkeypatch)
    owner = AgentOwnerIdentity("alice", "athena")
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    clean_inventory = ProjectHoodInventory(
        owner, "proj", _three_hood_runs(tainted=False)
    )
    first = reconcile_agent_hoods(
        target, repo, identity=_identity(), inventory=clean_inventory
    )
    assert first.hoods_published == 3
    snapshot_before = {
        hood: (repo / snapshot_path(owner, hood)).read_bytes()
        for hood in ("keep", "block", "probe")
    }
    manifest_before = (repo / owner_manifest_path(owner)).read_bytes()

    tainted = ProjectHoodInventory(owner, "proj", _three_hood_runs(tainted=True))
    counts = reconcile_agent_hoods(
        target, repo, identity=_identity(), inventory=tainted
    )

    assert counts.hoods_published == 0
    assert counts.hoods_refreshed == 0
    assert counts.hoods_unchanged == 1
    assert ("alice.athena.block.one", "blocked") in counts.withheld_runs
    assert ("alice.athena.probe.one", "unverified") in counts.withheld_runs
    assert ("block", "blocked") in counts.withheld_hoods
    assert ("probe", "unverified") in counts.withheld_hoods
    assert "keep" not in {hood for hood, _reason in counts.withheld_hoods}
    assert "withheld hood 'block': blocked" in counts.diagnostics
    assert "withheld hood 'probe': unverified" in counts.diagnostics
    _assert_value_free(counts.diagnostics)
    assert (repo / snapshot_path(owner, "block")).read_bytes() == snapshot_before[
        "block"
    ]
    assert (repo / snapshot_path(owner, "probe")).read_bytes() == snapshot_before[
        "probe"
    ]
    assert (repo / owner_manifest_path(owner)).read_bytes() == manifest_before
    blobs = _payload_blobs(repo)
    assert not any(MARKER in content for content in blobs.values())
    assert not any(UNVERIFIED_MARKER in content for content in blobs.values())
    assert SCANNER_UNAVAILABLE.encode() not in b"".join(blobs.values())
    assert (repo / "agents" / "alice.athena.keep.one" / "prompt.md").exists()
    assert (repo / "agents" / "alice.athena.block.one" / "prompt.md").exists()
    assert (repo / "agents" / "alice.athena.probe.one" / "prompt.md").exists()


def test_targeted_planning_skips_fully_withheld_hoods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    _isolate_protection_state(tmp_path, monkeypatch)
    owner = AgentOwnerIdentity("alice", "athena")
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    clean_inventory = ProjectHoodInventory(
        owner, "proj", _three_hood_runs(tainted=False)
    )
    reconcile_agent_hoods(target, repo, identity=_identity(), inventory=clean_inventory)
    snapshot_before = {
        hood: (repo / snapshot_path(owner, hood)).read_bytes()
        for hood in ("keep", "block", "probe")
    }
    manifest_before = (repo / owner_manifest_path(owner)).read_bytes()
    tainted = ProjectHoodInventory(owner, "proj", _three_hood_runs(tainted=True))
    payload, counts = plan_targeted_hoods(
        target, repo, tainted, ("keep", "block", "probe"), owner
    )
    assert snapshot_path(owner, "block") not in payload
    assert snapshot_path(owner, "probe") not in payload
    assert snapshot_path(owner, "keep") in payload
    assert counts.hoods_unchanged == 1
    assert ("block", "blocked") in counts.withheld_hoods
    assert ("probe", "unverified") in counts.withheld_hoods
    _assert_value_free(counts.diagnostics)
    full_payload, full_counts = plan_hoods(
        target, repo, tainted, ("keep", "block", "probe"), owner
    )
    assert snapshot_path(owner, "block") not in full_payload
    assert ("block", "blocked") in full_counts.withheld_hoods
    assert (repo / snapshot_path(owner, "block")).read_bytes() == snapshot_before[
        "block"
    ]
    assert (repo / snapshot_path(owner, "probe")).read_bytes() == snapshot_before[
        "probe"
    ]
    assert (repo / owner_manifest_path(owner)).read_bytes() == manifest_before
    assert not any(MARKER in content for content in payload.values())
    assert not any(UNVERIFIED_MARKER in content for content in payload.values())
