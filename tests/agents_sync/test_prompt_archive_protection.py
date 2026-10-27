"""Prompt-archive publication protection: withhold unsafe text, keep clean bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import sase_core_rs

from sase.agents_sync import git_sync
from sase.agents_sync import publication_protection as protection
from sase.agents_sync.git import run_git
from sase.agents_sync.prompt_archive.archive_objects import ARCHIVE_OBJECT_ROOT
from sase.agents_sync.prompt_archive.git_ops import publish_pending_archive_objects
from sase.agents_sync.prompt_archive.protection import (
    PRIVATE_RECOVERY_DIRECTORY,
    PROMPT_PROTECTION_BLOCKED,
    preserve_private_publication_object,
    protection_scope_for_target,
)
from sase.agents_sync.prompt_archive.publish import publish_prompt_archive
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync._prompt_archive_helpers import (
    HostedLinks,
    make_record,
    write_manifest,
)
from tests.agents_sync.commit_publication_fixtures import git, setup_target
from tests.agents_sync.git_sync_fixtures import (
    patch_payload_pass,
    setup_repo,
    target as make_sync_target,
)

MARKER = b"SYNTHETIC-PROMPT-SECRET-1oh"


def _install_marker_scanner(monkeypatch: pytest.MonkeyPatch) -> None:
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
                return {
                    "outcome": "clean",
                    "hit": None,
                    "bytes_scanned": len(data),
                    "rules_version": 1,
                }

            return scan
        return real_require(name)

    monkeypatch.setattr(rust, "require_rust_binding", require_binding)


def _payload_blobs(repo: Path) -> dict[str, bytes]:
    return {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }


def _publish_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
):
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, remote = setup_target(tmp_path)
    git(target.sidecar_path, "config", "user.name", "Tests")
    git(target.sidecar_path, "config", "user.email", "tests@example.test")
    artifacts_dir = tmp_path / "runs/20260801130000"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"workspace_dir": str(target.primary_checkout)})
    )
    (artifacts_dir / "raw_xprompt.md").write_text(prompt)
    from sase.agents_sync.prompt_archive import publish as archive_publish
    from sase.agents_sync.models import TargetSelection

    monkeypatch.setattr(
        archive_publish,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        archive_publish,
        "require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        archive_publish, "_hosted_resolver", lambda *_args: HostedLinks()
    )
    monkeypatch.setattr("sase.file_references.format_with_prettier", lambda text: text)
    return target, remote, artifacts_dir


def test_blocked_raw_prompt_is_not_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    target, remote, artifacts_dir = _publish_env(
        tmp_path, monkeypatch, f"do not leak {MARKER.decode()}\n"
    )
    referenced: list[object] = []
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.publish.enqueue_referenced_by_request",
        referenced.append,
    )

    outcome = publish_prompt_archive(
        "worker",
        "a" * 40,
        project="Project",
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
    )

    assert not outcome.published
    assert outcome.protection_status == "blocked"
    assert outcome.skip_reason == PROMPT_PROTECTION_BLOCKED
    assert referenced == []
    verify = tmp_path / "verify-blocked-prompt"
    git(tmp_path, "clone", str(remote), str(verify))
    blobs = _payload_blobs(verify)
    assert not any(MARKER in content for content in blobs.values())
    assert not (verify / "prompts").exists()
    digest = hashlib.sha256(f"do not leak {MARKER.decode()}\n".encode()).hexdigest()
    assert not protection.publication_content_retry_allowed(
        "proj",
        repository_identity=target.remote_url,
        relative_destination="prompts/202608/alice.athena.worker.md",
        sha256=digest,
    )


def test_blocked_text_object_is_withheld_and_clean_sibling_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    target, remote, artifacts_dir = _publish_env(
        tmp_path, monkeypatch, "Use @~/secret.txt and @~/ok.bin.\n"
    )
    secret = b"token " + MARKER + b"\n"
    binary = b"\x00\xff binary sibling"
    secret_digest = hashlib.sha256(secret).hexdigest()
    binary_digest = hashlib.sha256(binary).hexdigest()
    secret_name = sase_core_rs.prompt_artifact_pool_filename(
        secret_digest, "secret.txt"
    )
    binary_name = sase_core_rs.prompt_artifact_pool_filename(binary_digest, "ok.bin")
    pool = target.primary_checkout / ".sase/artifacts/pool"
    pool.mkdir(parents=True)
    (pool / secret_name).write_bytes(secret)
    (pool / binary_name).write_bytes(binary)
    write_manifest(
        target.primary_checkout,
        [
            make_record(
                artifacts_dir=artifacts_dir,
                raw_ref="@~/secret.txt",
                label="secret.txt",
                sha256=secret_digest,
                pool_relpath=f"pool/{secret_name}",
            ),
            make_record(
                artifacts_dir=artifacts_dir,
                raw_ref="@~/ok.bin",
                label="ok.bin",
                sha256=binary_digest,
                pool_relpath=f"pool/{binary_name}",
            ),
        ],
    )

    outcome = publish_prompt_archive(
        "worker",
        "a" * 40,
        project="Project",
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
    )

    assert outcome.published and outcome.error is None
    verify = tmp_path / "verify-object-sibling"
    git(tmp_path, "clone", str(remote), str(verify))
    blobs = _payload_blobs(verify)
    assert not any(MARKER in content for content in blobs.values())
    secret_rel = sase_core_rs.artifact_object_relpath(secret_digest)
    binary_rel = sase_core_rs.artifact_object_relpath(binary_digest)
    assert secret_rel not in blobs
    assert blobs[binary_rel] == binary
    prompt = (verify / "prompts/202608/alice.athena.worker.md").read_text()
    assert "../../files/objects/" in prompt
    assert secret_digest not in prompt
    assert binary_digest in prompt


def test_pending_hash_valid_secret_object_is_preserved_not_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    _remote, _seed, sidecar = setup_repo(tmp_path)
    content = b"pending " + MARKER + b"\n"
    digest = hashlib.sha256(content).hexdigest()
    relpath = sase_core_rs.artifact_object_relpath(digest)
    path = sidecar / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    from sase.agents_sync.models import ProjectTarget

    target = ProjectTarget(
        "proj",
        "Project",
        tmp_path / "primary",
        (tmp_path / "primary",),
        sidecar,
        str(_remote),
    )
    result = publish_pending_archive_objects(
        sidecar, run_git, protection_scope=protection_scope_for_target(target)
    )

    assert result is False
    tracked = git(sidecar, "ls-files", "--", ARCHIVE_OBJECT_ROOT).stdout.split()
    assert tracked == []
    assert path.read_bytes() == content
    recovered = (
        tmp_path
        / "state"
        / "private"
        / PRIVATE_RECOVERY_DIRECTORY
        / "proj"
        / digest[:2]
        / digest
    )
    assert recovered.read_bytes() == content
    assert MARKER.decode() not in (
        tmp_path
        / "state"
        / "projects"
        / "proj"
        / protection.AGENT_PUBLICATION_PROTECTION_FILENAME
    ).read_text(encoding="utf-8")


def test_private_preserve_failure_leaves_source_and_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    _remote, _seed, sidecar = setup_repo(tmp_path)
    content = b"only copy " + MARKER + b"\n"
    digest = hashlib.sha256(content).hexdigest()
    relpath = sase_core_rs.artifact_object_relpath(digest)
    path = sidecar / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    def boom(**_kwargs: object) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.protection.preserve_private_publication_object",
        boom,
    )
    from sase.agents_sync.models import ProjectTarget

    target = ProjectTarget(
        "proj",
        "Project",
        tmp_path / "primary",
        (tmp_path / "primary",),
        sidecar,
        str(_remote),
    )
    result = publish_pending_archive_objects(
        sidecar, run_git, protection_scope=protection_scope_for_target(target)
    )

    assert isinstance(result, str)
    assert "could not preserve" in result
    assert path.read_bytes() == content
    assert git(sidecar, "ls-files", "--", ARCHIVE_OBJECT_ROOT).stdout.split() == []


def test_retry_does_not_regenerate_blocked_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    target, remote, artifacts_dir = _publish_env(
        tmp_path, monkeypatch, f"again {MARKER.decode()}\n"
    )
    first = publish_prompt_archive(
        "worker",
        "a" * 40,
        project="Project",
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
    )
    second = publish_prompt_archive(
        "worker",
        "a" * 40,
        project="Project",
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
    )

    assert first.protection_status == "blocked"
    assert second.protection_status == "blocked"
    verify = tmp_path / "verify-retry"
    git(tmp_path, "clone", str(remote), str(verify))
    assert not any(MARKER in content for content in _payload_blobs(verify).values())


def test_full_sync_early_pending_secret_object_is_not_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_marker_scanner(monkeypatch)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    remote, _seed, sidecar = setup_repo(tmp_path)
    content = b"sync pending " + MARKER + b"\n"
    digest = hashlib.sha256(content).hexdigest()
    relpath = sase_core_rs.artifact_object_relpath(digest)
    path = sidecar / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    patch_payload_pass(monkeypatch)
    outcome = git_sync._sync_project(
        make_sync_target(tmp_path, remote, sidecar),
        "athena",
        git_runner=run_git,
    )

    assert outcome.error is None
    assert git(sidecar, "ls-files", "--", ARCHIVE_OBJECT_ROOT).stdout.split() == []
    assert path.read_bytes() == content
    recovered = (
        tmp_path
        / "state"
        / "private"
        / PRIVATE_RECOVERY_DIRECTORY
        / "proj"
        / digest[:2]
        / digest
    )
    assert recovered.read_bytes() == content
    verify = tmp_path / "verify-sync-pending"
    git(tmp_path, "clone", str(remote), str(verify))
    assert not any(
        MARKER in blob.read_bytes()
        for blob in verify.rglob("*")
        if blob.is_file() and ".git" not in blob.parts
    )


def test_preserve_is_idempotent_for_the_same_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    source = tmp_path / "object"
    data = b"sole copy bytes"
    digest = hashlib.sha256(data).hexdigest()
    source.write_bytes(data)
    first = preserve_private_publication_object(
        project_key="proj", sha256=digest, source=source
    )
    second = preserve_private_publication_object(
        project_key="proj", sha256=digest, source=source
    )
    assert first == second
    assert first.read_bytes() == data
