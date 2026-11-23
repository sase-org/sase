"""Tests for fingerprint-gated followed-epic progress warmup."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import pytest

from sase.ace.tui.models.agent_epic_follow_progress import (
    _EPIC_FOLLOW_PROGRESS_CACHE,
    _EpicFollowProgress,
    cached_epic_follow_progress_snapshot,
    should_resolve_epic_follow_progress,
    warm_epic_follow_progress,
)
from sase.core.wait_epic_follow_view import EpicFollowView
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _clear_follow_progress_cache() -> Iterator[None]:
    _EPIC_FOLLOW_PROGRESS_CACHE.clear()
    yield
    _EPIC_FOLLOW_PROGRESS_CACHE.clear()


def _follow_view(*epic_ids: str) -> EpicFollowView:
    return EpicFollowView(
        target="planner",
        state="following",
        epic_ids=tuple(epic_ids),
        since=1750000000.0,
    )


def _waiting_agent(*epic_ids: str) -> object:
    return make_agent(
        status="WAITING",
        waiting_for=["planner"],
        wait_for_epics_of=["planner"],
        wait_epic_follows=[_follow_view(*epic_ids)],
    )


def _progress(
    _project: str, epic_ids: Iterable[str], closed: int = 2, total: int = 5
) -> dict[str, _EpicFollowProgress | None]:
    return {
        epic_id: _EpicFollowProgress(closed=closed, total=total) for epic_id in epic_ids
    }


def test_warm_reuses_unchanged_store_across_ttl_without_store_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_epic_follow_progress"
        "._follow_progress_project_fingerprint",
        lambda _project: "tok-1",
    )
    calls = 0

    def counting_read(
        project: str, epic_ids: Iterable[str]
    ) -> dict[str, _EpicFollowProgress | None]:
        nonlocal calls
        calls += 1
        assert project == "tmp"
        assert list(epic_ids) == ["sase-7k"]
        return _progress(project, epic_ids)

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_epic_follow_progress._read_epic_follow_progress",
        counting_read,
    )
    agent = _waiting_agent("sase-7k")

    assert warm_epic_follow_progress([agent]) == {agent.identity}  # type: ignore[attr-defined]
    assert calls == 1
    assert should_resolve_epic_follow_progress(agent) is False

    _EPIC_FOLLOW_PROGRESS_CACHE._entries[("tmp", "sase-7k")] = (
        -1.0,
        _EpicFollowProgress(closed=2, total=5),
    )
    assert should_resolve_epic_follow_progress(agent) is True

    assert warm_epic_follow_progress([agent]) == set()
    assert calls == 1
    assert should_resolve_epic_follow_progress(agent) is False
    assert cached_epic_follow_progress_snapshot(agent) == {
        "sase-7k": _EpicFollowProgress(closed=2, total=5)
    }


def test_warm_rereads_when_store_fingerprint_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = ["tok-1"]
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_epic_follow_progress"
        "._follow_progress_project_fingerprint",
        lambda _project: tokens[0],
    )

    def reading(
        project: str, epic_ids: Iterable[str]
    ) -> dict[str, _EpicFollowProgress | None]:
        closed = 2 if tokens[0] == "tok-1" else 3
        return _progress(project, epic_ids, closed=closed)

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_epic_follow_progress._read_epic_follow_progress",
        reading,
    )
    agent = _waiting_agent("sase-7k")

    assert warm_epic_follow_progress([agent]) == {agent.identity}  # type: ignore[attr-defined]

    _EPIC_FOLLOW_PROGRESS_CACHE._entries[("tmp", "sase-7k")] = (
        -1.0,
        _EpicFollowProgress(closed=2, total=5),
    )
    tokens[0] = "tok-2"

    assert warm_epic_follow_progress([agent]) == {agent.identity}  # type: ignore[attr-defined]
    assert cached_epic_follow_progress_snapshot(agent) == {
        "sase-7k": _EpicFollowProgress(closed=3, total=5)
    }


def test_warm_reads_cold_epics_despite_unchanged_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_epic_follow_progress"
        "._follow_progress_project_fingerprint",
        lambda _project: "tok-1",
    )
    calls: list[list[str]] = []

    def reading(
        project: str, epic_ids: Iterable[str]
    ) -> dict[str, _EpicFollowProgress | None]:
        ids = list(epic_ids)
        calls.append(ids)
        return _progress(project, ids, closed=1, total=2)

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_epic_follow_progress._read_epic_follow_progress",
        reading,
    )
    first = _waiting_agent("sase-7k")
    assert warm_epic_follow_progress([first]) == {first.identity}  # type: ignore[attr-defined]
    assert calls == [["sase-7k"]]

    _EPIC_FOLLOW_PROGRESS_CACHE._entries[("tmp", "sase-7k")] = (
        -1.0,
        _EpicFollowProgress(closed=1, total=2),
    )
    second = _waiting_agent("sase-7k", "sase-8k")
    assert warm_epic_follow_progress([second]) == {second.identity}  # type: ignore[attr-defined]
    assert calls == [["sase-7k"], ["sase-8k"]]
    assert cached_epic_follow_progress_snapshot(second) == {
        "sase-7k": _EpicFollowProgress(closed=1, total=2),
        "sase-8k": _EpicFollowProgress(closed=1, total=2),
    }


def test_warm_fingerprint_unknown_fails_open_to_store_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_epic_follow_progress"
        "._follow_progress_project_fingerprint",
        lambda _project: None,
    )
    calls = 0

    def counting_read(
        project: str, epic_ids: Iterable[str]
    ) -> dict[str, _EpicFollowProgress | None]:
        nonlocal calls
        calls += 1
        return _progress(project, epic_ids, closed=0, total=1)

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_epic_follow_progress._read_epic_follow_progress",
        counting_read,
    )
    agent = _waiting_agent("sase-7k")

    assert warm_epic_follow_progress([agent]) == {agent.identity}  # type: ignore[attr-defined]
    _EPIC_FOLLOW_PROGRESS_CACHE._entries[("tmp", "sase-7k")] = (
        -1.0,
        _EpicFollowProgress(closed=0, total=1),
    )
    assert warm_epic_follow_progress([agent]) == set()
    assert calls == 2


def test_warm_missing_store_converges_when_store_appears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = ["MISSING"]
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_epic_follow_progress"
        "._follow_progress_project_fingerprint",
        lambda _project: tokens[0],
    )

    def reading(
        project: str, epic_ids: Iterable[str]
    ) -> dict[str, _EpicFollowProgress | None]:
        if tokens[0] == "MISSING":
            return {}
        return _progress(project, epic_ids, closed=4, total=4)

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_epic_follow_progress._read_epic_follow_progress",
        reading,
    )
    agent = _waiting_agent("sase-7k")

    # A missing store leaves the lane blank, exactly like a cold cache, so no
    # visible change is reported; the MISSING token is still recorded.
    assert warm_epic_follow_progress([agent]) == set()
    assert cached_epic_follow_progress_snapshot(agent) == {"sase-7k": None}

    _EPIC_FOLLOW_PROGRESS_CACHE._entries[("tmp", "sase-7k")] = (-1.0, None)
    tokens[0] = "tok-new"
    assert warm_epic_follow_progress([agent]) == {agent.identity}  # type: ignore[attr-defined]
    assert cached_epic_follow_progress_snapshot(agent) == {
        "sase-7k": _EpicFollowProgress(closed=4, total=4)
    }


def test_follow_fingerprint_map_stays_bounded() -> None:
    for index in range(300):
        _EPIC_FOLLOW_PROGRESS_CACHE.set_fingerprint(f"proj-{index}", "tok")
    assert len(_EPIC_FOLLOW_PROGRESS_CACHE._fingerprints) <= 256
    assert _EPIC_FOLLOW_PROGRESS_CACHE.fingerprint_for("proj-299") == "tok"


def test_follow_fingerprint_cache_cleared_with_entries() -> None:
    _EPIC_FOLLOW_PROGRESS_CACHE.set(
        ("tmp", "sase-7k"), _EpicFollowProgress(closed=1, total=2)
    )
    _EPIC_FOLLOW_PROGRESS_CACHE.set_fingerprint("tmp", "tok-1")
    assert _EPIC_FOLLOW_PROGRESS_CACHE.fingerprint_for("tmp") == "tok-1"
    _EPIC_FOLLOW_PROGRESS_CACHE.clear()
    assert _EPIC_FOLLOW_PROGRESS_CACHE.fingerprint_for("tmp") is None
