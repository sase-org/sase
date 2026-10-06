"""Fingerprint keys for the Beads and Plans panes (sase-1h8.5)."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.widgets.artifacts.beads_data_sources import (
    store_fingerprint_key as beads_store_key,
)
from sase.ace.tui.widgets.artifacts.plans_data_sources import (
    store_fingerprint_key as plans_store_key,
)


def _event_store(beads: Path) -> None:
    (beads / "events" / "streams").mkdir(parents=True)
    (beads / "config.json").write_text("{}\n", encoding="utf-8")
    (beads / "events" / "manifest.json").write_text("{}\n", encoding="utf-8")
    (beads / "events" / "streams" / "demo-1.jsonl").write_text("{}\n", encoding="utf-8")
    (beads / "issues.jsonl").write_text("{}\n", encoding="utf-8")


def test_beads_key_ignores_projection_rewrite(tmp_path: Path) -> None:
    beads = tmp_path / "beads"
    _event_store(beads)
    first = beads_store_key(beads)
    assert isinstance(first, str) and len(first) == 64

    (beads / "issues.jsonl").write_text("{}\n{}\n", encoding="utf-8")
    assert beads_store_key(beads) == first


def test_beads_key_moves_on_stream_change(tmp_path: Path) -> None:
    beads = tmp_path / "beads"
    _event_store(beads)
    first = beads_store_key(beads)

    with (beads / "events" / "streams" / "demo-1.jsonl").open(
        "a", encoding="utf-8"
    ) as handle:
        handle.write("{}\n")
    assert beads_store_key(beads) != first


def test_beads_key_missing_dir_is_stable() -> None:
    assert beads_store_key(None) == ()


def test_plans_key_splits_bead_fingerprint_from_document_mtime(
    tmp_path: Path,
) -> None:
    beads = tmp_path / "beads"
    _event_store(beads)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "plan.md").write_text("# Plan\n", encoding="utf-8")

    bead_key, doc_key = plans_store_key(beads, {"plans": docs})
    assert isinstance(bead_key, str) and len(bead_key) == 64
    assert len(doc_key) == 1

    (beads / "issues.jsonl").write_text("{}\n{}\n", encoding="utf-8")
    bead_again, doc_again = plans_store_key(beads, {"plans": docs})
    assert bead_again == bead_key
    assert doc_again == doc_key

    (docs / "plan.md").write_text("# Plan\n\nmore\n", encoding="utf-8")
    bead_after, doc_after = plans_store_key(beads, {"plans": docs})
    assert bead_after == bead_key
    assert doc_after != doc_key
