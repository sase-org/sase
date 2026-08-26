from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from sase.artifact_links.derive import DerivableDocument, DerivedLinkCandidate
from sase.sdd import artifact_link_backfill as artifact_link_backfill_module
from sase.sdd.artifact_link_derivation import _ArtifactLinkDerivationOutcome
from sase.sdd.artifact_link_backfill import (
    run_artifact_link_backfill_batch,
    sweepable_artifact_link_documents,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactLinkStore:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    plans.mkdir()
    research.mkdir()
    return ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans, "research": research},
    )


def _write_plan(root: Path, relpath: str, *, bead_id: str | None) -> Path:
    path = root / "plans" / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    bead_line = f"bead_id: {bead_id}\n" if bead_id else ""
    path.write_text(f"---\ntier: tale\n{bead_line}---\n\nbody\n", encoding="utf-8")
    return path


def test_sweep_walks_nested_directories_and_skips_the_links_companion_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    _write_plan(tmp_path, "202608/a.md", bead_id="sase-xx")
    _write_plan(tmp_path, "202608/nested/b.md", bead_id="sase-yy")
    companion = tmp_path / "plans" / "links" / "202608" / "a.md.json"
    companion.parent.mkdir(parents=True, exist_ok=True)
    companion.write_text("{}", encoding="utf-8")

    documents = sweepable_artifact_link_documents(store)

    refs = {document.ref for document in documents}
    assert refs == {"plan:202608/a.md", "plan:202608/nested/b.md"}


def test_sweep_excludes_already_swept_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    _write_plan(tmp_path, "202608/a.md", bead_id="sase-xx")
    _write_plan(tmp_path, "202608/b.md", bead_id="sase-yy")

    documents = sweepable_artifact_link_documents(
        store, already_swept=frozenset({"plan:202608/a.md"})
    )

    assert [document.ref for document in documents] == ["plan:202608/b.md"]


def test_missing_sidecar_root_contributes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    store = ArtifactLinkStore(project_key="gh_sase-org__sase", sidecar_roots={})

    assert sweepable_artifact_link_documents(store) == ()


def test_batch_is_bounded_and_reports_remaining(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sase.sdd.artifact_link_derivation._known_bead_ids",
        lambda _store: frozenset({"sase-xx", "sase-yy", "sase-zz"}),
    )
    _write_plan(tmp_path, "202608/a.md", bead_id="sase-xx")
    _write_plan(tmp_path, "202608/b.md", bead_id="sase-yy")
    _write_plan(tmp_path, "202608/c.md", bead_id="sase-zz")

    report, swept = run_artifact_link_backfill_batch(
        store, already_swept=frozenset(), batch_size=2
    )

    assert report.total_pending == 3
    assert report.scanned == 2
    assert report.remaining == 1
    assert report.persisted == 2
    assert len(swept) == 2

    second_report, second_swept = run_artifact_link_backfill_batch(
        store, already_swept=swept, batch_size=2
    )

    assert second_report.scanned == 1
    assert second_report.remaining == 0
    assert second_swept == frozenset(
        {"plan:202608/a.md", "plan:202608/b.md", "plan:202608/c.md"}
    )


def test_batch_returns_after_completed_chunk_when_deadline_expires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    monkeypatch.setattr(artifact_link_backfill_module, "_PERSIST_CHUNK_SIZE", 1)
    _write_plan(tmp_path, "202608/a.md", bead_id="sase-xx")
    _write_plan(tmp_path, "202608/b.md", bead_id="sase-yy")
    _write_plan(tmp_path, "202608/c.md", bead_id="sase-zz")
    processed: list[str] = []

    persisted_keys: set[tuple[str, str, str]] = set()

    def _derive(
        documents: Sequence[DerivableDocument],
        **_kwargs: object,
    ) -> tuple[DerivedLinkCandidate, ...]:
        processed.extend(document.ref for document in documents)
        return tuple(
            DerivedLinkCandidate(
                source_ref=document.ref,
                relation="related",
                target_ref="plan:202608/target.md",
                description="shares a fixture root",
            )
            for document in documents
        )

    def _persist(
        _store: ArtifactLinkStore,
        candidates: Sequence[DerivedLinkCandidate],
        **_kwargs: object,
    ) -> _ArtifactLinkDerivationOutcome:
        persisted_keys.update(
            (candidate.source_ref, candidate.relation, candidate.target_ref)
            for candidate in candidates
        )
        return _ArtifactLinkDerivationOutcome(
            candidates=len(candidates), persisted=len(candidates)
        )

    monkeypatch.setattr(
        artifact_link_backfill_module, "derive_candidate_links", _derive
    )
    monkeypatch.setattr(
        artifact_link_backfill_module, "persist_derived_link_candidates", _persist
    )
    monkeypatch.setattr(
        artifact_link_backfill_module,
        "_stored_link_keys",
        lambda _store: frozenset(persisted_keys),
    )
    monkeypatch.setattr(artifact_link_backfill_module.time, "monotonic", lambda: 2.0)

    report, swept = run_artifact_link_backfill_batch(
        store,
        already_swept=frozenset(),
        batch_size=3,
        deadline=1.0,
    )

    assert processed == ["plan:202608/a.md"]
    assert report.total_pending == 3
    assert report.scanned == 1
    assert report.remaining == 2
    assert report.persisted == 1
    assert swept == frozenset({"plan:202608/a.md"})


def test_candidate_documents_remain_unswept_when_persist_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    _write_plan(tmp_path, "202608/a.md", bead_id="sase-xx")
    _write_plan(tmp_path, "202608/b.md", bead_id="sase-yy")

    def _derive(
        documents: Sequence[DerivableDocument],
        **_kwargs: object,
    ) -> tuple[DerivedLinkCandidate, ...]:
        [document] = documents
        if document.ref.endswith("/b.md"):
            return ()
        return (
            DerivedLinkCandidate(
                source_ref=document.ref,
                relation="related",
                target_ref="plan:202608/target.md",
                description="shares a fixture root",
            ),
        )

    monkeypatch.setattr(
        artifact_link_backfill_module, "derive_candidate_links", _derive
    )
    monkeypatch.setattr(
        artifact_link_backfill_module,
        "persist_derived_link_candidates",
        lambda *_args, **_kwargs: _ArtifactLinkDerivationOutcome(
            candidates=1,
            persisted=0,
            errors=("commit failed",),
        ),
    )

    report, swept = run_artifact_link_backfill_batch(
        store, already_swept=frozenset(), batch_size=2
    )

    assert report.scanned == 2
    assert report.candidates == 1
    assert report.persisted == 0
    assert report.remaining == 1
    assert report.errors == ("commit failed",)
    assert swept == frozenset({"plan:202608/b.md"})


def test_no_pending_documents_is_a_fast_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    _write_plan(tmp_path, "202608/a.md", bead_id="sase-xx")
    already_swept = frozenset({"plan:202608/a.md"})

    report, swept = run_artifact_link_backfill_batch(
        store, already_swept=already_swept, batch_size=500
    )

    assert report.total_pending == 0
    assert report.scanned == 0
    assert swept == already_swept
