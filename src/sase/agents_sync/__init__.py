"""Owner-sharded agent-hood synchronization through hidden agents sidecars."""

from __future__ import annotations

from functools import partial

from sase._lazy_exports import LazyExportMap, lazy_dir, lazy_getattr

_EXPORTS: LazyExportMap = {
    "get_agents_sync_status": ("sase.agents_sync.status", "get_agents_sync_status"),
    "publish_agent_hood": ("sase.agents_sync.publication", "publish_agent_hood"),
    "reconcile_agent_hoods": (
        "sase.agents_sync.publication",
        "reconcile_agent_hoods",
    ),
    "sync_agents": ("sase.agents_sync.git_sync", "sync_agents"),
}

__all__ = [
    "get_agents_sync_status",
    "publish_agent_hood",
    "reconcile_agent_hoods",
    "sync_agents",
]


__getattr__ = partial(lazy_getattr, __name__, globals(), _EXPORTS)
__dir__ = partial(lazy_dir, globals(), _EXPORTS)
