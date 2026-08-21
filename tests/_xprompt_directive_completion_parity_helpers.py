"""Helper-bridge payloads for ACE/LSP directive completion parity tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_FINALIZER_ROWS = (
    {
        "value": "commit",
        "display": "commit",
        "provider_ref": "builtin@commit",
        "detail": "builtin@commit",
        "required": True,
        "default": True,
        "max_attempts": 2,
        "documentation": "Required for this launch.",
    },
    {
        "value": "lint",
        "display": "lint",
        "provider_ref": "builtin@command",
        "detail": "builtin@command",
        "default": True,
        "after": ["format"],
        "max_attempts": 2,
        "documentation": "Selected by default.",
    },
    {
        "value": "zoom",
        "display": "zoom",
        "provider_ref": "plugin@zoom",
        "detail": "plugin@zoom",
        "max_attempts": 1,
        "documentation": "Optional.",
    },
)
_OPTIONAL_FINALIZER_ROWS = (_FINALIZER_ROWS[2],)


def _write_helper(tmp_path: Path) -> Path:
    helper = tmp_path / "lsp_helper.py"
    helper.write_text(_HELPER_SCRIPT, encoding="utf-8")
    return helper


def _write_failing_helper(tmp_path: Path) -> Path:
    helper = tmp_path / "failing_lsp_helper.py"
    helper.write_text(
        "import sys\nprint('helper unavailable', file=sys.stderr)\nsys.exit(2)\n",
        encoding="utf-8",
    )
    return helper


def _finalizer_catalog_payload(
    catalog: dict[str, Any] | Sequence[Mapping[str, object]] | None,
) -> dict[str, Any]:
    if isinstance(catalog, dict) and "schema_version" in catalog:
        return catalog
    entries = _FINALIZER_ROWS if catalog is None else catalog
    return {
        "schema_version": 1,
        "status": "ok",
        "message": "",
        "entries": [dict(entry) for entry in entries],
    }


_HELPER_SCRIPT = r"""
import json
import os
import sys


def result():
    return {
        "status": "success",
        "message": None,
        "warnings": [],
        "skipped": [],
        "partial_failure_count": None,
    }


def context():
    return {"project": None, "scope": "unspecified"}


operation = sys.argv[-1]
if operation == "agent-catalog":
    payload = {
        "schema_version": 1,
        "status": "ok",
        "message": "",
        "entries": [
            {
                "name": "planner",
                "status": "RUNNING",
                "project": "sase",
                "kind": "agent",
                "member_count": 1,
                "detail": "RUNNING",
                "documentation": "",
            },
            {
                "name": "coder",
                "status": "RUNNING",
                "project": "sase",
                "kind": "agent",
                "member_count": 1,
                "detail": "RUNNING",
                "documentation": "",
            },
            {
                "name": "review",
                "status": "RUNNING",
                "project": "sase",
                "kind": "clan",
                "member_count": 1,
                "detail": "clan",
                "documentation": "",
            },
            {
                "name": "ship",
                "status": "RUNNING",
                "project": "sase",
                "kind": "family",
                "member_count": 1,
                "detail": "family",
                "documentation": "",
            },
            {
                "name": "@builders",
                "status": "RUNNING",
                "project": "sase",
                "kind": "tribe",
                "member_count": 1,
                "detail": "tribe",
                "documentation": "",
            },
        ],
        "beads": [
            {
                "id": "sase-a",
                "title": "Active bug",
                "status": "in_progress",
                "type_label": "task",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-20T12:00:00Z",
                "task_type": "bug",
                "project": "sase",
            }
        ],
    }
elif operation == "xprompt-catalog":
    payload = {
        "schema_version": 1,
        "result": result(),
        "context": context(),
        "entries": [],
        "stats": {
            "total_count": 0,
            "project_count": 0,
            "skill_count": 0,
            "memory_count": 0,
            "pdf_requested": False,
        },
        "catalog_attachment": None,
    }
elif operation == "snippet-catalog":
    payload = {
        "schema_version": 1,
        "result": result(),
        "context": context(),
        "entries": [],
        "stats": {"total_count": 0},
    }
elif operation == "vcs-repo-catalog":
    payload = {
        "schema_version": 1,
        "status": "ok",
        "message": "",
        "entries": [],
    }
elif operation == "finalizer-catalog":
    catalog_path = os.environ.get("SASE_PARITY_FINALIZER_CATALOG")
    if not catalog_path:
        raise SystemExit("missing SASE_PARITY_FINALIZER_CATALOG")
    with open(catalog_path, encoding="utf-8") as fh:
        payload = json.load(fh)
else:
    raise SystemExit(f"unsupported operation: {operation}")

json.dump(payload, sys.stdout)
"""
