"""Editor helper bridge operation for SASE snippet catalogs."""

from __future__ import annotations

from typing import Any

from sase.config import load_merged_config
from sase.core.snippet_catalog_facade import compose_snippet_catalog
from sase.xprompt.snippet_bridge import (
    XPromptSnippetEntry,
    get_xprompt_snippet_entries,
    is_valid_snippet_trigger,
)

from ._mobile_helper_common import (
    GATEWAY_WIRE_SCHEMA_VERSION,
    helper_result,
    optional_string,
)


def snippet_catalog_response(request: dict[str, Any]) -> dict[str, Any]:
    """Return the merged ACE snippet registry for editor clients."""
    project = optional_string(request.get("project"), "project")
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

    raw_templates = {
        trigger: entry["template"] or ""
        for trigger, entry in entries_by_trigger.items()
    }
    composition = compose_snippet_catalog(raw_templates)
    entries: list[dict[str, str | None]] = []
    for trigger, template in composition.templates.items():
        source = composition.alias_provenance.get(trigger, trigger)
        entry = dict(entries_by_trigger[source])
        entry["trigger"] = trigger
        entry["template"] = template
        entries.append(entry)
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
