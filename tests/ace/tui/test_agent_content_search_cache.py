"""Tests for ``AgentContentSearchCache`` and the content-aware ``/`` filter."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_content_search import (
    AgentContentSearchCache,
    AgentContentSearchIndex,
)


def _make_agent(artifacts_dir: Path, **overrides: object) -> Agent:
    """Build a minimal ``Agent`` pointing at a filesystem artifacts dir."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "cl_zero",
        "project_file": "/tmp/projects/proj/proj.sase",
        "status": "RUNNING",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": "20240101120000",
        "artifacts_dir": str(artifacts_dir),
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def test_haystack_includes_prompt_and_reply(tmp_path: Path) -> None:
    (tmp_path / "raw_xprompt.md").write_text(
        "Explain CONNECTION timeouts", encoding="utf-8"
    )
    (tmp_path / "live_reply.md").write_text(
        "A Flaky TEST is a test that sometimes fails", encoding="utf-8"
    )
    agent = _make_agent(tmp_path)

    cache = AgentContentSearchCache()
    haystack = cache.get_haystack(agent)

    assert "connection timeouts" in haystack  # lowercased
    assert "flaky test" in haystack


def test_no_artifacts_dir_returns_empty_haystack(tmp_path: Path) -> None:
    agent = _make_agent(tmp_path / "does_not_exist")
    cache = AgentContentSearchCache()
    assert cache.get_haystack(agent) == ""


def test_cache_reuses_entry_when_mtime_unchanged(tmp_path: Path) -> None:
    reply = tmp_path / "live_reply.md"
    reply.write_text("hello world", encoding="utf-8")
    agent = _make_agent(tmp_path)

    cache = AgentContentSearchCache()
    cache.get_haystack(agent)

    # Simulate a disk read by replacing file content but keeping mtime_ns
    # identical. The cache must return the original content.
    st = os.stat(reply)
    reply.write_text("NEW CONTENT", encoding="utf-8")
    os.utime(reply, ns=(st.st_atime_ns, st.st_mtime_ns))

    haystack = cache.get_haystack(agent)
    assert "hello world" in haystack
    assert "new content" not in haystack


def test_cache_refreshes_when_mtime_changes(tmp_path: Path) -> None:
    reply = tmp_path / "live_reply.md"
    reply.write_text("hello", encoding="utf-8")
    agent = _make_agent(tmp_path)

    cache = AgentContentSearchCache()
    assert "hello" in cache.get_haystack(agent)

    # Bump mtime by writing a newer payload — cache must re-read.
    reply.write_text("fresh data", encoding="utf-8")
    st = os.stat(reply)
    os.utime(reply, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    haystack = cache.get_haystack(agent)
    assert "fresh data" in haystack


def test_missing_file_is_tolerated(tmp_path: Path) -> None:
    # Only xprompt exists, no reply.
    (tmp_path / "raw_xprompt.md").write_text("Just the prompt", encoding="utf-8")
    agent = _make_agent(tmp_path)

    cache = AgentContentSearchCache()
    haystack = cache.get_haystack(agent)
    assert "just the prompt" in haystack


def test_size_cap_limits_cached_content(tmp_path: Path, monkeypatch) -> None:
    from sase.ace.tui.models import agent_content_search

    monkeypatch.setattr(agent_content_search, "_MAX_BYTES_PER_FILE", 16)
    (tmp_path / "live_reply.md").write_text("A" * 100 + "needle", encoding="utf-8")
    agent = _make_agent(tmp_path)

    cache = AgentContentSearchCache()
    haystack = cache.get_haystack(agent)
    # Only the first 16 bytes were read, so the needle after position 100
    # must not appear in the haystack.
    assert "needle" not in haystack
    assert len(haystack) <= 16


def test_prune_drops_entries_for_missing_agents(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_a.mkdir()
    (dir_a / "live_reply.md").write_text("alpha", encoding="utf-8")
    dir_b = tmp_path / "b"
    dir_b.mkdir()
    (dir_b / "live_reply.md").write_text("bravo", encoding="utf-8")

    agent_a = _make_agent(dir_a, cl_name="cl_a", raw_suffix="20240101120001")
    agent_b = _make_agent(dir_b, cl_name="cl_b", raw_suffix="20240101120002")

    cache = AgentContentSearchCache()
    cache.get_haystack(agent_a)
    cache.get_haystack(agent_b)
    assert len(cache._cache) == 2

    # Only agent_a is still active -- agent_b's entry must be dropped.
    cache.prune([agent_a])
    cached_paths = set(cache._cache)
    assert str(dir_a / "live_reply.md") in cached_paths
    assert str(dir_b / "live_reply.md") not in cached_paths


def test_haystack_includes_attempt_replies(tmp_path: Path) -> None:
    from sase.ace.tui.models.agent import AttemptRecord

    attempt_dir = tmp_path / "attempts" / "01"
    attempt_dir.mkdir(parents=True)
    (attempt_dir / "live_reply.md").write_text(
        "Prior ATTEMPT said FOO", encoding="utf-8"
    )

    agent = _make_agent(tmp_path)
    agent.attempt_history = [
        AttemptRecord(
            attempt_number=1,
            status="failed",
            start_epoch=0.0,
            end_epoch=1.0,
            model=None,
            used_fallback=False,
            error_snippet="",
            error_full="",
            live_reply_path=str(attempt_dir / "live_reply.md"),
            timestamps_path=str(attempt_dir / "live_reply_timestamps.jsonl"),
        )
    ]

    cache = AgentContentSearchCache()
    haystack = cache.get_haystack(agent)
    assert "prior attempt said foo" in haystack


def test_haystack_includes_chat_path_fallback(tmp_path: Path) -> None:
    chat_path = tmp_path / "chat.md"
    chat_path.write_text("CHAT ONLY CONTENT", encoding="utf-8")
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"chat_path": str(chat_path)}), encoding="utf-8"
    )
    agent = _make_agent(tmp_path)

    cache = AgentContentSearchCache()
    haystack = cache.get_haystack(agent)
    assert "chat only content" in haystack


