"""Tests for cached waited-for bead status resolution."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from sase.ace.tui.models.agent_wait_beads import (
    _WAIT_BEAD_STATUS_CACHE,
    resolve_wait_bead_statuses,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _clear_wait_bead_status_cache() -> Iterator[None]:
    _WAIT_BEAD_STATUS_CACHE.clear()
    yield
    _WAIT_BEAD_STATUS_CACHE.clear()


def test_agent_without_bead_wait_performs_no_store_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def lookup(_project: str, _bead_ids: list[str]) -> dict[str, str] | None:
        nonlocal calls
        calls += 1
        return {}

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_wait_beads.bead_statuses_for_project",
        lookup,
    )

    assert resolve_wait_bead_statuses(make_agent()) is None
    assert calls == 0


def test_two_resolves_inside_ttl_use_one_store_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def lookup(_project: str, bead_ids: list[str]) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return dict.fromkeys(bead_ids, "closed")

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_wait_beads.bead_statuses_for_project",
        lookup,
    )
    agent = make_agent(waiting_for_beads=["sase-1"])

    expected = (("sase-1", "closed"),)
    assert resolve_wait_bead_statuses(agent) == expected
    assert resolve_wait_bead_statuses(agent) == expected
    assert calls == 1


def test_multiple_beads_are_resolved_in_one_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def lookup(_project: str, bead_ids: list[str]) -> dict[str, str]:
        calls.append(bead_ids)
        return dict.fromkeys(bead_ids, "open")

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_wait_beads.bead_statuses_for_project",
        lookup,
    )
    agent = make_agent(waiting_for_beads=["a", "b", "c"])

    assert resolve_wait_bead_statuses(agent) == (
        ("a", "open"),
        ("b", "open"),
        ("c", "open"),
    )
    assert calls == [["a", "b", "c"]]


def test_unavailable_store_result_is_negatively_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def lookup(_project: str, _bead_ids: list[str]) -> None:
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_wait_beads.bead_statuses_for_project",
        lookup,
    )
    agent = make_agent(waiting_for_beads=["a", "b"])

    expected = (("a", None), ("b", None))
    assert resolve_wait_bead_statuses(agent) == expected
    assert resolve_wait_bead_statuses(agent) == expected
    assert calls == 1


def test_wait_display_source_owns_beads_and_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def lookup(project: str, bead_ids: list[str]) -> dict[str, str]:
        calls.append((project, bead_ids))
        return dict.fromkeys(bead_ids, "claimed")

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_wait_beads.bead_statuses_for_project",
        lookup,
    )
    root = make_agent(
        project_file="/projects/root/root.sase",
        waiting_for_beads=["root-bead"],
    )
    child = make_agent(
        project_file="/projects/child/child.sase",
        waiting_for_beads=["child-bead"],
    )
    root.wait_display_source = child

    assert resolve_wait_bead_statuses(root) == (("child-bead", "claimed"),)
    assert calls == [("child", ["child-bead"])]
