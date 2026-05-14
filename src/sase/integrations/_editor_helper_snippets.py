"""Editor helper bridge operation for SASE snippet catalogs."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.config import load_merged_config
from sase.daemon.client import LocalDaemonTransportError
from sase.daemon.read_facade import read_or_fallback
from sase.xprompt.snippet_bridge import (
    XPromptSnippetEntry,
    get_xprompt_snippet_entries,
    is_valid_snippet_trigger,
)

from ._mobile_helper_common import (
    GATEWAY_WIRE_SCHEMA_VERSION,
    helper_result,
    optional_bool,
    optional_string,
)


def snippet_catalog_response(request: dict[str, Any]) -> dict[str, Any]:
    """Return the merged ACE snippet registry for editor clients."""
    project = optional_string(request.get("project"), "project")
    no_daemon = optional_bool(request.get("no_daemon"), "no_daemon")
    if project is None:
        return _direct_snippet_catalog_response(project=project)
    result = read_or_fallback(
        "snippet_catalog",
        args=SimpleNamespace(no_daemon=no_daemon),
        direct_loader=lambda: _direct_snippet_catalog_response(project=project),
        daemon_loader=lambda daemon: _daemon_snippet_catalog_response(
            daemon, project=project
        ),
    )
    return result.value


def _direct_snippet_catalog_response(*, project: str | None) -> dict[str, Any]:
    entries_by_trigger = _xprompt_entries_by_trigger(project=project)

    for trigger, template in _user_snippets().items():
        if not is_valid_snippet_trigger(trigger):
            continue
        entries_by_trigger[trigger] = {
            "trigger": trigger,
            "template": template,
            "source": "user_config",
            "xprompt_name": None,
            "description": None,
            "source_path_display": "ace.snippets",
        }

    entries = list(entries_by_trigger.values())
    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": helper_result(
            "success",
            f"loaded {len(entries)} snippet(s)",
        ),
        "context": {
            "project": project,
            "scope": "explicit" if project is not None else "all_known",
        },
        "entries": entries,
        "stats": {"total_count": len(entries)},
    }


def _daemon_snippet_catalog_response(
    daemon: Any, *, project: str | None
) -> dict[str, Any]:
    entries_by_trigger = _daemon_xprompt_entries_by_trigger(daemon, project=project)
    for trigger, template in _user_snippets().items():
        if not is_valid_snippet_trigger(trigger):
            continue
        entries_by_trigger[trigger] = {
            "trigger": trigger,
            "template": template,
            "source": "user_config",
            "xprompt_name": None,
            "description": None,
            "source_path_display": "ace.snippets",
        }

    entries = list(entries_by_trigger.values())
    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": helper_result(
            "success",
            f"loaded {len(entries)} snippet(s)",
        ),
        "context": {
            "project": project,
            "scope": "explicit" if project is not None else "all_known",
        },
        "entries": entries,
        "stats": {"total_count": len(entries)},
    }


def _daemon_xprompt_entries_by_trigger(
    daemon: Any, *, project: str | None
) -> dict[str, dict[str, str | None]]:
    raw = daemon.snippet_catalog(project_id=project, limit=500)
    rows = raw.get("entries")
    if rows is None:
        rows = raw.get("snippets")
    if not isinstance(rows, list):
        raise LocalDaemonTransportError(
            "snippet catalog payload did not include entries",
            code="projection_degraded",
            fallback_reason="unsupported_daemon_payload",
        )

    entries: dict[str, dict[str, str | None]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise LocalDaemonTransportError(
                "snippet catalog row is not an object",
                code="projection_degraded",
                fallback_reason="unsupported_daemon_payload",
            )
        trigger = row.get("trigger")
        if not isinstance(trigger, str) or not is_valid_snippet_trigger(trigger):
            continue
        entries[trigger] = {
            "trigger": trigger,
            "template": str(row.get("template") or ""),
            "source": str(row.get("source") or "xprompt"),
            "xprompt_name": (
                row.get("xprompt_name")
                if isinstance(row.get("xprompt_name"), str)
                else None
            ),
            "description": (
                row.get("description")
                if isinstance(row.get("description"), str)
                else None
            ),
            "source_path_display": (
                row.get("source_path_display")
                if isinstance(row.get("source_path_display"), str)
                else None
            ),
        }
    return entries


def _xprompt_entries_by_trigger(
    *, project: str | None
) -> dict[str, dict[str, str | None]]:
    entries: dict[str, dict[str, str | None]] = {}
    for entry in get_xprompt_snippet_entries(project=project):
        entries[entry.trigger] = _xprompt_entry_wire(entry)
    return entries


def _xprompt_entry_wire(entry: XPromptSnippetEntry) -> dict[str, str | None]:
    return {
        "trigger": entry.trigger,
        "template": entry.template,
        "source": "xprompt",
        "xprompt_name": entry.xprompt_name,
        "description": entry.description,
        "source_path_display": entry.source_path_display,
    }


def _user_snippets() -> dict[str, str]:
    merged = load_merged_config()
    ace_cfg = merged.get("ace", {}) if isinstance(merged, dict) else {}
    raw_snippets = ace_cfg.get("snippets", {}) if isinstance(ace_cfg, dict) else {}
    if not isinstance(raw_snippets, dict):
        return {}
    return {
        key: value
        for key, value in raw_snippets.items()
        if isinstance(key, str) and isinstance(value, str)
    }
