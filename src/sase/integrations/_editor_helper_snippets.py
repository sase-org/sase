"""Editor helper bridge operation for SASE snippet catalogs."""

from __future__ import annotations

from typing import Any

from sase.snippet.catalog import editor_helper_entries, load_snippet_catalog

from ._mobile_helper_common import (
    GATEWAY_WIRE_SCHEMA_VERSION,
    helper_result,
    optional_string,
)


def snippet_catalog_response(request: dict[str, Any]) -> dict[str, Any]:
    """Return the merged ACE snippet registry for editor clients."""
    project = optional_string(request.get("project"), "project")
    catalog = load_snippet_catalog(project)
    entries = editor_helper_entries(catalog)
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
