"""Shared helpers for Agent Hijack stop-protocol tests.

Split from ``tests.test_agent_hijack_stop``. Helpers use public names so
focused test modules can import them without touching a ``_``-prefixed
symbol across files.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack._stop_models import StopDeps
from sase.running_field import WorkspaceClaim
from tests._running_field_helpers import create_project_file_with_running

AGENT = "sase-7f.2"
PID = 424242
WS = 4
_TS = "20260712120000"


@pytest.fixture(name="hijack_home")
def shared_hijack_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


def make_artifacts(tmp_path: Path, *, capabilities: list[str] | None = None) -> Path:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    meta: dict[str, Any] = {
        "name": AGENT,
        "agent_session": "sase-7f",
        "pid": PID,
        "runner_capabilities": capabilities if capabilities is not None else ["hijack"],
        "agent_model": "claude-opus",
        "agent_llm_provider": "claude",
        "agent_effort": "high",
        "booted_at": 1000.0,
    }
    (artifacts / "agent_meta.json").write_text(json.dumps(meta))
    return artifacts


def make_project_file(tmp_path: Path) -> str:
    return create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                WS,
                "ace(run)-260712_120000",
                "feature",
                pid=PID,
                artifacts_timestamp=_TS,
            )
        ],
    )


def install_target(
    monkeypatch: pytest.MonkeyPatch, artifacts: Path, project_file: str
) -> None:
    def fake_fields(agent: Any) -> tuple[Any, str, str, str, bool]:
        return Path(agent.artifacts_dir), "proj", project_file, _TS, False

    monkeypatch.setattr("sase.agent.running.named_agent_project_fields", fake_fields)
    monkeypatch.setattr(
        "sase.agent.hijack._stop_target._claim_workspace_dir",
        lambda _project, _claim: None,
    )


def stop_deps(
    artifacts: Path,
    *,
    terminate: Any | None = None,
    snapshot_repo: Any | None = None,
) -> StopDeps:
    row = SimpleNamespace(
        name=AGENT,
        artifacts_dir=str(artifacts),
        status="RUNNING",
        pid=PID,
        is_monitor=False,
        agent_session=None,
        workspace_num=WS,
    )
    if terminate is None:
        terminate = SimpleNamespace(success=True, survivors=(), error=None)

        def _ok(*args: Any, **kwargs: Any) -> Any:
            return terminate

        terminate_fn = _ok
    else:
        terminate_fn = terminate
    return StopDeps(
        find_agent=lambda name: (
            SimpleNamespace(
                name=AGENT,
                artifacts_dir=str(artifacts),
                is_done=False,
                outcome=None,
            )
            if name == AGENT
            else None
        ),
        list_running=lambda: [row],
        terminate=terminate_fn,
        snapshot_repo=snapshot_repo,
        process_alive=lambda _meta, _path: True,
    )
