"""Historical artifact-link rename repair: per-kind memoization and deadlines."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from sase.sdd._artifact_link_commit import (
    ARTIFACT_LINK_COMMIT_MESSAGE,
    commit_artifact_link_indexes,
)
from sase.sdd._artifact_link_renames import repair_historical_artifact_renames
from sase.sdd.artifact_link_outbox import read_artifact_link_outbox_entries
from sase.sdd._artifact_link_store_support import sidecar_index_path
from tests.sdd._artifact_link_store_helpers import _store
from tests.sdd._artifact_link_store_helpers import _row

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
    assert report.alias_events_queued == 1
    assert report.deferred_refs == 2


def test_rename_repair_queues_stable_alias_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    plans = store.sidecar_roots["plan"]
    new_path = plans / "202608" / "new.md"
    new_path.parent.mkdir(parents=True)
    new_path.write_text("# renamed\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.sdd._artifact_link_renames._historical_rename_map",
        lambda _root, *, kind: {f"{kind}:202608/old.md": f"{kind}:202608/new.md"},
    )

    first = repair_historical_artifact_renames(store, ("plan:202608/old.md",))
    second = repair_historical_artifact_renames(store, ("plan:202608/old.md",))
    entries = read_artifact_link_outbox_entries("gh_sase-org__sase")

    assert first.alias_events_queued == 1
    assert second.alias_events_queued == 1
    assert len(entries) == 2
    assert entries[0].id == entries[1].id
    assert entries[0].event is not None
    assert entries[0].event["kind"] == {
        "type": "alias",
        "old_ref": "plan:202608/old.md",
        "new_ref": "plan:202608/new.md",
    }


def test_commit_artifact_link_indexes_stages_existing_and_deleted_indexes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    plans = store.sidecar_roots["plan"]
    _init_git_repo(plans)
    existing = _write_link_index(
        plans,
        "plan:202608/existing.md",
        rows=[
            _row(
                source="plan:202608/existing.md",
                target="plan:202608/target.md",
            )
        ],
    )
    removed = _write_link_index(
        plans,
        "plan:202608/removed.md",
        rows=[
            _row(
                source="plan:202608/removed.md",
                target="plan:202608/target.md",
            )
        ],
    )
    _git(plans, "add", ".")
    _git(plans, "commit", "-m", "seed link indexes")

    payload = json.loads(existing.read_text(encoding="utf-8"))
    payload["rows"].append(
        _row(
            source="plan:202608/existing.md",
            relation="related",
            target="plan:202608/other.md",
        )
    )
    existing.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    removed.unlink()

    result = commit_artifact_link_indexes(
        (existing, removed),
        repo_roots=(plans,),
        push_after_commit=False,
        verify_publication=False,
    )

    assert result.committed is True
    changed = set(
        _git_output(plans, "show", "--name-status", "--format=", "HEAD").splitlines()
    )
    assert "M\tlinks/202608/existing.md.json" in changed
    assert "D\tlinks/202608/removed.md.json" in changed
    assert _git_output(plans, "status", "--short") == ""


def test_rename_repair_commit_includes_rewrite_and_removed_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    plans = store.sidecar_roots["plan"]
    _init_git_repo(plans)
    old_doc = plans / "202608" / "old.md"
    new_doc = plans / "202608" / "new.md"
    old_doc.parent.mkdir(parents=True)
    old_doc.write_text("# old\n", encoding="utf-8")
    _write_link_index(
        plans,
        "plan:202608/old.md",
        rows=[
            _row(
                source="agent:planner.coder",
                relation="read",
                target="plan:202608/old.md",
                origin="read",
            )
        ],
    )
    _git(plans, "add", ".")
    _git(plans, "commit", "-m", "seed old artifact")
    old_doc.rename(new_doc)
    _git(plans, "add", "-A")
    _git(plans, "commit", "-m", "rename artifact")

    report = repair_historical_artifact_renames(
        store,
        ("plan:202608/old.md",),
    )
    result = commit_artifact_link_indexes(
        report.changed_paths,
        repo_roots=(plans,),
        push_after_commit=False,
        verify_publication=False,
    )

    assert [(rename.old_ref, rename.new_ref) for rename in report.renames] == [
        ("plan:202608/old.md", "plan:202608/new.md")
    ]
    assert result.committed is True
    assert (
        _git_output(plans, "log", "-1", "--pretty=%s") == ARTIFACT_LINK_COMMIT_MESSAGE
    )
    changed = set(
        _git_output(
            plans,
            "show",
            "--no-renames",
            "--name-status",
            "--format=",
            "HEAD",
        ).splitlines()
    )
    assert "A\tlinks/202608/new.md.json" in changed
    assert "D\tlinks/202608/old.md.json" in changed
    assert _git_output(plans, "status", "--short") == ""


def _write_link_index(
    repo: Path,
    artifact_ref: str,
    *,
    rows: list[dict[str, object]],
) -> Path:
    path = sidecar_index_path(repo, artifact_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "artifact_ref": artifact_ref,
                "rows": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _git_output(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
