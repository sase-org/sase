"""Best-effort hosted page URLs for terminal agent rows."""

from __future__ import annotations

from pathlib import Path

from sase.agent.status_buckets import agent_status_bucket
from sase.sdd.hosted_links import hosted_link_resolver
from sase.sdd.store import resolve_sdd_store
from sase.workspace_provider.utils import parse_workspace_dir

from .agent import Agent
from ..widgets.prompt_panel._agent_commits import agent_commit_groups


def agent_publishes_page(agent: Agent) -> bool:
    """Return whether ``agent`` should have a published agents-sidecar page."""
    return bool(
        agent_status_bucket(agent) == "Done"
        and agent_commit_groups(agent)
        and agent.agent_name
        and not agent.is_clan_container
    )


def resolve_agent_page_url(agent: Agent) -> str | None:
    """Resolve ``agent``'s hosted sidecar page without raising."""
    if not agent_publishes_page(agent):
        return None
    agent_name = agent.agent_name
    if not agent.project_file or not agent_name:
        return None

    try:
        project_key = Path(agent.project_file).parent.name
        primary_root = parse_workspace_dir(agent.project_file) or agent.workspace_dir
        if not primary_root:
            return None
        store = resolve_sdd_store(primary_root, 1)
        resolver = hosted_link_resolver(
            store,
            project=project_key,
            primary_root=primary_root,
        )
        resolver.snapshot_agent_name_registry()
        return resolver.agent_url(agent_name)
    except Exception:
        return None


__all__ = ["agent_publishes_page", "resolve_agent_page_url"]
