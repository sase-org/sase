"""Shared helpers for trusted PluginsRequired gate tests."""

from __future__ import annotations

from typing import Any

from sase.plugins._required_gate_spec import build_plugins_required_gate_spec


def missing_entry(**overrides: Any) -> dict[str, str]:
    fields = {
        "requirement": "sase-github",
        "name": "sase-github",
        "kind": "missing",
        "install_command": "sase plugin install sase-github",
        "message": (
            "required plugin `sase-github` is not installed; "
            "run `sase plugin install sase-github`"
        ),
    }
    fields.update(overrides)
    return fields


def plugins_required_spec(
    *, request_id: str = "plugins-required-1", **overrides: Any
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "request_id": request_id,
        "project": "sase",
        "project_label": "sase",
        "missing": [missing_entry()],
        "producer": {"chop": "plugins_required"},
    }
    fields.update(overrides)
    return build_plugins_required_gate_spec(**fields)
