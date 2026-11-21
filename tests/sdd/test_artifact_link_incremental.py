"""Input fingerprints that let the hourly artifact-link jobs skip no-op work."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase.sdd._artifact_link_incremental import (
    FULL_PASS_INTERVAL_SECONDS,
    ArtifactLinkReconcileMemo,
    document_sweep_fingerprint,
    reconcile_input_fingerprint,
    store_backed_rows_digest,
    unrepairable_refs_fingerprint,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _row

_PROJECT = "gh_sase-org__sase"


def _touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactLinkStore:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "machine" / "plans"
    research = tmp_path / "machine" / "research"
    beads = tmp_path / "machine" / "beads"
    for root in (plans, research, beads):
        root.mkdir(parents=True)
    store = ArtifactLinkStore(
        project_key=_PROJECT,
        sidecar_roots={"plan": plans, "research": research},
        beads_dir=beads,
    )
    monkeypatch.setattr(
        ArtifactLinkStore,
        "_iter_reconciliation_stores",
        lambda self: iter((self,)),
    )
    monkeypatch.setattr(
        ArtifactLinkStore, "_legacy_indexes_imported", lambda self: True
    )
    return store


def test_sweep_fingerprint_tracks_document_paths_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    plans = store.sidecar_roots["plan"]
    doc = _touch(plans / "202611" / "a.md")
    baseline = document_sweep_fingerprint(store)

    assert baseline is not None
    assert document_sweep_fingerprint(store) == baseline

    # Edits never make an already-swept ref pending again, and neither link
    # indexes, event objects, nor dot directories hold sweepable documents.
    doc.write_text("edited body", encoding="utf-8")
    _touch(plans / "links" / "202611" / "a.md.json")
    _touch(plans / "link-events" / "v1" / "ab" / "event.json")
    _touch(plans / ".git" / "notes.md")
    _touch(plans / "202611" / "notes.txt")
    assert document_sweep_fingerprint(store) == baseline

    added = _touch(store.sidecar_roots["research"] / "202611" / "r.md")
    with_added = document_sweep_fingerprint(store)
    assert with_added != baseline

    added.rename(added.with_name("renamed.md"))
    assert document_sweep_fingerprint(store) not in {baseline, with_added}


def test_sweep_fingerprint_fails_open_without_sidecar_roots() -> None:
    assert document_sweep_fingerprint(SimpleNamespace()) is None


def test_reconcile_fingerprint_tracks_every_reduced_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    plans = store.sidecar_roots["plan"]
    beads = store.beads_dir
    assert beads is not None
    _touch(plans / "link-events" / "v1" / "aa" / "one.json")
    _touch(beads / "events" / "streams" / "sase-1.jsonl")
    seen = {reconcile_input_fingerprint(store)}
    assert None not in seen
    assert reconcile_input_fingerprint(store) in seen

    # Projection inputs and derived bead caches never force the reduction.
    _touch(plans / "202611" / "new-plan.md")
    _touch(beads / "pages" / "sase-1.md")
    _touch(beads / "beads.db-wal")
    _touch(beads / "events" / "streams" / ".sase-1.jsonl.tmp.1")
    assert reconcile_input_fingerprint(store) in seen

    changes = (
        lambda: _touch(plans / "link-events" / "v1" / "bb" / "two.json"),
        lambda: _touch(plans / "link-events" / "quarantine" / "v1" / "q.json"),
        lambda: _touch(
            tmp_path / ".sase" / "projects" / _PROJECT / "link-events" / "v1" / "l.json"
        ),
        lambda: _touch(beads / "events" / "streams" / "sase-2.jsonl"),
        lambda: _touch(
            tmp_path / ".sase" / "projects" / _PROJECT / "artifact-link-outbox.jsonl",
            "{}\n",
        ),
    )
    for change in changes:
        change()
        fingerprint = reconcile_input_fingerprint(store)
        assert fingerprint is not None
        assert fingerprint not in seen
        seen.add(fingerprint)


def test_reconcile_fingerprint_reads_legacy_indexes_until_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ArtifactLinkStore, "_legacy_indexes_imported", lambda self: False
    )
    before = reconcile_input_fingerprint(store)
    _touch(store.sidecar_roots["plan"] / "links" / "202611" / "a.md.json")

    assert reconcile_input_fingerprint(store) != before


def test_reconcile_fingerprint_fails_open() -> None:
    assert reconcile_input_fingerprint(SimpleNamespace(project_key=_PROJECT)) is None


def test_store_backed_digest_ignores_projected_rows() -> None:
    durable = _row()
    projected = _row(target="plan:202608/c.md", origin="projected")

    assert store_backed_rows_digest([durable, projected]) == store_backed_rows_digest(
        [durable]
    )
    assert store_backed_rows_digest([durable]) != store_backed_rows_digest(
        [_row(description="changed")]
    )


def _git(root: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, env=env)


def test_unrepairable_refs_fingerprint_tracks_refs_and_sidecar_heads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    plans = store.sidecar_roots["plan"]
    _git(plans, "init", "-q")
    _touch(plans / "202611" / "a.md")
    _git(plans, "add", "-A")
    _git(plans, "commit", "-q", "-m", "one")
    refs = ("plan:202611/gone.md", "research:202611/old.md")
    baseline = unrepairable_refs_fingerprint(store, refs)

    assert baseline is not None
    assert unrepairable_refs_fingerprint(store, reversed(refs)) == baseline
    assert unrepairable_refs_fingerprint(store, refs[:1]) != baseline

    _touch(plans / "202611" / "b.md")
    _git(plans, "add", "-A")
    _git(plans, "commit", "-q", "-m", "two")
    assert unrepairable_refs_fingerprint(store, refs) != baseline


def test_memo_round_trips_and_reports_the_daily_backstop() -> None:
    memo = ArtifactLinkReconcileMemo(
        input_fingerprint="in:agg", unrepairable_refs="refs", full_pass_at=100.0
    )

    assert ArtifactLinkReconcileMemo.from_json(memo.to_json()) == memo
    assert ArtifactLinkReconcileMemo.from_json("junk") == ArtifactLinkReconcileMemo()
    assert memo.full_pass_due(now=100.0 + FULL_PASS_INTERVAL_SECONDS - 1) is False
    assert memo.full_pass_due(now=100.0 + FULL_PASS_INTERVAL_SECONDS) is True
    assert ArtifactLinkReconcileMemo().full_pass_due(now=0.0) is True
