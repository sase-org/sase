"""LinkIndex must resolve every durable row the store holds (bead:sase-ug.5).

Uses the shared harness `truthread` (bead:sase-ug.4) built so a repeat of the
epic's historical defect -- an index silently dropping a relation class --
fails the suite instead of passing by comparing an index against itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from sase.ace.tui.relations.artifact_links import ArtifactLinksSnapshot
from sase.ace.tui.relations.link_index import LinkChip, _build_link_index
from tests.sdd._artifact_link_store_helpers import (
    _row,
    _store,
    assert_index_resolves_durable_rows,
)


def _index_rows(
    index: object,
    rows: tuple[Mapping[str, object], ...],
) -> list[dict[str, object]]:
    from tests.perf.artifact_link_index_bench import index_enumeration_refs

    if index is None:
        return []
    refs = index_enumeration_refs(rows)  # type: ignore[arg-type]
    chips_for = index.chips_for
    return [
        {
            "source_ref": ref,
            "relation": chip.relation,
            "target_ref": chip.neighbor_ref,
        }
        for ref in refs
        for chip in chips_for(ref)
        if chip.this_is_source
    ]


def test_link_index_resolves_every_durable_row_the_store_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    store.upsert_row(_row())
    store.upsert_row(
        _row(
            source="agent:pending.athena.worker",
            relation="cites",
            target="plan:202608/c.md",
            origin="prompt_ref",
        )
    )
    store.upsert_row(
        _row(source="plan:202608/d.md", relation="related", target="plan:202608/e.md")
    )

    rows = tuple(store.load_aggregate()["rows"])
    index = _build_link_index(ArtifactLinksSnapshot(rows=rows, source_key=("test",)))

    assert_index_resolves_durable_rows(store, _index_rows(index, rows))


def test_link_index_catches_a_repeat_of_the_dropped_relation_class_defect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    store.upsert_row(
        _row(
            source="agent:pending.athena.worker",
            relation="cites",
            target="plan:202608/a.md",
            origin="prompt_ref",
        )
    )

    with pytest.raises(AssertionError, match="missing durable artifact-link rows"):
        assert_index_resolves_durable_rows(store, _index_rows(index=None, rows=()))
