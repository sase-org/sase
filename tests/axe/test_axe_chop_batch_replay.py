"""Direct replay coverage for persisted ordinary chop batches."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.axe import chop_batch_store
from sase.axe.chop_batch_replay import (
    ChopBatchReplayError,
    replay_ordinary_chop_batch,
)
from sase.core.axe_chop_facade import CHOP_BATCH_SCHEMA_VERSION


def _manifest() -> dict[str, Any]:
    return {
        "schema_version": CHOP_BATCH_SCHEMA_VERSION,
        "batch_id": "ordinary-replay",
        "run": {"routine": "docs", "job": "refresh", "run_id": "ordinary-replay"},
        "members": [
            {
                "source_index": index,
                "proposal_id": f"p{index}",
                "agent_name": f"docs-refresh-{index}",
                "prompt": f"%id:docs-refresh-{index}\nReview {index}.",
                "workspace": "git:sase",
            }
            for index in range(3)
        ],
    }


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


def test_replay_reuses_names_and_dispatches_only_reconciled_missing_member(
    isolated_home: Path,
) -> None:
    chop_batch_store.create_chop_batch("docs", "refresh", _manifest())
    observed = [
        {
            "agent_name": "docs-refresh-0",
            "observation": "matched_spawn",
        },
        {
            "agent_name": "docs-refresh-1",
            "observation": "reservation_only",
        },
        {
            "agent_name": "docs-refresh-2",
            "observation": "foreign_conflict",
        },
    ]
    spawned: list[tuple[str, str]] = []

    def dispatch_member(
        member: dict[str, Any],
        *,
        before_spawn: Any,
        on_spawn_recorded: Any,
    ) -> Any:
        request = SimpleNamespace(
            name_reservation=SimpleNamespace(agent_name=member["agent_name"]),
            extra_env={},
        )
        before_spawn(request)
        result = SimpleNamespace(agent_name=member["agent_name"], pid=1001)
        on_spawn_recorded(result)
        spawned.append((member["agent_name"], member["prompt"]))
        return result

    replay = replay_ordinary_chop_batch(
        "docs",
        "refresh",
        "ordinary-replay",
        observations=observed,
        observations_are_complete=True,
        dispatch_member=dispatch_member,
    )

    batch = chop_batch_store.load_chop_batch("docs", "refresh", "ordinary-replay")
    assert spawned == [
        (
            "docs-refresh-1",
            "%id:docs-refresh-1\nReview 1.",
        )
    ]
    assert replay.already_launched == (0,)
    assert [entry["member_index"] for entry in replay.blocked] == [2]
    assert batch["members"][0]["status"] == "launched"
    assert batch["members"][1]["status"] == "launched"
    assert batch["members"][2]["status"] == "pending"


def test_replay_requires_complete_observations_and_keeps_typed_batches_separate(
    isolated_home: Path,
) -> None:
    chop_batch_store.create_chop_batch("docs", "refresh", _manifest())
    with pytest.raises(ChopBatchReplayError, match="complete spawn observation"):
        replay_ordinary_chop_batch(
            "docs",
            "refresh",
            "ordinary-replay",
            observations=[],
            observations_are_complete=False,
            dispatch_member=lambda *_args, **_kwargs: pytest.fail("must not dispatch"),
        )

    typed = _manifest()
    typed["batch_id"] = "typed-replay"
    typed["typed_bundle"] = {"bundle_id": "bundle-1", "bundle_digest": "digest-1"}
    chop_batch_store.create_chop_batch("docs", "refresh", typed)
    with pytest.raises(ChopBatchReplayError, match="typed adapter"):
        replay_ordinary_chop_batch(
            "docs",
            "refresh",
            "typed-replay",
            observations=[],
            observations_are_complete=True,
            dispatch_member=lambda *_args, **_kwargs: pytest.fail("must not dispatch"),
        )


def test_replay_pause_leaves_unstarted_members_pending(isolated_home: Path) -> None:
    chop_batch_store.create_chop_batch("docs", "refresh", _manifest())
    replay = replay_ordinary_chop_batch(
        "docs",
        "refresh",
        "ordinary-replay",
        observations=[],
        observations_are_complete=True,
        dispatch_member=lambda *_args, **_kwargs: pytest.fail("must not dispatch"),
        pause_requested_fn=lambda: True,
    )
    batch = chop_batch_store.load_chop_batch("docs", "refresh", "ordinary-replay")
    assert replay.paused is True
    assert batch["status"] == "paused"
    assert [member["status"] for member in batch["members"]] == [
        "pending",
        "pending",
        "pending",
    ]
