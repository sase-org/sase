"""Snapshot gate tests for hijack release recovery."""

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
    recover_release_action,
    restart_availability_reason,
    restart_replacement_conflicts,
)
from tests._agent_hijack_recover_helpers import record as make_record
from tests._agent_hijack_recover_helpers import subject as make_subject


from tests._agent_hijack_recover_release_support import (
    ReleaseLedger,
    ReleasePreview,
    ReleaseRow,
    held_artifacts,
    install_release_ledger,
    recover_args,
    record_for,
    release_deps,
    release_preview,
    release_preview_for_cli,
    release_subject,
)


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
