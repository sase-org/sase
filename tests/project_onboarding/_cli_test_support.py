"""Shared builders for project onboarding CLI contract tests.

Split from ``tests.project_onboarding.test_cli``; the original module
re-exports its tests so its import path keeps working.

Names are public so the ``test_cli_*`` split modules can share them
without importing ``_``-prefixed names across files. Helpers needed by
only one split module live in that module instead.
"""

from __future__ import annotations

import re
from typing import Any

from sase.main.parser import create_parser


def make_plan(*, blockers: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "project_onboarding_plan",
        "mode": "add",
        "status": "blocked" if blockers else "ready",
        "intent_fingerprint": "f" * 64,
        "provider": {"workflow_type": "gh", "display": "GitHub"},
        "target": {
            "ref": "team/demo",
            "display": "team/demo",
            "identity_key": "github.com/team/demo",
            "visibility": "private",
            "default_branch": "main",
            "checkout_dir": "/tmp/demo",
            "can_push": True,
            "sase_managed": False,
        },
        "project": {
            "key": "gh_team__demo",
            "name": "demo",
            "aliases": [],
            "state": "enabled",
            "existing": False,
            "accent": "cyan",
        },
        "setup": {"enabled": True, "code": "unmanaged_can_push"},
        "steps": [
            {
                "id": "checkout",
                "label": "Clone and register",
                "operation": "create",
                "state": "pending",
            }
        ],
        "warnings": [],
        "blockers": blockers or [],
        "apply_argv": ["sase", "project", "add", "team/demo", "--yes", "--json"],
        "next_argv": [],
    }


def make_create_args(parser_args: list[str]) -> Any:
    return create_parser(only="project").parse_args(["project", "create", *parser_args])


def long_option_order(help_text: str) -> list[str]:
    names: list[str] = []
    in_options = False
    for line in help_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("options:"):
            in_options = True
            continue
        if not in_options:
            continue
        # Option definition lines start with two spaces then a dash. Help
        # text may mention other flags (for example "sugar for --option").
        if not line.startswith("  -"):
            continue
        for match in re.finditer(r"--([a-z0-9-]+)", line):
            name = match.group(1)
            if name != "help" and name not in names:
                names.append(name)
    return names
