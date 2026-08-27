"""Shared helpers for ``sase gate list``/``show``/``cancel`` handler tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.main.gate_handler import handle_gate_command
from tests.main.parser_cli_helpers import parse_sase_args
from tests.monitor._fixtures import record_from_disk

__all__ = [
    "dispatch",
    "gate_shell_home",
    "make_gate_shell",
    "patch_gate_shell_project_records",
]


@pytest.fixture(autouse=True)
def gate_shell_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point every agent-artifact path this handler reads at an isolated home."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


def dispatch(argv: list[str]) -> int:
    """Run one ``sase gate`` invocation and return its process exit code."""
    with pytest.raises(SystemExit) as exit_info:
        handle_gate_command(parse_sase_args(argv))
    return int(exit_info.value.code or 0)


def make_gate_shell(
    project: str,
    timestamp: str,
    member_name: str,
    *,
    lane: str,
    gate_id: str,
    gate_state: str = "pending",
    kind: str = "custom",
    label: str | None = None,
    reason: str = "wait for reviewer",
    start_status: str = "GATE",
    stop_status: str = "GATED",
    workspace_policy: str = "inherit",
    timeout_seconds: float = 86_400.0,
    **overrides: object,
) -> str:
    """Create a real gate-shell member's artifacts dir with test-friendly defaults."""
    from sase.core.paths import sase_projects_dir

    meta: dict[str, object] = {
        "agent_family": lane,
        "agent_family_role": "gate",
        "gate_id": gate_id,
        "gate_kind": kind,
        "gate_state": gate_state,
        "gate_start_status": start_status,
        "gate_stop_status": stop_status,
        "gate_label": label or gate_id,
        "gate_reason": reason,
        "gate_workspace_policy": workspace_policy,
        "gate_timeout_seconds": timeout_seconds,
        "name": member_name,
        "model": "test",
        **overrides,
    }
    artifacts_dir = (
        sase_projects_dir()
        / project
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )
    artifacts_dir.mkdir(parents=True)
    import json

    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return str(artifacts_dir)


def patch_gate_shell_project_records(
    monkeypatch: pytest.MonkeyPatch,
    artifacts_dirs: list[str],
) -> None:
    """Make ``sase.gate_shell.store`` see exactly *artifacts_dirs*, read live."""
    from sase.gate_shell import store as store_module

    def fake(project_name: str | None) -> list[AgentArtifactRecordWire]:
        return [
            record
            for record in (record_from_disk(d) for d in artifacts_dirs)
            if project_name is None or record.project_name == project_name
        ]

    monkeypatch.setattr(store_module, "_project_records", fake)
