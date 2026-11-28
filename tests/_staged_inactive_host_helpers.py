"""Shared public helpers for failed-origin inactive settlement host tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.agent.staged_handoff import (
    STAGED_HANDOFF_FILENAME,
    build_monitor_staged_record,
    write_adoption_receipt,
)

NOW = 1_700_000_000.0
STAGED_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
OTHER_STAGED_ID = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"
MONITOR_ID = "monitor-1"
FAILED_AT = NOW - 3600.0


def artifact_dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "artifacts" / name
    path.mkdir(parents=True)
    return path


def write_origin_meta(artifact: Path, name: str, outcome: str = "failed") -> None:
    (artifact / "agent_meta.json").write_text(
        json.dumps({"name": name, "agent_session": name}), encoding="utf-8"
    )
    (artifact / "done.json").write_text(
        json.dumps({"outcome": outcome, "finished_at": FAILED_AT}),
        encoding="utf-8",
    )


def write_monitor_stage(
    artifact: Path,
    staged_id: str = STAGED_ID,
    *,
    member_artifacts_dir: str | None = None,
) -> None:
    inner: dict[str, Any] = {"monitor_id": MONITOR_ID}
    if member_artifacts_dir:
        inner["member_artifacts_dir"] = member_artifacts_dir
    payload = build_monitor_staged_record(
        payload=inner,
        dirty_obligations_at_stage=[],
        staged_id=staged_id,
    )
    (artifact / STAGED_HANDOFF_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def write_held_receipt(artifact: Path, staged_id: str = STAGED_ID) -> None:
    write_adoption_receipt(
        {
            "staged_id": staged_id,
            "adopted_at": "2026-10-28T12:02:00Z",
            "outcome": "handoff_not_adopted",
            "reason": "no finalizer settlement",
        },
        artifacts_dir=str(artifact),
    )


def patch_owner_home(monkeypatch: Any, home: Path) -> None:
    monkeypatch.setattr("sase.monitor.staged_owner.sase_home", lambda: home)
    monkeypatch.setattr("sase.core.paths.sase_home", lambda: home)


def write_member_launch(
    member: Path, origin: Path, staged_id: str = STAGED_ID, **claim: Any
) -> None:
    context = {"starter_artifacts_dir": str(origin)}
    context.update(claim)
    payload = {
        "staged_id": staged_id,
        "monitor_id": MONITOR_ID,
        "workspace": {"claim_context": context},
    }
    (member / "staged_monitor_launch.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def write_owner_index(member: Path, origin: Path, staged_id: str = STAGED_ID) -> None:
    from sase.monitor.staged_owner import write_staged_owner_index

    write_staged_owner_index(
        MONITOR_ID,
        staged_id=staged_id,
        artifacts_dir=str(member),
        starter_artifacts_dir=str(origin),
    )
