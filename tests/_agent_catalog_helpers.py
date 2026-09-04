"""Shared helpers for building ``AgentCatalogRow`` fixtures in tests."""

from __future__ import annotations

from typing import Any

from sase.agents.catalog import AgentCatalogRow


def make_agent_catalog_row(name: str, **overrides: Any) -> AgentCatalogRow:
    """Create an ``AgentCatalogRow`` with every field set to a neutral default."""
    defaults: dict[str, Any] = {
        "name": name,
        "canonical_global_name": None,
        "kind": ("agent",),
        "project": None,
        "state": None,
        "family": None,
        "role": None,
        "clan": None,
        "tribe": None,
        "workflow": None,
        "parent_timestamp": None,
        "raw_suffix": None,
        "artifacts_dir": None,
        "bundle_path": None,
        "model": None,
        "llm_provider": None,
        "status": None,
        "hidden": False,
        "started_at": None,
        "finished_at": None,
        "retry_attempt": None,
        "retry_of_timestamp": None,
        "retried_as_timestamp": None,
        "retry_chain_root_timestamp": None,
        "patch": None,
        "dismissed": False,
        "revivable": False,
        "historically_viewable": False,
        "durably_revivable": False,
        "restartable": False,
        "missing_requirements": (),
        "attention": False,
        "retry": False,
        "has_collision_history": False,
        "from_artifact_index": False,
        "from_dismissed_archive": False,
    }
    defaults.update(overrides)
    return AgentCatalogRow(**defaults)
