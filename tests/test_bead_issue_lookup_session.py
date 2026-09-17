"""Tests for batched bead issue lookup sessions."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from sase.agent.bead_display import BeadIssueLookupSession
from sase.bead.model import Issue


class _FakeBeadProject:
    issues: ClassVar[list[Issue]] = []
    list_calls: ClassVar[int] = 0

    def __init__(self, _root: Path, *, beads_dirname: str) -> None:
        del beads_dirname

    def __enter__(self) -> _FakeBeadProject:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        pass

    def list_issues(self) -> list[Issue]:
        type(self).list_calls += 1
        return list(type(self).issues)


@pytest.fixture(autouse=True)
def _fake_bead_project(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeBeadProject.issues = []
    _FakeBeadProject.list_calls = 0
    monkeypatch.setattr("sase.bead.project.BeadProject", _FakeBeadProject)


def test_lookup_session_indexes_one_store_once_for_many_candidates(
    tmp_path: Path,
) -> None:
    beads_dir = tmp_path / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    first = Issue("sase-124.1", "one")
    second = Issue("sase-124.2", "two")
    _FakeBeadProject.issues = [first, second]

    with BeadIssueLookupSession() as session:
        assert session.lookup("sase-124.1", [beads_dir]) is first
        assert session.lookup("sase-124.2", [beads_dir]) is second
        assert session.lookup("124.1", [beads_dir]) is first

    assert _FakeBeadProject.list_calls == 1


def test_lookup_session_ambiguous_suffix_fails_closed(tmp_path: Path) -> None:
    beads_dir = tmp_path / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    _FakeBeadProject.issues = [
        Issue("sase-124.1", "one"),
        Issue("other-124.1", "other"),
    ]

    with BeadIssueLookupSession() as session:
        assert session.lookup("124.1", [beads_dir]) is None
        assert session.lookup("sase-124.1", [beads_dir]) is _FakeBeadProject.issues[0]

    assert _FakeBeadProject.list_calls == 1
