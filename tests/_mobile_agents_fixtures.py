"""Shared helpers for mobile agent integration tests."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path

from sase.agent.running import RunningAgentInfo

_PNG_BYTES = b"\x89PNG\r\n\x1a\npayload"


def _image_request(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "prompt": "Review this screenshot",
        "original_filename": "screen.png",
        "content_type": "image/png",
        "byte_length": len(_PNG_BYTES),
        "base64_image": base64.b64encode(_PNG_BYTES).decode("ascii"),
        "device_id": "device/one",
        "name": "mobile.image",
        "dry_run": False,
    }
    payload.update(overrides)
    return payload


def _agent(
    tmp_path: Path,
    *,
    name: str | None = "alpha",
    status: str = "RUNNING",
    project: str = "sase",
) -> RunningAgentInfo:
    artifacts_dir = tmp_path / (name or "unnamed")
    artifacts_dir.mkdir(exist_ok=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "retry_of_timestamp": "20260506140000",
                "retry_attempt": 1,
                "parent_agent_name": "parent",
            }
        ),
        encoding="utf-8",
    )
    return RunningAgentInfo(
        name=name,
        project=project,
        pid=1234,
        model="gpt-5.5",
        provider="codex",
        workspace_num=100,
        duration="1m",
        approve=False,
        prompt="Line one\nLine two",
        status=status,
        started_at=datetime(2026, 5, 6, 14, 30, tzinfo=UTC),
        duration_seconds=60,
        artifacts_dir=str(artifacts_dir),
    )


def _known_project(tmp_path: Path, name: str = "sase") -> Path:
    workspace = tmp_path / "workspaces" / name
    workspace.mkdir(parents=True)
    project_dir = tmp_path / "projects" / name
    project_dir.mkdir(parents=True)
    project_file = project_dir / f"{name}.gp"
    project_file.write_text(f"WORKSPACE_DIR: {workspace}\n", encoding="utf-8")
    return workspace
