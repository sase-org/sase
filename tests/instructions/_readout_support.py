"""Shared fixtures for readout tests.

This is a private helper module: the names it defines are public on
purpose so the split ``test_readout_*`` modules can import them
without crossing a ``_``-prefixed boundary. Test-only helpers used by
a single module live in that module instead.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

RUN_START = datetime(2026, 10, 6, 11, tzinfo=UTC)
RUN_END = datetime(2026, 10, 6, 13, tzinfo=UTC)

HANDOFF_PHASE = {
    "lifecycle_phases": [{"phase": "handoff", "at": "2026-10-06T12:00:00Z"}]
}


def write_meta(
    artifacts: Path,
    *,
    name: str,
    provider: str,
    started_at: str = "2026-10-06T11:00:00Z",
    role: str | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {
        "name": name,
        "llm_provider": provider,
        "workspace_dir": "/work/synthetic",
        "run_started_at": started_at,
    }
    if role is not None:
        payload["agent_session_role"] = role
    if extra:
        payload.update(extra)
    (artifacts / "agent_meta.json").write_text(json.dumps(payload), encoding="utf-8")


def write_done(artifacts: Path) -> None:
    (artifacts / "done.json").write_text(
        json.dumps({"outcome": "completed", "finished_at": 1791000000}),
        encoding="utf-8",
    )


def passthrough_manifest_normalize(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.core.instruction_manifest.normalize_instruction_manifest",
        lambda payload: payload,
    )


__all__ = [
    "HANDOFF_PHASE",
    "RUN_END",
    "RUN_START",
    "passthrough_manifest_normalize",
    "write_done",
    "write_meta",
]
