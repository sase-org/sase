"""Snapshot-verified release recovery: restart, edit backend, and dismiss."""

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


class TestReleaseSnapshotGate:
    def test_matching_fingerprint_reuses_recorded_snapshot(self) -> None:
        from sase.agent.hijack._release_snapshot import (
            _fingerprint_token,
            ensure_recovery_snapshot,
        )

        recorded = [
            {
                "repo": "/repo",
                "reference": "snap-1",
                "fingerprint": _fingerprint_token({"head": "abc"}),
            }
        ]
        calls: list[str] = []
        merged: list[tuple[str, dict[str, Any]]] = []

        result = ensure_recovery_snapshot(
            {
                "hijack_id": "h-1",
                "agent_name": "a",
                "snapshots": recorded,
                "workspace_dir": "/repo",
                "workspace_num": 3,
            },
            fingerprint_fn=lambda root: {"head": "abc"},
            snapshot_repo=lambda *args, **kwargs: calls.append("snap"),  # type: ignore[arg-type]
            merge_fn=lambda hid, fields: merged.append((hid, fields)),
        )
        assert calls == []
        assert result == recorded
        assert merged == [("h-1", {"snapshots": recorded})]

    def test_stale_fingerprint_refreshes_and_merges(self) -> None:
        from sase.agent.hijack._release_snapshot import (
            _fingerprint_token,
            ensure_recovery_snapshot,
        )

        recorded = [{"repo": "/repo", "reference": "snap-0", "fingerprint": "OLD"}]
        merged: list[tuple[str, dict[str, Any]]] = []
        snap = SimpleNamespace(snapshot_id="snap-9", head="abc", worktree_tree="tree-9")

        result = ensure_recovery_snapshot(
            {
                "hijack_id": "h-9",
                "agent_name": "a",
                "snapshots": recorded,
                "workspace_dir": "/repo",
                "workspace_num": 3,
            },
            fingerprint_fn=lambda root: {"head": "abc"},
            snapshot_repo=lambda *args, **kwargs: snap,
            merge_fn=lambda hid, fields: merged.append((hid, fields)),
        )
        assert result == [
            {
                "repo": "/repo",
                "reference": "snap-9",
                "fingerprint": _fingerprint_token({"head": "abc"}),
            }
        ]
        assert merged == [("h-9", {"snapshots": result})]

    def test_snapshot_failure_names_escape_hatch_and_keeps_hold(self) -> None:
        from sase.agent.hijack._release_snapshot import ensure_recovery_snapshot
        from sase.agent.hijack.recover_common import RecoveryRefusal

        def no_fingerprint(root: str) -> dict[str, str]:
            raise RuntimeError("no fingerprint")

        existing = [{"repo": "/repo", "reference": "snap-1", "fingerprint": "TOKEN"}]
        with pytest.raises(RecoveryRefusal) as excinfo:
            ensure_recovery_snapshot(
                {
                    "hijack_id": "h-1",
                    "agent_name": "a",
                    "snapshots": existing,
                    "workspace_dir": "/repo",
                    "workspace_num": 3,
                },
                fingerprint_fn=no_fingerprint,
            )
        assert excinfo.value.code == "snapshot_failed"
        assert "--discard-without-snapshot" in excinfo.value.message

        def boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("git exploded")

        result = ensure_recovery_snapshot(
            {
                "hijack_id": "h-1",
                "agent_name": "a",
                "snapshots": existing,
                "workspace_dir": "/repo",
                "workspace_num": 3,
            },
            fingerprint_fn=no_fingerprint,
            snapshot_repo=boom,
            discard_without_snapshot=True,
        )
        assert result == existing

    def test_missing_workspace_without_snapshots_refuses(self) -> None:
        from sase.agent.hijack._release_snapshot import ensure_recovery_snapshot
        from sase.agent.hijack.recover_common import RecoveryRefusal

        with pytest.raises(RecoveryRefusal) as excinfo:
            ensure_recovery_snapshot(
                {"hijack_id": "h-1", "agent_name": "a", "snapshots": []},
            )
        assert excinfo.value.code == "snapshot_failed"

    def test_real_git_repo_with_changes_snapshots_before_release(
        self, tmp_path: Path
    ) -> None:
        import subprocess

        from sase.agent.hijack._release_snapshot import ensure_recovery_snapshot

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.t"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "t"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True
        )
        # Unpushed commit plus staged, unstaged, untracked, and binary changes.
        (repo / "tracked.txt").write_text("staged change\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "unpushed"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        (repo / "tracked.txt").write_text("unstaged change\n", encoding="utf-8")
        (repo / "untracked.txt").write_text("new file\n", encoding="utf-8")
        (repo / "blob.bin").write_bytes(bytes(range(256)))

        workspace = tmp_path / "ws"
        workspace.mkdir()
        record = {
            "hijack_id": "h-git",
            "agent_name": "acme--3",
            "artifacts_dir": str(tmp_path / "artifacts"),
            "workspace_dir": str(repo),
            "workspace_num": 3,
            "snapshots": [],
        }
        result = ensure_recovery_snapshot(record)
        assert len(result) == 1
        assert result[0]["repo"] == str(repo)
        assert result[0]["reference"]
        assert result[0]["fingerprint"]


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


class TestReleaseTransaction:
    def _held(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides: Any
    ) -> tuple[ReleaseLedger, dict[str, Any]]:
        artifacts = held_artifacts(tmp_path)
        rec = make_record(artifacts, **overrides)
        fake = ReleaseLedger(rec)
        install_release_ledger(monkeypatch, fake)
        return fake, rec

    def test_dismiss_settles_dismissed_and_releases_bead(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, calls = release_deps(preview=release_preview())
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action("acme--3", action="dismiss", deps=deps)

        assert result.kind == "launched", result.message
        assert fake.current["state"] == "dismissed"
        assert fake.current["resolution_action"] == "dismiss"
        assert calls["snapshots"] == 1
        assert calls["dismiss"] == 1
        assert calls["bead"] == 1
        done = json.loads((tmp_path / "artifacts" / "done.json").read_text())
        assert done["outcome"] == "hijacked"
        assert done["recovery"]["state"] == "dismissed"
        assert done["recovery"]["action"] == "dismiss"

    def test_restart_keeps_bead_and_settles_resolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, calls = release_deps(preview=release_preview())
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action("acme--3", action="restart", deps=deps)

        assert result.kind == "launched", result.message
        assert result.successor == "acme--3"
        assert fake.current["state"] == "resolved"
        assert fake.current["resolution_action"] == "restart"
        assert calls["snapshots"] == 1
        assert calls["bead"] == 0
        done = json.loads((tmp_path / "artifacts" / "done.json").read_text())
        assert done["recovery"]["state"] == "resolved"
        assert done["recovery"]["action"] == "restart"
        assert done["recovery"]["successor"] == "acme--3"

    def test_restart_with_replacement_runs_edit_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, calls = release_deps(preview=release_preview())
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action(
            "acme--3", action="restart", prompt="Do the other thing.\n", deps=deps
        )

        assert result.kind == "launched", result.message
        assert result.successor == "acme--3"
        assert fake.current["state"] == "resolved"
        assert fake.current["resolution_action"] == "edit"
        assert calls["dismiss"] == 1
        assert calls["bead"] == 1

    def test_replacement_conflicts_refuse_before_cas(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, calls = release_deps(preview=release_preview())
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action(
            "acme--3",
            action="restart",
            prompt="%wait(acme--9)\n\nDo the other thing.\n",
            deps=deps,
        )

        assert result.kind == "refused"
        assert result.detail.get("code") == "conflicting_directives"
        assert fake.events == []
        assert calls["snapshots"] == 0

    def test_snapshot_failure_returns_to_held(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, calls = release_deps(preview=release_preview(), snapshot="fail")
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action("acme--3", action="dismiss", deps=deps)

        assert result.kind == "error"
        assert result.detail.get("code") == "snapshot_failed"
        assert fake.current["state"] == "held"
        assert calls["dismiss"] == 0

    def test_discard_without_snapshot_bypasses_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, calls = release_deps(preview=release_preview(), snapshot="fail")
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action(
            "acme--3", action="dismiss", discard_without_snapshot=True, deps=deps
        )

        assert result.kind == "launched", result.message
        assert fake.current["state"] == "dismissed"

    def test_preview_refusal_blocks_before_cas(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, calls = release_deps(
            preview=release_preview(restart="fanout: fan-out prompt")
        )
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action("acme--3", action="restart", deps=deps)

        assert result.kind == "refused"
        assert result.detail.get("code") == "action_unavailable"
        assert "fan-out prompt" in (result.message or "")
        assert fake.events == []

    def test_stale_revision_refuses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, _ = release_deps(preview=release_preview(revision=7))
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action(
            "acme--3", action="dismiss", expected_revision=6, deps=deps
        )

        assert result.kind == "refused"
        assert result.detail.get("code") == "stale_revision"
        assert fake.events == []

    def test_repeat_resolution_reports_without_acting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch, state="dismissed")
        deps, calls = release_deps(preview=release_preview())
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action("acme--3", action="dismiss", deps=deps)

        assert result.kind == "already_resolved"
        assert calls["snapshots"] == 0
        assert calls["dismiss"] == 0

    def test_expired_hold_allows_release(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch, state="expired")
        deps, _ = release_deps(preview=release_preview(state="expired"))
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action("acme--3", action="dismiss", deps=deps)

        assert result.kind == "launched", result.message
        assert fake.current["state"] == "dismissed"

    def test_unsupported_action_and_state_refuse(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, _ = release_deps(preview=release_preview())
        deps.load_subject = lambda name: make_subject(rec)

        bad_action = recover_release_action("acme--3", action="escalate", deps=deps)
        assert bad_action.kind == "refused"
        assert bad_action.detail.get("code") == "unsupported_action"

        stopped = make_record(held_artifacts(tmp_path), state="stop_failed")
        deps.load_subject = lambda name: make_subject(stopped)
        bad_state = recover_release_action("acme--3", action="dismiss", deps=deps)
        assert bad_state.kind == "refused"
        assert bad_state.detail.get("code") == "not_held"

    def test_failed_relaunch_after_release_stays_uncertain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, rec = self._held(tmp_path, monkeypatch)
        deps, _ = release_deps(preview=release_preview(), execute_status="partial")
        deps.load_subject = lambda name: make_subject(rec)

        result = recover_release_action("acme--3", action="restart", deps=deps)

        assert result.kind == "uncertain"
        assert fake.current["state"] == "resolving"
        assert result.detail.get("recovery_command") == "sase run --recovery abc"


class TestRestartAvailability:
    def test_planner_success_means_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sase.agent.hijack.recover_release as release_module

        monkeypatch.setattr(
            release_module, "_default_plan_restart", lambda name: object()
        )
        assert restart_availability_reason({"agent_name": "acme--3"}) is None

    def test_planner_refusal_becomes_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sase.agent.hijack.recover_release as release_module
        from sase.agent._restart_types import AgentRestartError

        def refuse(name: str) -> Any:
            raise AgentRestartError(reason="fanout", message="fan-out prompt")

        monkeypatch.setattr(release_module, "_default_plan_restart", refuse)
        reason = restart_availability_reason({"agent_name": "acme--3"})
        assert reason is not None
        assert "fanout" in reason
        assert "fan-out prompt" in reason

    def test_missing_name_refuses(self) -> None:
        assert restart_availability_reason({}) is not None


class TestReplacementConflicts:
    def test_clean_prompt_has_no_conflicts(self) -> None:
        assert restart_replacement_conflicts("Do the other thing.\n") == []

    def test_changed_id_is_allowed(self) -> None:
        assert (
            restart_replacement_conflicts("%id acme--9\n\nDo the other thing.\n") == []
        )

    def test_wait_dependency_conflicts(self) -> None:
        conflicts = restart_replacement_conflicts(
            "%wait(acme--9)\n\nDo the other thing.\n"
        )
        assert any("wait" in item for item in conflicts)

    def test_directive_only_prompt_conflicts(self) -> None:
        conflicts = restart_replacement_conflicts("%id(acme--9)\n")
        assert conflicts != []

    def test_unknown_alias_model_fails_closed(self) -> None:
        from sase.agent.hijack.recover_common import RecoveryRefusal

        with pytest.raises(RecoveryRefusal) as excinfo:
            restart_replacement_conflicts(
                "%model:@no-such-alias-xyz\n\nDo the thing.\n"
            )
        assert excinfo.value.code == "invalid_prompt"

    def test_concrete_model_is_allowed(self) -> None:
        assert (
            restart_replacement_conflicts("%model:claude/opus@high\n\nDo the thing.\n")
            == []
        )


class TestReleasePreviewRows:
    def _wire(
        self,
        state: str = "held",
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "hijack_id": "h-123",
            "revision": 7,
            "header": {},
            "default_action": "escalate",
            "actions": [
                {
                    "action": "escalate",
                    "available": True,
                    "reason": None,
                    "label": "Escalate",
                    "detail": "up",
                    "target": "t",
                },
                {
                    "action": "continue",
                    "available": True,
                    "reason": None,
                    "label": "Continue",
                    "detail": "same",
                    "target": "t",
                },
                {
                    "action": "restart",
                    "available": False,
                    "reason": "not yet available",
                    "label": "Restart",
                    "detail": "",
                    "target": None,
                },
                {
                    "action": "dismiss",
                    "available": False,
                    "reason": "not yet available",
                    "label": "Dismiss",
                    "detail": "",
                    "target": None,
                },
            ],
        }

    def test_held_preview_marks_release_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sase.agent.hijack.preview as preview_module

        monkeypatch.setattr(
            "sase.agent.hijack.recover_release.restart_availability_reason",
            lambda record: None,
        )
        result = preview_module._with_release_rows(
            self._wire(), {"agent_name": "acme--3"}, "held"
        )
        by_action = {item["action"]: item for item in result["actions"]}
        assert by_action["restart"]["available"] is True
        assert by_action["restart"]["detail"] == (
            "same prompt, same name, fresh workspace"
        )
        assert by_action["edit"]["available"] is True
        assert by_action["edit"]["label"] == "Edit"
        assert by_action["dismiss"]["available"] is True
        assert by_action["dismiss"]["detail"] == (
            "snapshot first, then workspace released"
        )

    def test_planner_refusal_disables_restart_but_keeps_dismiss(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sase.agent.hijack.preview as preview_module

        monkeypatch.setattr(
            "sase.agent.hijack.recover_release.restart_availability_reason",
            lambda record: "fanout: fan-out prompt",
        )
        result = preview_module._with_release_rows(
            self._wire(), {"agent_name": "acme--3"}, "held"
        )
        by_action = {item["action"]: item for item in result["actions"]}
        assert by_action["restart"]["available"] is False
        assert "fan-out prompt" in (by_action["restart"]["reason"] or "")
        assert by_action["edit"]["available"] is True
        assert by_action["dismiss"]["available"] is True

    def test_resolving_disables_every_release_row(self) -> None:
        import sase.agent.hijack.preview as preview_module

        result = preview_module._with_release_rows(
            self._wire(), {"agent_name": "acme--3"}, "resolving"
        )
        by_action = {item["action"]: item for item in result["actions"]}
        for name in ("restart", "edit", "dismiss"):
            assert by_action[name]["available"] is False
            assert by_action[name]["reason"] == "already being resolved"

    def test_expired_offers_only_release_actions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sase.agent.hijack.preview as preview_module

        monkeypatch.setattr(
            "sase.agent.hijack.recover_release.restart_availability_reason",
            lambda record: None,
        )
        result = preview_module._with_release_rows(
            self._wire(), {"agent_name": "acme--3"}, "expired"
        )
        by_action = {item["action"]: item for item in result["actions"]}
        for name in ("restart", "edit", "dismiss"):
            assert by_action[name]["available"] is True

    def test_preview_end_to_end_patches_release_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sase.agent.hijack.preview as preview_module

        artifacts = held_artifacts(tmp_path)
        monkeypatch.setattr(
            preview_module,
            "agent_hijack_config",
            lambda: preview_module.AgentHijackConfig(),
        )
        monkeypatch.setattr(preview_module, "build_alias_candidates", lambda ladder: {})
        monkeypatch.setattr(
            preview_module,
            "hijack_escalation_target",
            lambda request: {
                "available": False,
                "kind": None,
                "reason": "no model",
                "concrete": None,
            },
        )

        def assemble(request: dict[str, Any]) -> dict[str, Any]:
            return self._wire(state=request.get("state", "held"))

        monkeypatch.setattr(
            preview_module, "assemble_hijack_recovery_preview", assemble
        )
        monkeypatch.setattr(
            "sase.agent.hijack.recover_release.restart_availability_reason",
            lambda record: None,
        )
        record = make_record(artifacts, artifacts_dir=str(artifacts), state="held")
        preview = preview_module.hijack_recovery_preview(record)
        assert preview.action("restart") is not None
        assert preview.action("restart").available is True  # type: ignore[union-attr]
        assert preview.action("dismiss").available is True  # type: ignore[union-attr]
        assert preview.action("edit").available is True  # type: ignore[union-attr]


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


class TestReleaseCli:
    def _preview(self, **row_overrides: Any) -> ReleasePreview:
        rows = {
            "restart": ReleaseRow("restart", True, None),
            "edit": ReleaseRow("edit", True, None),
            "dismiss": ReleaseRow("dismiss", True, None),
            "escalate": ReleaseRow("escalate", True, None, "t"),
            "continue": ReleaseRow("continue", True, None, "t"),
            "instruct": ReleaseRow("instruct", True, None, "t"),
        }
        rows.update(row_overrides)
        return ReleasePreview(
            revision=7,
            rows=(
                rows["escalate"],
                rows["continue"],
                rows["instruct"],
                rows["restart"],
                rows["edit"],
                rows["dismiss"],
            ),
        )

    def test_recover_restart_routes_to_release_backend(self, capsys: Any) -> None:
        from sase.agents.cli_recover import handle_agents_recover

        calls: dict[str, Any] = {}

        def release(name: str, **kwargs: Any) -> RecoveryResult:
            calls["name"] = name
            calls.update(kwargs)
            return RecoveryResult(
                kind="launched",
                hijack_id="h-123",
                revision=8,
                action="restart",
                successor="acme--3",
                message="Restarted hijacked agent",
            )

        code = handle_agents_recover(
            recover_args(action="restart", json=True),
            preview_fn=lambda _name: self._preview(),
            release_fn=release,
        )
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert calls["action"] == "restart"
        assert calls["prompt"] is None
        assert calls["discard_without_snapshot"] is False
        assert calls["expected_hijack_id"] == "h-123"
        assert calls["expected_revision"] == 7
        assert payload["result"]["kind"] == "launched"
        assert payload["target"] is None

    def test_recover_restart_with_prompt_uses_edit_row_and_passes_prompt(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        from sase.agents.cli_recover import handle_agents_recover

        prompt_file = tmp_path / "edited.md"
        prompt_file.write_text("Do the other thing.\n", encoding="utf-8")
        calls: dict[str, Any] = {}

        def release(name: str, **kwargs: Any) -> RecoveryResult:
            calls.update(kwargs)
            return RecoveryResult(
                kind="launched",
                hijack_id="h-123",
                revision=8,
                action="restart",
                successor="acme--3",
                message="Relaunched",
            )

        preview = ReleasePreview(
            revision=7,
            rows=(
                ReleaseRow("escalate", True, None, "t"),
                ReleaseRow("continue", True, None, "t"),
                ReleaseRow("instruct", True, None, "t"),
                ReleaseRow("restart", False, "fanout: fan-out prompt"),
                ReleaseRow("edit", True, None),
                ReleaseRow("dismiss", True, None),
            ),
        )
        code = handle_agents_recover(
            recover_args(action="restart", prompt_file=str(prompt_file), json=True),
            preview_fn=lambda _name: preview,
            release_fn=release,
        )
        assert code == 0, capsys.readouterr().out
        assert calls["prompt"] == "Do the other thing.\n"

    def test_recover_unavailable_release_row_refuses(self, capsys: Any) -> None:
        from sase.agents.cli_recover import handle_agents_recover

        def never_release(*args: Any, **kwargs: Any) -> RecoveryResult:
            raise AssertionError("unavailable rows must not reach the backend")

        code = handle_agents_recover(
            recover_args(action="dismiss", json=True),
            preview_fn=lambda _name: self._preview(
                dismiss=ReleaseRow("dismiss", False, "already being resolved")
            ),
            release_fn=never_release,
        )
        payload = json.loads(capsys.readouterr().out)
        assert code == 2
        assert payload["error"]["code"] == "action_unavailable"

    def test_recover_release_option_validation(self, capsys: Any) -> None:
        from sase.agents.cli_recover import handle_agents_recover

        def never(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("invalid input must fail before backends")

        cases = [
            recover_args(action="restart", dry_run=True, json=True),
            recover_args(action="restart", model="claude/opus@high", json=True),
            recover_args(action="dismiss", prompt_file="/tmp/x.md", json=True),
            recover_args(action="continue", discard_without_snapshot=True, json=True),
        ]
        for args in cases:
            code = handle_agents_recover(
                args,
                preview_fn=lambda _name: self._preview(),
                recover_fn=never,
                release_fn=never,
            )
            payload = json.loads(capsys.readouterr().out)
            assert code == 2, args
            assert payload["error"]["code"] == "invalid_input", payload

    def test_bare_menu_lists_edit_row(self) -> None:
        import io

        from rich.console import Console

        from sase.agents._recover_render import render_recovery_menu
        from sase.agent.hijack.preview import RecoveryAction, RecoveryPreview

        preview = RecoveryPreview(
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
            actions=(
                RecoveryAction("escalate", True, None, "Escalate", "up", "t"),
                RecoveryAction("continue", True, None, "Continue", "same", "t"),
                RecoveryAction("instruct", True, None, "Instruct", "guide", None),
                RecoveryAction(
                    "restart",
                    True,
                    None,
                    "Restart",
                    "same prompt, same name, fresh workspace",
                    None,
                ),
                RecoveryAction("edit", True, None, "Edit", "edit the prompt", None),
                RecoveryAction(
                    "dismiss", True, None, "Dismiss", "snapshot first", None
                ),
            ),
            state="held",
            _record={},
            _artifacts_dir="/tmp/artifacts",
        )
        buffer = io.StringIO()
        Console(file=buffer, no_color=True, width=100).print(
            render_recovery_menu(preview)
        )
        output = buffer.getvalue()
        assert "START OVER" in output
        assert "Edit" in output
        assert "Dismiss" in output

    def test_actions_constant_covers_release_set(self) -> None:
        assert RELEASE_ACTIONS == frozenset({"dismiss", "restart"})


class TestKillRestartHijackRouting:
    def test_kill_refuses_hijacked_target(
        self, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        import sase.agents.cli_kill as kill_module

        monkeypatch.setattr(
            kill_module,
            "held_record_for_agent",
            lambda name: {"state": "held", "agent_name": name},
        )

        def never_kill(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("hijacked rows must not reach kill")

        monkeypatch.setattr(kill_module, "kill_named_agent", never_kill)
        with pytest.raises(SystemExit) as excinfo:
            kill_module.handle_agents_kill(recover_args(name="acme--3", action=None))
        assert excinfo.value.code == 2
        captured = capsys.readouterr()
        assert "already stopped (hijacked)" in captured.err
        assert "sase agent recover acme--3 -a dismiss" in captured.err

    def test_kill_passes_through_when_not_hijacked(
        self, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        import sase.agents.cli_kill as kill_module
        from sase.agent.running import _KillResult

        monkeypatch.setattr(kill_module, "held_record_for_agent", lambda name: None)
        monkeypatch.setattr(
            kill_module,
            "kill_named_agent",
            lambda name, **kwargs: _KillResult(
                True, f"Killed agent {name!r}", changed=True
            ),
        )
        with pytest.raises(SystemExit) as excinfo:
            kill_module.handle_agents_kill(recover_args(name="acme--3", action=None))
        assert excinfo.value.code == 0

    def test_restart_routes_hijacked_to_release(
        self, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        import sase.agents.cli_restart as restart_module

        monkeypatch.setattr(
            restart_module,
            "held_record_for_agent",
            lambda name: {"state": "held", "agent_name": name},
        )
        calls: dict[str, Any] = {}

        def release(name: str, **kwargs: Any) -> RecoveryResult:
            calls["name"] = name
            calls.update(kwargs)
            return RecoveryResult(
                kind="launched",
                hijack_id="h-123",
                revision=8,
                action="restart",
                successor="acme--3",
                message="Restarted hijacked agent",
            )

        monkeypatch.setattr(
            "sase.agent.hijack.recover_release.recover_release_action", release
        )
        monkeypatch.setattr(
            "sase.agent.hijack.preview.hijack_recovery_preview",
            lambda name: release_preview_for_cli(),
        )
        code = restart_module.handle_agents_restart(
            recover_args(name="acme--3", action=None)
        )
        assert code == 0
        assert calls["action"] == "restart"
        assert "Restarted hijacked agent" in capsys.readouterr().out

    def test_restart_hijacked_dry_run_prints_menu(
        self, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        import io

        from rich.console import Console

        import sase.agents.cli_restart as restart_module

        monkeypatch.setattr(
            restart_module,
            "held_record_for_agent",
            lambda name: {"state": "held", "agent_name": name},
        )
        monkeypatch.setattr(
            "sase.agent.hijack.preview.hijack_recovery_preview",
            lambda name: release_preview_for_cli(),
        )
        buffer = io.StringIO()
        code = restart_module.handle_agents_restart(
            recover_args(name="acme--3", action=None, dry_run=True),
            console=Console(file=buffer, no_color=True, width=100),
        )
        assert code == 0
        assert "acme--3" in buffer.getvalue()


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


class TestPersistRecoverRelease:
    def _request(self, tmp_path: Path, payload: dict[str, Any]) -> tuple[Any, Path]:
        from sase.main.parser import create_parser
        from sase.ops import DurableOperationRequest, write_operation_request
        from sase.ops.names import AGENT_PERSIST_RECOVER

        request_path = tmp_path / "req.json"
        result_path = tmp_path / "res.json"
        write_operation_request(
            request_path,
            DurableOperationRequest(operation=AGENT_PERSIST_RECOVER, payload=payload),
        )
        args = create_parser().parse_args(
            [
                "agent",
                "persist-recover",
                "-Q",
                str(request_path),
                "-R",
                str(result_path),
            ]
        )
        return args, result_path

    def test_persist_recover_dismiss(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.ops import read_operation_result
        from sase.ops.commands.agent import handle_agent_operation

        captured: dict[str, Any] = {}

        def release(name: str, **kwargs: Any) -> RecoveryResult:
            captured["name"] = name
            captured.update(kwargs)
            return RecoveryResult(
                kind="launched",
                hijack_id="h-123",
                revision=8,
                action="dismiss",
                message="Dismissed",
            )

        monkeypatch.setattr(
            "sase.ops.commands._agent_persist_recover.recover_release_action", release
        )
        args, result_path = self._request(
            tmp_path,
            {
                "name": "sase-7f.2",
                "action": "dismiss",
                "expected_hijack_id": "h-123",
                "expected_revision": 7,
                "discard_without_snapshot": True,
            },
        )
        monkeypatch.setenv("SASE_PROC_ID", "proc-release")
        assert handle_agent_operation(args) == 0
        assert captured["action"] == "dismiss"
        assert captured["discard_without_snapshot"] is True
        loaded = read_operation_result(result_path, expected_proc_id="proc-release")
        assert loaded.success is True
        assert loaded.payload["status"] == "launched"

    def test_persist_recover_rejects_bad_action(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.ops import read_operation_result
        from sase.ops.commands.agent import handle_agent_operation

        args, result_path = self._request(
            tmp_path,
            {
                "name": "sase-7f.2",
                "action": "nuke",
                "expected_hijack_id": "h-123",
                "expected_revision": 7,
            },
        )
        monkeypatch.setenv("SASE_PROC_ID", "proc-release")
        assert handle_agent_operation(args) != 0
        loaded = read_operation_result(result_path, expected_proc_id="proc-release")
        assert loaded.success is False
        assert "must be" in (loaded.error or "")
