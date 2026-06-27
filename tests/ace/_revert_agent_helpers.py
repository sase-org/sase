"""Shared fixtures for revert-agent backend tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.ace.revert_agent import RevertTarget
from sase.ace.revert_agent_models import RevertRepo


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "sase@localhost")
    _git(repo, "config", "user.name", "sase")
    # A base commit so tagged commits are never the root commit.
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "base")


def _commit(repo: Path, message: str, files: dict[str, str]) -> str:
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _add_bare_origin(repo: Path, remote: Path) -> None:
    """Create a bare ``origin`` remote for *repo* (no initial push)."""
    remote.mkdir(parents=True, exist_ok=True)
    _git(remote, "init", "-q", "--bare", "-b", "main")
    _git(repo, "remote", "add", "origin", str(remote))


def _msg(subject: str, agent: str) -> str:
    """Build a commit message with legacy (unprefixed) footer tags."""
    return f"{subject}\n\nAGENT={agent}\nTYPE=sdd"


def _msg_prefixed(subject: str, agent: str) -> str:
    """Build a commit message with new ``SASE_``-prefixed footer tags."""
    return f"{subject}\n\nSASE_AGENT={agent}\nSASE_TYPE=sdd"


def _repo(repo: Path, label: str = "primary", *, primary: bool = False) -> RevertRepo:
    return RevertRepo(label=label, workspace_dir=str(repo), is_primary=primary)


def _target(
    repo: Path,
    name: str,
    *,
    family_base: str | None = None,
    artifacts: str | None = None,
) -> RevertTarget:
    return RevertTarget(
        agent_name=name,
        display_name=name,
        workspace_dir=str(repo),
        family_base=family_base,
        artifacts_dir=artifacts,
    )
