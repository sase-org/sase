"""Saved-query and history records refuse amended-dialect profile digests."""

from __future__ import annotations

import pytest

from sase.ace.query_record import QueryRecord, current_profile_digest
from sase.ace.query_profile import (
    beads_query_schema,
    compile_query_profile,
    files_query_schema,
    plans_query_schema,
    stitches_query_schema,
)


@pytest.mark.parametrize(
    ("pane_id", "schema_factory"),
    (
        ("beads", beads_query_schema),
        ("stitches", stitches_query_schema),
        ("files", files_query_schema),
        ("ref:plan", plans_query_schema),
    ),
)
def test_amended_dialect_marks_prior_digest_stale(pane_id: str, schema_factory) -> None:
    current = current_profile_digest(pane_id)
    assert current == compile_query_profile(schema_factory()).digest
    stale = QueryRecord(source="q", canonical="q", profile_digest="prior-digest")
    assert stale.is_stale(pane_id) is True
    live = QueryRecord(source="q", canonical="q", profile_digest=current)
    assert live.is_stale(pane_id) is False
