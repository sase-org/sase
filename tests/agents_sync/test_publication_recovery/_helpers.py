"""Shared builders for publication-recovery tests.

Split from ``tests.agents_sync.test_publication_recovery``; the names here are
public so the sibling test modules can import them without touching a
``_``-prefixed symbol across files.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.agents_sync import publication_recovery as recovery
from sase.agents_sync.publication_protection import PublicationProtectionScope

TOKEN = "SYNTHETIC-REMOTE-SECRET-7f3a9c2e"
BLOCKED_REL = "agents/local.athena.worker/chat.md"
SECOND_BLOCKED_REL = "agents/local.athena.worker/prompt.md"
CLEAN_REL = "agents/local.athena.other/chat.md"


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def setup_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare", "-b", "main")
    sidecar = tmp_path / "sidecar"
    git(tmp_path, "clone", str(remote), str(sidecar))
    git(sidecar, "config", "user.name", "Tests")
    git(sidecar, "config", "user.email", "tests@example.test")
    (sidecar / "README.md").write_text("# sidecar\n")
    git(sidecar, "add", "README.md")
    git(sidecar, "commit", "-m", "seed")
    git(sidecar, "push", "-u", "origin", "HEAD:main")
    return remote, sidecar


def commit(sidecar: Path, relpath: str, content: bytes, message: str) -> None:
    path = sidecar / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    git(sidecar, "add", relpath)
    git(sidecar, "commit", "-m", message)


def tip(sidecar: Path) -> str:
    return git(sidecar, "rev-parse", "HEAD").stdout.strip()


def upstream_tip(sidecar: Path) -> str:
    return git(sidecar, "rev-parse", "@{upstream}").stdout.strip()


def isolate_protection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    state = tmp_path / "state"
    projects_root = state / "projects"

    import sase.agents_sync._publication_protection_ledger as protection_ledger
    import sase.agents_sync._publication_protection_scan as protection_scan
    import sase.agents_sync.prompt_archive.protection as archive_protection

    monkeypatch.setattr(protection_scan, "sase_home", lambda: state)
    monkeypatch.setattr(protection_ledger, "sase_projects_dir", lambda: projects_root)
    monkeypatch.setattr(archive_protection, "sase_home", lambda: state)
    return state


def gh013_stderr(*paths: str, token: str = TOKEN) -> str:
    lines = [
        "remote: error: GH013: Repository rule violations found for refs/heads/main.",
        f"remote: error: {token}",
        "remote: error: The following lines were detected as secrets:",
    ]
    lines.extend(f"remote: error:   path: {path}" for path in paths)
    lines.append("remote: error: Push cannot contain secrets.")
    lines.append("To " + "https://example.test/remote.git")
    lines.append(" ! [remote rejected] main -> main (push declined due to secret)")
    lines.append("error: failed to push some refs to 'https://example.test/remote.git'")
    return "\n".join(lines) + "\n"


def scope_for(remote: Path) -> PublicationProtectionScope:
    return PublicationProtectionScope(
        project_key="proj", repository_identity=str(remote)
    )


def recover(
    sidecar: Path,
    runner,  # noqa: ANN001 - tests use duck-typed git runners.
    scope: PublicationProtectionScope,
    stderr: str,
    *,
    affected: tuple[tuple[str, str], ...] = (),
) -> recovery.PublicationPushRecovery:
    return recovery.recover_publication_push(
        sidecar,
        runner,
        project_key=scope.project_key,
        repository_identity=scope.repository_identity,
        returncode=1,
        stdout="",
        stderr=stderr,
        affected_requests=affected,
    )
