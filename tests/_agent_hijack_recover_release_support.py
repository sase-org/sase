"""Shared fixtures for hijack release recovery tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack.ledger import HijackLedgerConflict
from sase.agent.hijack.recover_common import RecoveryResult
from sase.agent.hijack.recover_release import (
    RELEASE_ACTIONS,
    ReleaseDeps,
    recover_release_action,
    restart_availability_reason,
    restart_replacement_conflicts,
)
from tests._agent_hijack_recover_helpers import record as make_record
from tests._agent_hijack_recover_helpers import subject as make_subject


@dataclass(frozen=True)
class ReleaseRow:
    action: str
    available: bool
    reason: str | None
    target: str | None = None


@dataclass(frozen=True)
class ReleasePreview:
    revision: int
    rows: tuple[ReleaseRow, ...]
    hijack_id: str = "h-123"
    state: str = "held"

    def action(self, name: str) -> ReleaseRow | None:
        return next((row for row in self.rows if row.action == name), None)

    @property
    def default_action(self) -> str | None:
        return "escalate"

    @property
    def header(self) -> dict[str, Any]:
        return {"agent_name": "acme--3"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "hijack_id": self.hijack_id,
            "revision": self.revision,
            "header": dict(self.header),
            "default_action": self.default_action,
            "actions": [
                {
                    "action": row.action,
                    "available": row.available,
                    "reason": row.reason,
                    "label": row.action,
                    "detail": "",
                    "target": row.target,
                }
                for row in self.rows
            ],
        }


def release_preview(
    revision: int = 7,
    *,
    restart: str | None = None,
    edit: str | None = None,
    dismiss: str | None = None,
    state: str = "held",
) -> ReleasePreview:
    rows = [
        ReleaseRow("escalate", True, None, "claude/opus@xhigh"),
        ReleaseRow("continue", True, None, "claude/opus@high"),
        ReleaseRow("instruct", True, None, "claude/opus@high"),
        ReleaseRow("restart", restart is None, restart),
        ReleaseRow("edit", edit is None, edit),
        ReleaseRow("dismiss", dismiss is None, dismiss),
    ]
    return ReleasePreview(revision=revision, rows=tuple(rows), state=state)


class ReleaseLedger:
    """In-memory CAS mirroring the Rust release transition rules."""

    def __init__(self, record: dict[str, Any]) -> None:
        self.current = dict(record)
        self.events: list[str] = []

    def cas(
        self, record: Mapping[str, Any], event: Mapping[str, Any]
    ) -> dict[str, Any]:
        if int(record.get("revision", -1)) != int(self.current.get("revision")):
            raise HijackLedgerConflict("stale revision")
        name = str(event.get("event"))
        nxt = dict(self.current)
        if name == "begin_resolution":
            if nxt.get("state") not in {"held", "expired"}:
                raise ValueError(f"illegal {nxt.get('state')} + begin_resolution")
            action = str(event.get("action") or "")
            allowed = (
                {"restart", "edit", "dismiss"}
                if nxt.get("state") == "expired"
                else {"escalate", "continue", "instruct", "restart", "edit", "dismiss"}
            )
            if action not in allowed:
                raise ValueError(f"illegal action {action}")
            nxt["state"] = "resolving"
            for key in (
                "action",
                "reserved_successor_name",
                "resolver_pid",
                "resolver_process_identity_token",
            ):
                if key in event:
                    record_key = "resolution_action" if key == "action" else key
                    nxt[record_key] = event[key]
            nxt["error"] = None
        elif name == "complete_resolution":
            if nxt.get("state") != "resolving":
                raise ValueError(f"illegal {nxt.get('state')} + complete_resolution")
            nxt["state"] = (
                "dismissed" if nxt.get("resolution_action") == "dismiss" else "resolved"
            )
            nxt["error"] = None
        elif name == "resolution_failed":
            if nxt.get("state") != "resolving":
                raise ValueError(f"illegal {nxt.get('state')} + resolution_failed")
            nxt["state"] = "held"
            nxt["error"] = event.get("error")
        else:
            raise ValueError(f"unknown event {name}")
        nxt["revision"] = int(nxt.get("revision", 0)) + 1
        self.current = nxt
        self.events.append(name)
        return dict(nxt)

    def load(self, hijack_id: str) -> dict[str, Any] | None:
        if self.current.get("hijack_id") == hijack_id:
            return dict(self.current)
        return None


def held_artifacts(tmp_path: Path, *, outcome: str = "hijacked") -> Path:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "acme--3", "bead_id": "sase-1"}), encoding="utf-8"
    )
    (artifacts / "done.json").write_text(
        json.dumps(
            {
                "outcome": outcome,
                "recovery": {
                    "kind": "hijack",
                    "hijack_id": "h-123",
                    "state": "pending",
                },
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "raw_prompt.md").write_text("Do the thing.\n", encoding="utf-8")
    return artifacts


def install_release_ledger(
    monkeypatch: pytest.MonkeyPatch, fake: ReleaseLedger
) -> None:
    import sase.agent.hijack._release_settle as settle_module
    import sase.agent.hijack.ledger as ledger_module
    import sase.agent.hijack.recover_release as release_module
    import sase.core.agent_artifact_index_lifecycle as index_module

    monkeypatch.setattr(ledger_module, "cas_advance_record", fake.cas)
    monkeypatch.setattr(ledger_module, "load_record", fake.load)
    monkeypatch.setattr(settle_module.ledger, "cas_advance_record", fake.cas)
    monkeypatch.setattr(settle_module.ledger, "load_record", fake.load)
    monkeypatch.setattr(release_module.ledger, "cas_advance_record", fake.cas)
    monkeypatch.setattr(release_module.ledger, "load_record", fake.load)
    monkeypatch.setattr(
        index_module,
        "update_agent_artifact_index_for_marker_mutation",
        lambda _path: True,
    )


def release_subject(record: dict[str, Any]) -> Any:
    return make_subject(record)


def release_deps(
    *,
    preview: ReleasePreview,
    snapshot: Any = "ok",
    dismiss_ok: bool = True,
    plan_ok: bool = True,
    execute_status: str = "ok",
    launch_name: str | None = "acme--3",
    bead_released: bool = True,
) -> tuple[ReleaseDeps, dict[str, Any]]:
    calls: dict[str, Any] = {"snapshots": 0, "bead": 0, "dismiss": 0}

    def fake_snapshot(
        resolving: Mapping[str, Any], *, discard_without_snapshot: bool = False
    ) -> list[dict[str, Any]]:
        calls["snapshots"] += 1
        if snapshot == "fail" and not discard_without_snapshot:
            from sase.agent.hijack.recover_common import RecoveryRefusal

            raise RecoveryRefusal(
                "snapshot_failed",
                "boom; use --discard-without-snapshot to release anyway",
            )
        return [{"repo": "/repo", "reference": "snap-1", "fingerprint": "TOKEN"}]

    def fake_dismiss(name: str) -> SimpleNamespace:
        calls["dismiss"] += 1
        if dismiss_ok:
            return SimpleNamespace(
                success=True,
                message=f"Dismissed {name!r}",
                reason="",
                status="dismissed",
            )
        return SimpleNamespace(
            success=False,
            message="dismiss broke",
            reason="dismiss_failed",
            status="error",
        )

    def fake_plan(name: str) -> SimpleNamespace:
        if not plan_ok:
            from sase.agent._restart_types import AgentRestartError

            raise AgentRestartError(reason="fanout", message="fan-out prompt")
        return SimpleNamespace(name=name, presented_name=name)

    def fake_execute(plan: Any) -> SimpleNamespace:
        return SimpleNamespace(
            status=execute_status,
            name=getattr(plan, "name", "acme--3"),
            error=None if execute_status == "ok" else "relaunch broke",
            recovery_command="sase run --recovery abc"
            if execute_status != "ok"
            else None,
            recovery_dir="/tmp/restarts/abc" if execute_status != "ok" else None,
            recovery_prompt="/tmp/restarts/abc/prompt.md"
            if execute_status != "ok"
            else None,
            renamed_to=None,
            launched_pid=999 if execute_status == "ok" else None,
            launched_workspace_num=5 if execute_status == "ok" else None,
            launched_artifacts_dir="/tmp/artifacts/acme--3"
            if execute_status == "ok"
            else None,
        )

    def fake_launch(reuse_plan: Any) -> str | None:
        return launch_name

    def fake_bead(record: Mapping[str, Any]) -> tuple[bool, str]:
        calls["bead"] += 1
        return bead_released, "released" if bead_released else "kept"

    deps = ReleaseDeps(
        load_subject=lambda name: make_subject(record_for(name)),
        preview=lambda record: preview,
        snapshot=fake_snapshot,
        dismiss_row=fake_dismiss,
        plan_restart=fake_plan,
        execute_restart=fake_execute,
        plan_replacement_reuse=lambda prompt: SimpleNamespace(
            rewritten_prompt=prompt, segment_envs=None
        ),
        apply_replacement_reuse=lambda reuse_plan: None,
        launch_replacement=fake_launch,
        release_bead_claim=fake_bead,
    )
    return deps, calls


def record_for(name: object) -> dict[str, Any]:
    raise AssertionError("load_subject is replaced per-test")


def recover_args(**overrides: Any) -> Any:
    import argparse

    values: dict[str, Any] = {
        "name": "acme--3",
        "action": None,
        "dry_run": False,
        "json": False,
        "model": None,
        "prompt_file": None,
        "discard_without_snapshot": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def release_preview_for_cli() -> Any:
    from sase.agent.hijack.preview import RecoveryAction, RecoveryPreview

    rows = [
        ("escalate", True, None, "Escalate", "up", "t"),
        ("continue", True, None, "Continue", "same", "t"),
        ("instruct", True, None, "Instruct", "guide", None),
        ("restart", True, None, "Restart", "same prompt", None),
        ("edit", True, None, "Edit", "edit prompt", None),
        ("dismiss", True, None, "Dismiss", "snapshot", None),
    ]
    return RecoveryPreview(
        hijack_id="h-123",
        revision=7,
        header={
            "agent_name": "acme--3",
            "workspace_num": 3,
            "model_display": "m",
            "run_duration_display": "1m",
            "hijacked_ago": "",
            "files_changed": 0,
            "insertions": 0,
            "deletions": 0,
            "last_tool": "",
            "last_tool_age": "",
        },
        default_action="escalate",
        actions=tuple(RecoveryAction(*row) for row in rows),
        state="held",
        _record={"hijack_id": "h-123"},
        _artifacts_dir="/tmp/artifacts",
    )
