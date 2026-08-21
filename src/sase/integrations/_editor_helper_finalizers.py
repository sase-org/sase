"""Editor helper-bridge operation for the finalizer completion catalog."""

from __future__ import annotations

from typing import Any

from sase.finalizers.catalog import (
    FINALIZER_CATALOG_SCHEMA_VERSION,
    build_finalizer_completion_catalog,
)
from sase.integrations._mobile_helper_common import optional_project


def finalizer_catalog_response(request: dict[str, Any]) -> dict[str, Any]:
    """Return configured finalizer rows for ACE and LSP completion clients.

    The helper is fail-closed: unsupported schema versions raise, and malformed
    finalizer configuration becomes a ``status=error`` envelope with no rows.
    Unknown request fields are ignored so mixed-version clients stay compatible.
    """
    if request.get("schema_version") != FINALIZER_CATALOG_SCHEMA_VERSION:
        raise ValueError("unsupported finalizer-catalog schema_version")
    optional_project(request.get("project"))

    try:
        catalog = build_finalizer_completion_catalog()
    except (TypeError, ValueError) as exc:
        return _envelope("error", str(exc))

    if not catalog.ok:
        return _envelope("error", catalog.message)
    return _envelope("ok", catalog.message, list(catalog.wire_entries()))


def _envelope(
    status: str,
    message: str,
    entries: list[dict[str, object]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": FINALIZER_CATALOG_SCHEMA_VERSION,
        "status": status,
        "message": message,
        "entries": entries or [],
    }


__all__ = ["finalizer_catalog_response"]
