"""Shared builders for gate-shell settlement follow-up tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.gate_shell.member import create_gate_shell_member
from sase.notification_gates.model_shell import GateShellSpec, subset_branches_allowed

__all__ = [
    "DEFAULT_SHELL",
    "gate_spec",
    "make_gate_shell_member",
    "sandbox_home",
]

_ECHO_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "print(json.dumps({'status': 'ok', 'input': json.load(sys.stdin)}))\n"
)


@pytest.fixture(autouse=True)
def sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


DEFAULT_SHELL: dict[str, Any] = {
    "pending_status": "GATE",
    "settled_status": "GATED",
    "next": {"prompt": "Verify the cleanup landed."},
}


def gate_spec(request_id: str, *, shell: dict[str, Any] | None) -> dict[str, object]:
    spec: dict[str, object] = {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {
            "icon": "🧪",
            "title": "Reclaim disk space",
            "notes": ["Free up disk on the shared volume"],
        },
        "query": "cleanup OR reject",
        "primary_branch": ["cleanup"],
        "options": [
            {
                "id": "cleanup",
                "label": "Clean up",
                "command": {"argv": ["commands/cleanup"]},
            },
            {
                "id": "reject",
                "label": "Reject",
                "command": {"argv": ["commands/reject"]},
            },
        ],
        "resources": [
            {"path": "commands/cleanup", "role": "command", "content": _ECHO_COMMAND},
            {"path": "commands/reject", "role": "command", "content": _ECHO_COMMAND},
        ],
    }
    if shell is not None:
        spec["shell"] = shell
    return spec


def make_gate_shell_member(
    request_id: str,
    bundle_path: Path,
    *,
    shell: dict[str, Any],
    branches: tuple[tuple[str, ...], ...] = (("cleanup",), ("reject",)),
    gate_kind: str = "custom",
    label: str = "Reclaim disk space",
    workspace_num: int | None = None,
) -> str:
    """Build the gate-shell member from the *same* shell block as the bundle.

    Settlement resolves follow-up policy from the durable bundle envelope
    (the single source of truth), never from the member's own metadata, so a
    test that wants a resolvable policy must give both the same shell block.
    """
    parsed_shell = GateShellSpec.from_mapping(
        shell,
        branches=branches,
        allow_branch_subsets=subset_branches_allowed(gate_kind),
    )
    base_meta: dict[str, Any] = {
        "name": "lane--0",
        "agent_family": "lane",
        "model": "gpt-5",
    }
    if workspace_num is not None:
        base_meta["workspace_dir"] = "/work/lane"
    artifacts_dir = create_gate_shell_member(
        "proj",
        base_meta,
        lane="lane",
        suffix="--gate",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=workspace_num,
        gate_id=request_id,
        gate_kind=gate_kind,
        label=label,
        reason="wait for reviewer",
        creator_agent="lane--0",
        timeout_seconds=86400.0,
        request_fingerprint=None,
        shell=parsed_shell,
    )
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    update_meta_field(artifacts_dir, "gate_bundle_path", str(bundle_path))
    if workspace_num is not None:
        update_meta_field(artifacts_dir, "gate_workspace_policy", "inherit")
    return artifacts_dir
