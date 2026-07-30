"""Best-effort hosted links for globally identified agent commit tags."""

from __future__ import annotations

import os
from pathlib import Path

from sase._git_remote import github_blob_url, parse_hosted_git_remote
from sase.agent_lanes import lane_page_path, lane_ref_for_agent
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.targets import resolve_sync_targets
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
)
from sase.core.commit_footer_facade import LinkedCommitTagValue
from sase.sdd.checkout_anchor import resolve_checkout_anchor
from sase.sdd.hosted_links import resolve_hosted_branch


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
    lane_ref = lane_ref_for_agent(agent_name, snapshot)
    if owner is None:
        return lane_ref.global_name

    current = Path(cwd or os.getcwd()).resolve(strict=False)
    anchor = resolve_checkout_anchor(current)
    project = anchor.project_name
    if not project:
        return lane_ref.global_name

    try:
        selection = resolve_sync_targets((project,))
    except Exception:
        return lane_ref.global_name
    if len(selection.targets) != 1:
        return lane_ref.global_name
    target = selection.targets[0]
    if target.primary_roots and not any(
        anchor.primary_root == root or anchor.primary_root.is_relative_to(root)
        for root in target.primary_roots
    ):
        return lane_ref.global_name
    if not (target.sidecar_path / ".git").exists():
        return lane_ref.global_name
    branch = resolve_hosted_branch(target.sidecar_path, git_runner=git_runner)
    if branch is None:
        return lane_ref.global_name

    destination = github_blob_url(
        target.remote_url,
        provider=hosted_provider(target.remote_url),
        branch=branch,
        path=lane_page_path(lane_ref, owner),
    )
    if destination is None:
        return lane_ref.global_name
    return LinkedCommitTagValue(lane_ref.global_name, destination)


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


__all__ = ["hosted_provider", "resolve_agent_commit_tag"]
