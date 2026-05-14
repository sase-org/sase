"""Xprompt operation handlers for the provider host runtime."""

from __future__ import annotations

import importlib.metadata
import os
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from sase.host.runtime_shared import (
    OperationContext,
    ProviderHostRuntimeError,
    optional_int,
    optional_str,
    require_capability,
)
from sase.host.wire import HOST_CAP_XPROMPT_CATALOG


def xprompt_catalog(context: OperationContext) -> Mapping[str, Any]:
    require_capability(context, HOST_CAP_XPROMPT_CATALOG)
    payload = context.request.payload
    include_pdf = bool(payload.get("include_pdf", False))
    if include_pdf:
        raise ProviderHostRuntimeError(
            "operation_unsupported",
            "host-routed xprompt.catalog is read-only and does not generate PDFs",
            target="payload.include_pdf",
        )

    from sase.xprompt._catalog_structured import (
        build_structured_xprompts_catalog,
    )

    projection = build_structured_xprompts_catalog(
        project=optional_str(payload.get("project")),
        source=optional_str(payload.get("source")),
        tag=optional_str(payload.get("tag")),
        query=optional_str(payload.get("query")),
        include_pdf=False,
        limit=optional_int(payload.get("limit")),
    )
    context.logs.append("info", "xprompt catalog collected", target="sase.host.xprompt")
    return {
        "projection": asdict(projection),
        "cache_invalidation": _xprompt_catalog_cache_policy(),
    }


def _xprompt_catalog_cache_policy() -> dict[str, Any]:
    """Return stable cache inputs for xprompt/resource catalog calls."""

    from sase.xprompt.loader_sources import get_xprompt_search_paths

    paths: list[dict[str, Any]] = []
    for path in get_xprompt_search_paths():
        paths.append(_path_fingerprint(path))
    for env_name in ("SASE_DISABLE_PLUGINS", "SASE_DISABLE_PLUGIN_XPROMPTS"):
        value = os.environ.get(env_name)
        paths.append({"env": env_name, "value": value})
    return {
        "version": 1,
        "sources": paths,
        "plugin_entry_points": _entry_point_fingerprint("sase_xprompts"),
    }


def _entry_point_fingerprint(group: str) -> list[dict[str, str]]:
    try:
        entry_points = importlib.metadata.entry_points(group=group)
    except Exception:
        return []
    return [
        {"name": ep.name, "value": ep.value}
        for ep in sorted(entry_points, key=lambda item: item.name)
    ]


def _path_fingerprint(path: Any) -> dict[str, Any]:
    path_str = os.fspath(path)
    try:
        stat = os.stat(path_str)
    except OSError:
        return {"path": path_str, "exists": False}
    return {
        "path": path_str,
        "exists": True,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }
