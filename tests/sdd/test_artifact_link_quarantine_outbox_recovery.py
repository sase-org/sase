"""Unsafe quarantine paths cannot settle outbox entries before safe retry."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_event_canonical import canonical_artifact_link_event_object
from sase.sdd.artifact_link_event_publisher import publish_artifact_link_events
from sase.sdd.artifact_link_outbox import (
    append_artifact_link_outbox_event,
    drain_artifact_link_outbox,
    read_artifact_link_outbox_entries,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_event_store_test_helpers import (
    PROJECT_KEY,
    edge_event,
)
from tests.sdd._artifact_link_store_helpers import allow_machine_sidecar_writes


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(root: Path) -> None:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "SASE Tests")
    _git(root, "config", "user.email", "sase@example.test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "doc.md").write_text("# Doc\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "initial")


def _digest(event: dict[str, object]) -> str:
    return str(require_rust_binding("artifact_link_event_digest")(event))


def test_quarantine_path_failure_keeps_loser_for_repaired_restart_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.sdd import _artifact_link_event_install as install_module

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    _init_repo(repo)
    store = ArtifactLinkStore(project_key=PROJECT_KEY, sidecar_roots={"plan": repo})

    operation_id = "d" * 32
    winner = edge_event(
        operation_id,
        target="plan:202610/durable-winner.md",
        description="durable winner",
    )
    replay = edge_event(
        operation_id,
        target="plan:202610/conflicting-replay.md",
        description="colliding replay",
        origin="derived",
    )
    fresh = edge_event(
        "e" * 32,
        target="plan:202610/fresh-observation.md",
        description="unrelated fresh observation",
        origin="derived",
    )
    publish_artifact_link_events(
        store,
        (winner,),
        push_after_commit=False,
        mutation_origin="machine",
    )
    winner_object = canonical_artifact_link_event_object(winner)
    winner_path = repo / winner_object.relative_path
    winner_bytes = winner_path.read_bytes()
    replay_object = canonical_artifact_link_event_object(replay)
    replay_path = repo / replay_object.relative_path
    for event in (replay, fresh):
        append_artifact_link_outbox_event(
            project_key=PROJECT_KEY,
            agent_name="sase",
            run_id="quarantine-recovery",
            event=event,
        )

    outside = tmp_path / "outside"
    outside.mkdir()
    quarantine_root = repo / "link-events" / "quarantine" / "v1"
    quarantine_root.mkdir(parents=True)
    (quarantine_root / ".staging").symlink_to(outside, target_is_directory=True)
    outside_creates: list[Path] = []
    real_open = install_module.os.open

    def observe_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
        resolved = Path(path).resolve(strict=False)
        if flags & install_module.os.O_CREAT and resolved.is_relative_to(outside):
            outside_creates.append(resolved)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(install_module.os, "open", observe_open)
    with pytest.raises(RuntimeError, match="invalid"):
        drain_artifact_link_outbox(
            store=store,
            drop_stale_terminal=False,
            push_after_commit=False,
        )
    assert outside_creates == []
    assert list(outside.iterdir()) == []
    assert not replay_path.exists()
    assert list(quarantine_root.rglob("*.json")) == []
    queued = read_artifact_link_outbox_entries(PROJECT_KEY)
    assert {(entry.id, _digest(entry.event)) for entry in queued} == {
        (operation_id, replay_object.digest),
        ("e" * 32, _digest(fresh)),
    }
    assert winner_path.read_bytes() == winner_bytes

    (quarantine_root / ".staging").unlink()
    (quarantine_root / ".staging").mkdir()
    repaired = drain_artifact_link_outbox(
        store=store,
        drop_stale_terminal=False,
        push_after_commit=False,
    )
    assert repaired.quarantined == 1
    assert repaired.drained == 1
    assert repaired.retained == 0
    assert len(list(quarantine_root.rglob("*.json"))) == 1
    assert read_artifact_link_outbox_entries(PROJECT_KEY) == ()
    assert winner_path.read_bytes() == winner_bytes

    restarted = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": repo},
    )
    idle = drain_artifact_link_outbox(
        store=restarted,
        drop_stale_terminal=False,
        push_after_commit=False,
    )
    assert idle.queued == 0
    snapshot = restarted.artifact_link_event_snapshot(strict=True)
    fresh_digest = _digest(fresh)
    assert (
        sum(1 for event in snapshot.durable_events if _digest(event) == fresh_digest)
        == 1
    )
    fresh_rows = [
        row
        for row in snapshot.rows
        if row.get("target_ref") == "plan:202610/fresh-observation.md"
    ]
    assert len(fresh_rows) == 1
    assert fresh_rows[0]["uses"] == 1
    assert winner_path.read_bytes() == winner_bytes
    assert _git(repo, "status", "--porcelain") == ""
