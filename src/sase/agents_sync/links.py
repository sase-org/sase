"""Best-effort hosted links for globally identified agent commit tags."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from sase._git_remote import github_blob_url, parse_hosted_git_remote
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.targets import resolve_sync_targets
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    agent_link_target,
    globalize_owned_agent_name,
    normalize_owned_agent_name,
)
from sase.core.commit_footer_facade import LinkedCommitTagValue


def resolve_agent_commit_tag(
    agent_name: str,
    *,
    identity: AgentIdentitySnapshot | None = None,
    cwd: str | os.PathLike[str] | None = None,
    git_runner: GitRunner = run_git,
) -> str | LinkedCommitTagValue:
    """Return a global agent label, linked when its sidecar is hosted.

    Resolution is deliberately local-only. A disabled, not-created, missing,
    detached, or non-GitHub agents sidecar keeps the globally unique label but
    does not invent a destination.
    """

    snapshot = identity or AgentIdentitySnapshot.current()
    owner = snapshot.owner
    if owner is None:
        return agent_name
    local_name = normalize_owned_agent_name(agent_name, snapshot)
    global_name = globalize_owned_agent_name(local_name, snapshot)

    try:
        from sase.workflows.utils import get_project_from_workspace

        project = get_project_from_workspace()
    except Exception:
        return global_name
    if not project:
        return global_name

    try:
        selection = resolve_sync_targets((project,))
    except Exception:
        return global_name
    if len(selection.targets) != 1:
        return global_name
    target = selection.targets[0]
    current = Path(cwd or os.getcwd()).resolve(strict=False)
    if target.primary_roots and not any(
        current == root or current.is_relative_to(root) for root in target.primary_roots
    ):
        return global_name
    if not (target.sidecar_path / ".git").exists():
        return global_name
    branch = _sidecar_branch(target.sidecar_path, git_runner)
    if branch is None:
        return global_name

    link_target = agent_link_target(local_name, owner)
    destination = github_blob_url(
        target.remote_url,
        provider=hosted_provider(target.remote_url),
        branch=branch,
        path=link_target.path,
    )
    if destination is None:
        return global_name
    if link_target.anchor:
        destination = f"{destination}#{quote(link_target.anchor, safe='-._~')}"
    return LinkedCommitTagValue(global_name, destination)


def hosted_provider(remote_url: str) -> str | None:
    """Return authoritative hosted-provider metadata for a Git remote."""

    parsed = parse_hosted_git_remote(remote_url)
    if parsed is None:
        return None
    if parsed.host == "github.com":
        return "github"
    try:
        from sase._linked_repo_identity import configured_github_hosts
        from sase.config import load_merged_config

        if parsed.host in configured_github_hosts(load_merged_config()):
            return "github"
    except Exception:
        pass
    return None


def _sidecar_branch(repo: Path, git_runner: GitRunner) -> str | None:
    current = git_runner(
        repo,
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        op="agents_sync.link_branch",
    )
    if current.returncode == 0 and current.stdout.strip():
        return current.stdout.strip().removeprefix("refs/heads/")
    origin = git_runner(
        repo,
        ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
        op="agents_sync.link_origin_branch",
    )
    if origin.returncode != 0:
        return None
    value = origin.stdout.strip()
    if value.startswith("refs/remotes/"):
        value = value[len("refs/remotes/") :]
    return value.removeprefix("origin/") or None


__all__ = ["hosted_provider", "resolve_agent_commit_tag"]
