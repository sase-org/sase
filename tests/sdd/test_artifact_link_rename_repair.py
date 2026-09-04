"""Historical artifact-link rename repair: per-kind memoization and deadlines."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sase.sdd._artifact_link_renames import repair_historical_artifact_renames
from tests.sdd._artifact_link_store_helpers import _store

_PLAN_REFS = (
    "plan:202608/a.md",
    "plan:202608/b.md",
    "plan:202608/c.md",
)
_RESEARCH_REFS = (
    "research:202608/d.md",
    "research:202608/e.md",
)
_ELIGIBLE_REFS = (*_PLAN_REFS, *_RESEARCH_REFS)


def test_repair_scans_rename_history_once_per_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    calls: list[str] = []

    def _fake_map(_root: Path, *, kind: str) -> dict[str, str]:
        calls.append(kind)
        return {}

    monkeypatch.setattr(
        "sase.sdd._artifact_link_renames._historical_rename_map",
        _fake_map,
    )

    report = repair_historical_artifact_renames(store, _ELIGIBLE_REFS)

    assert calls == ["plan", "research"]
    assert report.deferred_refs == 0
    assert report.renames == ()


def test_repair_deadline_defers_unexamined_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    calls: list[str] = []

    def _fake_map(_root: Path, *, kind: str) -> dict[str, str]:
        calls.append(kind)
        return {}

    monkeypatch.setattr(
        "sase.sdd._artifact_link_renames._historical_rename_map",
        _fake_map,
    )

    expired = repair_historical_artifact_renames(
        store, _ELIGIBLE_REFS, deadline=time.monotonic() - 1.0
    )
    assert calls == []
    assert expired.deferred_refs == len(_ELIGIBLE_REFS)
    assert expired.renames == ()

    unbounded = repair_historical_artifact_renames(store, _ELIGIBLE_REFS)
    assert calls == ["plan", "research"]
    assert unbounded.deferred_refs == 0


def test_repair_applies_renames_resolved_before_deadline_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    plans = store.sidecar_roots["plan"]
    new_path = plans / "202608" / "new.md"
    new_path.parent.mkdir(parents=True)
    new_path.write_text("# renamed\n", encoding="utf-8")

    now = [0.0]
    monkeypatch.setattr(
        "sase.sdd._artifact_link_renames.time.monotonic", lambda: now[0]
    )

    def _fake_map(_root: Path, *, kind: str) -> dict[str, str]:
        now[0] = 2.0
        return {f"{kind}:202608/old.md": f"{kind}:202608/new.md"}

    monkeypatch.setattr(
        "sase.sdd._artifact_link_renames._historical_rename_map",
        _fake_map,
    )

    report = repair_historical_artifact_renames(
        store,
        ("plan:202608/old.md", "plan:202608/other.md", "research:202608/x.md"),
        deadline=1.0,
    )

    assert [(rename.old_ref, rename.new_ref) for rename in report.renames] == [
        ("plan:202608/old.md", "plan:202608/new.md")
    ]
    assert report.deferred_refs == 2
