"""Phase 5 lazy attempt-history tests for ``sase-3r``.

These tests pin the Phase 5 contract from
``sdd/epics/202605/fast_agents_tab_disk_load.md`` (bead ``sase-3r.5``):

* Normal Agents-tab refreshes do NOT walk per-agent ``attempts/<N>/``
  directories — :attr:`Agent.attempt_history` is left empty for every
  row.
* Explicit full-history refreshes (revive/archive/repair) still hydrate
  attempt history up-front for the content-search / dismissed-bundle
  paths that consume it.
* :func:`hydrate_attempt_history_for` reads attempt history for one
  selected agent on demand and uses the snapshot cache so repeat calls
  in steady state do not re-walk.
* The content-search cache exposes an explicit ``"inbox"`` /
  ``"archive"`` mode split — inbox mode never opens attempt reply
  files, archive mode does.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._loading_helpers import (
    hydrate_attempt_history_for,
    load_agents_from_disk_with_state,
)
from sase.ace.tui.actions.agents._snapshot_cache import AgentSnapshotCache
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_attempt import AttemptRecord
from sase.ace.tui.models.agent_content_search import AgentContentSearchCache
from sase.ace.tui.models.agent_loader import AgentLoadState


def _write_attempt(artifacts_dir: Path, n: int) -> None:
    sub = artifacts_dir / "attempts" / f"{n:02d}"
    sub.mkdir(parents=True, exist_ok=True)
    meta = {
        "attempt_number": n,
        "status": "failed",
        "start_epoch": 100.0 + n,
        "end_epoch": 150.0 + n,
        "model": "claude-sonnet-4-5",
        "used_fallback": False,
        "error_snippet": "boom",
        "error_full": "boom full",
    }
    (sub / "attempt_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (sub / "live_reply.md").write_text(
        f"archive-only secret token attempt {n}", encoding="utf-8"
    )
    (sub / "live_reply_timestamps.jsonl").write_text("", encoding="utf-8")


def _make_agent(artifacts_dir: str | None = None) -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/tmp/proj.sase",
        status="DONE",
        start_time=None,
        artifacts_dir=artifacts_dir,
    )
    return agent


def _load_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )


# ---------------------------------------------------------------------------
# Loader: lazy attempt history
# ---------------------------------------------------------------------------


def test_normal_load_does_not_hydrate_attempt_history(tmp_path: Path) -> None:
    """Default load leaves ``attempt_history`` empty for every agent."""

    artifacts_dir = tmp_path / "agent"
    artifacts_dir.mkdir()
    _write_attempt(artifacts_dir, 1)
    _write_attempt(artifacts_dir, 2)

    agent = _make_agent(str(artifacts_dir))

    with (
        patch(
            "sase.ace.tui.models.agent_loader.load_tiered_agents",
            return_value=([agent], _load_state()),
        ),
        patch("sase.ace.agent_tags.load_agent_tags", return_value={}),
        patch.object(
            AgentSnapshotCache,
            "attempt_history_for",
            autospec=True,
        ) as spy,
    ):
        result = load_agents_from_disk_with_state(set())

    spy.assert_not_called()
    assert result.all_agents == [agent]
    assert agent.attempt_history == []


def test_full_history_load_hydrates_attempt_history(tmp_path: Path) -> None:
    """Explicit full-history loads still populate attempt history up-front."""

    artifacts_dir = tmp_path / "agent"
    artifacts_dir.mkdir()
    _write_attempt(artifacts_dir, 1)

    agent = _make_agent(str(artifacts_dir))

    with (
        patch(
            "sase.ace.tui.models.agent_loader.load_tiered_agents",
            return_value=([agent], _load_state()),
        ),
        patch("sase.ace.agent_tags.load_agent_tags", return_value={}),
    ):
        result = load_agents_from_disk_with_state(set(), full_history=True)

    assert result.all_agents == [agent]
    assert [r.attempt_number for r in agent.attempt_history] == [1]


def test_hydrate_attempt_history_for_selected_agent_only(tmp_path: Path) -> None:
    """``hydrate_attempt_history_for`` populates one agent without touching others."""

    selected_dir = tmp_path / "selected"
    selected_dir.mkdir()
    _write_attempt(selected_dir, 1)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    _write_attempt(other_dir, 7)

    selected = _make_agent(str(selected_dir))
    other = _make_agent(str(other_dir))

    real_attempt_history_for = AgentSnapshotCache.attempt_history_for
    calls: list[str | None] = []

    def tracking(self: AgentSnapshotCache, path: str | None) -> list[AttemptRecord]:
        calls.append(path)
        return real_attempt_history_for(self, path)

    with patch.object(
        AgentSnapshotCache, "attempt_history_for", autospec=True, side_effect=tracking
    ):
        hydrate_attempt_history_for(selected)

    assert calls == [str(selected_dir)]
    assert [r.attempt_number for r in selected.attempt_history] == [1]
    assert other.attempt_history == []


def test_hydrate_attempt_history_for_no_artifacts_dir_is_noop() -> None:
    """Agents without an artifacts directory do not trigger any cache call."""

    agent = _make_agent(None)

    with patch.object(AgentSnapshotCache, "attempt_history_for", autospec=True) as spy:
        hydrate_attempt_history_for(agent)

    spy.assert_not_called()
    assert agent.attempt_history == []


# ---------------------------------------------------------------------------
# Content search: inbox vs archive mode split
# ---------------------------------------------------------------------------


def _attempt_record(path: str) -> AttemptRecord:
    return AttemptRecord(
        attempt_number=1,
        status="failed",
        start_epoch=0.0,
        end_epoch=0.0,
        model=None,
        used_fallback=False,
        error_snippet="",
        error_full="",
        live_reply_path=path,
        timestamps_path=path + ".ts",
    )


def test_content_search_inbox_mode_skips_attempt_paths(tmp_path: Path) -> None:
    """Inbox-mode haystacks ignore ``attempt_history`` live-reply files."""

    artifacts_dir = tmp_path / "agent"
    artifacts_dir.mkdir()
    (artifacts_dir / "raw_xprompt.md").write_text("prompt text", encoding="utf-8")
    (artifacts_dir / "live_reply.md").write_text("reply text", encoding="utf-8")
    attempt_reply = artifacts_dir / "attempts" / "01" / "live_reply.md"
    attempt_reply.parent.mkdir(parents=True)
    attempt_reply.write_text("archive-only marker", encoding="utf-8")

    agent = _make_agent(str(artifacts_dir))
    agent.attempt_history = [_attempt_record(str(attempt_reply))]

    cache = AgentContentSearchCache()
    assert cache.mode == "inbox"
    haystack = cache.get_haystack(agent)
    assert "prompt text" in haystack
    assert "reply text" in haystack
    assert "archive-only marker" not in haystack


def test_content_search_archive_mode_includes_attempt_paths(tmp_path: Path) -> None:
    """Archive-mode haystacks include ``attempt_history`` live replies."""

    artifacts_dir = tmp_path / "agent"
    artifacts_dir.mkdir()
    (artifacts_dir / "raw_xprompt.md").write_text("prompt text", encoding="utf-8")
    (artifacts_dir / "live_reply.md").write_text("reply text", encoding="utf-8")
    attempt_reply = artifacts_dir / "attempts" / "01" / "live_reply.md"
    attempt_reply.parent.mkdir(parents=True)
    attempt_reply.write_text("archive-only marker", encoding="utf-8")

    agent = _make_agent(str(artifacts_dir))
    agent.attempt_history = [_attempt_record(str(attempt_reply))]

    cache = AgentContentSearchCache(mode="archive")
    haystack = cache.get_haystack(agent)
    assert "archive-only marker" in haystack

    inbox_cache = AgentContentSearchCache()
    inbox_haystack = inbox_cache.get_haystack(agent, mode="archive")
    assert "archive-only marker" in inbox_haystack


def test_content_search_build_index_propagates_mode(tmp_path: Path) -> None:
    """``build_index`` honors a per-call mode override."""

    artifacts_dir = tmp_path / "agent"
    artifacts_dir.mkdir()
    (artifacts_dir / "raw_xprompt.md").write_text("prompt text", encoding="utf-8")
    attempt_reply = artifacts_dir / "attempts" / "01" / "live_reply.md"
    attempt_reply.parent.mkdir(parents=True)
    attempt_reply.write_text("archive-only marker", encoding="utf-8")

    agent = _make_agent(str(artifacts_dir))
    agent.attempt_history = [_attempt_record(str(attempt_reply))]

    cache = AgentContentSearchCache()
    inbox_index = cache.build_index([agent])
    assert "archive-only marker" not in inbox_index.get_haystack(agent)

    archive_index = cache.build_index([agent], mode="archive")
    assert "archive-only marker" in archive_index.get_haystack(agent)


def test_content_search_fork_preserves_mode() -> None:
    """``fork`` carries the cache mode into the worker snapshot."""

    cache = AgentContentSearchCache(mode="archive")
    clone = cache.fork()
    assert clone.mode == "archive"
