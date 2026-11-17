"""Shared helpers for the split new-project create execution tests.

Helpers needed by more than one split module live here under public names;
the ``test_new_project_create_execution_*`` modules import only these public
names (never ``_``-prefixed names from each other).
"""

from __future__ import annotations

from typing import Any

__all__ = ["create_document"]


def create_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": 1,
        "kind": "project_onboarding_plan",
        "mode": "create",
        "status": "ready",
        "intent_fingerprint": "c" * 64,
        "provider": {"workflow_type": "gh", "display": "GitHub"},
        "target": {
            "ref": "sase-org/new",
            "display": "sase-org/new",
            "identity_key": "github.com/sase-org/new",
            "host": "github.com",
            "owner": "sase-org",
            "web_url": "https://github.com/sase-org/new",
            "visibility": "private",
            "checkout_dir": "/tmp/new",
        },
        "project": {
            "key": "gh_sase-org__new",
            "name": "new",
            "accent": "#B9589C",
        },
        "creation": {
            "visibility": "private",
            "summary": ["GitHub repository"],
        },
        "steps": [
            {
                "id": "checkout",
                "operation": "create",
                "label": "Clone and register",
                "detail": "/tmp/new",
                "state": "pending",
            }
        ],
        "warnings": [],
        "blockers": [],
        "apply_argv": [
            "sase",
            "project",
            "create",
            "sase-org/new",
            "--description",
            "--yes",
            "--visibility",
            "private",
            "--option",
            "readme=--json",
            "--yes",
            "--json",
        ],
    }
    document.update(overrides)
    return document
