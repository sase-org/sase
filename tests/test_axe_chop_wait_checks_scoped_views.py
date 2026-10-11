"""Scoped resolving and confirmation views for the wait_checks chop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import sase.scripts._chop_wait_checks_run as wait_checks
from sase.core.wait_dependency_resolution import WaitDependencyIndex
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks


def _spy_add_many(
    monkeypatch: pytest.MonkeyPatch,
) -> list[list[Path]]:
    captured: list[list[Path]] = []
    original = WaitDependencyIndex.add_many

    def _add_many(
        self: WaitDependencyIndex,
        artifacts: Any,
    ) -> None:
        rows = list(artifacts)
        captured.append([artifact_dir for artifact_dir, _meta, _project in rows])
        original(self, rows)

    monkeypatch.setattr(WaitDependencyIndex, "add_many", _add_many)
    return captured


def test_mixed_scopable_and_unscopable_waiters_use_both_views(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    named_waiter = make_waiting_agent(tmp_path, "foo", suffix="named")
    tribe_waiter = make_waiting_agent(tmp_path, "@missing-tribe", suffix="tribe")
    foo_dir = make_agent(
        tmp_path,
        "proj",
        "20261011010101",
        "foo",
        done=True,
        outcome="completed",
    )
    unrelated_dir = make_agent(
        tmp_path,
        "proj",
        "20261011010102",
        "zzz",
        done=True,
        outcome="completed",
    )
    captured = _spy_add_many(monkeypatch)

    run_wait_checks(tmp_path, monkeypatch)

    assert json.loads((named_waiter / "ready.json").read_text(encoding="utf-8")) == {
        "resolved_deps": ["foo"],
        "released_by": "wait_checks",
    }
    assert not (tribe_waiter / "ready.json").exists()
    out = capsys.readouterr().out
    assert "scoped_waiters=1" in out
    assert "full_view_waiters=1" in out

    resolving_calls = captured[:2]
    assert [set(dirs) for dirs in resolving_calls] == [
        {foo_dir},
        {foo_dir, unrelated_dir},
    ]


def test_stale_resolving_view_defers_when_newer_failed_run_appears(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20261011020101",
        "foo",
        done=True,
        outcome="completed",
    )
    failed_dir = make_agent(
        tmp_path,
        "proj",
        "20261011020102",
        "foo",
        done=True,
        outcome="failed",
    )
    real_rows = wait_checks._filesystem_dependency_rows

    def _rows(
        projects_dir: Path,
        *,
        project_names: set[str] | None = None,
        meta_cache: dict[Path, dict[str, Any] | None] | None = None,
    ) -> list[tuple[Path, dict[str, Any], str]]:
        rows = real_rows(
            projects_dir, project_names=project_names, meta_cache=meta_cache
        )
        if project_names is None:
            return [row for row in rows if row[0] != failed_dir]
        return rows

    monkeypatch.setattr(wait_checks, "_filesystem_dependency_rows", _rows)

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()
    out = capsys.readouterr().out
    assert "deferred_unconfirmed=1" in out
    assert "scoped_waiters=1" in out
    assert "full_view_waiters=0" in out
    assert "Deferred release for waiter-cl" in out


def test_bead_only_waiter_uses_the_scoped_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, wait_for_beads=["sase-missing"])
    make_agent(
        tmp_path,
        "proj",
        "20261011030101",
        "unrelated",
        done=True,
        outcome="completed",
    )
    captured = _spy_add_many(monkeypatch)

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()
    out = capsys.readouterr().out
    assert "scoped_waiters=1" in out
    assert "full_view_waiters=0" in out
    # Bead-only markers contribute no identity keys, so the resolving view
    # keeps only the waiter directory — and this helper writes no meta there.
    assert captured
    assert captured[0] == []
