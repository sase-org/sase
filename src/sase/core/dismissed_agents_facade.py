"""UI-free import surface for dismissed-agent archive operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.core.agent_types import AgentIdentity


def dismissed_bundles_dir() -> Path:
    from sase.ace import dismissed_agents

    return dismissed_agents.dismissed_bundles_dir()


def dismissed_agent_groups_dir() -> Path:
    from sase.ace import dismissed_agents

    return dismissed_agents.dismissed_agent_groups_dir()


def load_dismissed_agents() -> set[AgentIdentity]:
    from sase.ace import dismissed_agents

    return dismissed_agents.load_dismissed_agents()


def persist_dismissed_agents(dismissed: set[AgentIdentity]) -> bool:
    from sase.ace.dismissed_agents import save_dismissed_agents as impl

    return impl(dismissed)


def rebuild_dismissed_bundle_index() -> tuple[int, int]:
    from sase.ace import dismissed_agents

    return dismissed_agents.rebuild_dismissed_bundle_index()


def load_dismissed_bundle_summaries(
    *,
    suffixes: set[str] | None = None,
    cl_name: str | None = None,
    project_name: str | None = None,
    top_level_only: bool = False,
    limit: int | None = None,
    offset: int | None = None,
) -> list[Any]:
    from sase.ace import dismissed_agents

    return dismissed_agents.load_dismissed_bundle_summaries(
        suffixes=suffixes,
        cl_name=cl_name,
        project_name=project_name,
        top_level_only=top_level_only,
        limit=limit,
        offset=offset,
    )


def iter_dismissed_bundle_paths(
    bundles_dir: Path, pattern: str = "*.json"
) -> list[Path]:
    from sase.ace.dismissed_agents_paths import iter_bundle_paths

    return iter_bundle_paths(bundles_dir, pattern)


def archive_index_exists(root: Path) -> bool:
    from sase.ace.dismissed_bundle_index import archive_index_exists as impl

    return impl(root)


def upsert_bundle_summary(root: Path, path: Path, bundle: dict[str, Any]) -> bool:
    from sase.ace.dismissed_bundle_index import upsert_bundle_summary as impl

    return impl(root, path, bundle)


__all__ = [
    "archive_index_exists",
    "dismissed_agent_groups_dir",
    "dismissed_bundles_dir",
    "iter_dismissed_bundle_paths",
    "load_dismissed_agents",
    "load_dismissed_bundle_summaries",
    "persist_dismissed_agents",
    "rebuild_dismissed_bundle_index",
    "upsert_bundle_summary",
]
