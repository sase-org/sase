"""Shared scan-option helpers for the agent artifact scan split.

The names here are public so the sibling ``agent_scan_*`` modules can
import them without touching a ``_``-prefixed symbol across files. Each
value keeps the behavior the former monolithic
:mod:`sase.core.agent_scan_facade` module used.
"""

from __future__ import annotations

from typing import Any

from sase.core.agent_artifact_index_lock import DEFAULT_READ_LOCK_TIMEOUT_SECONDS
from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire


def _default_clan_records_dir_str() -> str:
    """Return the default clan records directory as a string."""
    from sase.core.agent_clan_record import clan_records_dir

    return str(clan_records_dir())


def options_to_dict(options: AgentArtifactScanOptionsWire) -> dict[str, Any]:
    """Render scan options as the dict the Rust bindings consume."""
    return {
        "include_prompt_step_markers": options.include_prompt_step_markers,
        "include_raw_prompt_snippets": options.include_raw_prompt_snippets,
        "max_prompt_snippet_bytes": options.max_prompt_snippet_bytes,
        "only_workflow_dirs": list(options.only_workflow_dirs),
        "max_records": options.max_records,
        "newest_first": options.newest_first,
        "not_before_timestamp": options.not_before_timestamp,
        "include_done_markers": options.include_done_markers,
        "include_workflow_state": options.include_workflow_state,
        "include_waiting": options.include_waiting,
        "only_projects": list(options.only_projects),
        "include_project_states": list(options.include_project_states),
        "capacity_only": options.capacity_only,
        "clan_records_dir": (
            options.clan_records_dir
            if options.clan_records_dir is not None
            else _default_clan_records_dir_str()
        ),
    }


__all__ = [
    "DEFAULT_READ_LOCK_TIMEOUT_SECONDS",
    "options_to_dict",
]