def test_build_index_includes_all_agent_content_sources(tmp_path: Path) -> None:
    from sase.ace.tui.models.agent import AttemptRecord

    chat_path = tmp_path / "chat.md"
    chat_path.write_text("CHAT FALLBACK", encoding="utf-8")
    attempt_dir = tmp_path / "attempts" / "01"
    attempt_dir.mkdir(parents=True)
    attempt_path = attempt_dir / "live_reply.md"
    attempt_path.write_text("ATTEMPT REPLY", encoding="utf-8")
    response_path = tmp_path / "response.md"
    response_path.write_text("FINAL RESPONSE", encoding="utf-8")
    (tmp_path / "raw_xprompt.md").write_text("PROMPT BODY", encoding="utf-8")
    (tmp_path / "live_reply.md").write_text("LIVE REPLY", encoding="utf-8")
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"chat_path": str(chat_path)}), encoding="utf-8"
    )
    agent = _make_agent(tmp_path, response_path=str(response_path))
    agent.attempt_history = [
        AttemptRecord(
            attempt_number=1,
            status="failed",
            start_epoch=0.0,
            end_epoch=1.0,
            model=None,
            used_fallback=False,
            error_snippet="",
            error_full="",
            live_reply_path=str(attempt_path),
            timestamps_path=str(attempt_dir / "live_reply_timestamps.jsonl"),
        )
    ]

    index = AgentContentSearchCache().build_index([agent])
    haystack = index.get_haystack(agent)

    assert "prompt body" in haystack
    assert "live reply" in haystack
    assert "chat fallback" in haystack
    assert "final response" in haystack
    assert "attempt reply" in haystack


def test_index_serves_haystacks_without_file_cache_reads(tmp_path: Path) -> None:
    (tmp_path / "live_reply.md").write_text("INDEXED NEEDLE", encoding="utf-8")
    agent = _make_agent(tmp_path)
    cache = AgentContentSearchCache()
    index = cache.build_index([agent])

    def fail_get_haystack(_agent: Agent) -> str:
        raise AssertionError("file-backed cache should not be consulted")

    cache.get_haystack = fail_get_haystack  # type: ignore[method-assign]

    assert index.get_haystack(agent) == "indexed needle"


def test_cache_fork_populate_and_merge(tmp_path: Path) -> None:
    (tmp_path / "live_reply.md").write_text("WORKER TEXT", encoding="utf-8")
    agent = _make_agent(tmp_path)
    ui_cache = AgentContentSearchCache()
    worker_cache = ui_cache.fork()

    index = worker_cache.build_index([agent])
    assert isinstance(index, AgentContentSearchIndex)
    assert ui_cache._cache == {}

    ui_cache.merge(worker_cache)

    assert str(tmp_path / "live_reply.md") in ui_cache._cache
    assert "worker text" in index.get_haystack(agent)


def test_substring_match_semantics(tmp_path: Path) -> None:
    """Matches are case-insensitive substring matches on the haystack."""
    (tmp_path / "live_reply.md").write_text(
        "Encountered a CONNECTION Timeout while fetching", encoding="utf-8"
    )
    agent = _make_agent(tmp_path)
    cache = AgentContentSearchCache()
    haystack = cache.get_haystack(agent)

    # Matches regardless of input casing (caller lowers query before comparing).
    assert "connection timeout" in haystack
    # Phrases that don't appear do not match.
    assert "flaky test" not in haystack
