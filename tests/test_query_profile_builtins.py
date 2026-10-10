"""Cross-pane query profile invariants."""

from __future__ import annotations

import pytest

from sase.ace.query_profile import (
    CompiledQueryProfile,
    agents_archive_query_schema,
    agents_live_query_schema,
    agents_query_schema,
    beads_query_schema,
    compile_query_profile,
    files_query_schema,
    patches_query_schema,
    plans_query_schema,
    procs_query_schema,
    stitches_query_schema,
)
from sase.core.rust import require_rust_binding


@pytest.mark.parametrize(
    "schema_factory",
    [
        patches_query_schema,
        stitches_query_schema,
        beads_query_schema,
        plans_query_schema,
        agents_query_schema,
        agents_live_query_schema,
        agents_archive_query_schema,
        files_query_schema,
        procs_query_schema,
    ],
)
def test_every_builtin_profile_compiles_without_error(schema_factory) -> None:
    profile = compile_query_profile(schema_factory())
    assert isinstance(profile, CompiledQueryProfile)
    assert profile.digest
    assert profile.to_wire()["digest"] == profile.digest
    # Core recomputes the digest from its own canonical payload and rejects a
    # mismatch, which would crash every Artifacts pane that indexes its rows.
    require_rust_binding("compile_corpus_with_profile")(profile.to_wire(), [])


def test_every_builtin_profile_has_a_unique_pane_id() -> None:
    all_ids = [
        factory().pane_id
        for factory in (
            patches_query_schema,
            stitches_query_schema,
            beads_query_schema,
            plans_query_schema,
            agents_query_schema,
            agents_live_query_schema,
            agents_archive_query_schema,
            files_query_schema,
            procs_query_schema,
        )
    ]
    assert len(all_ids) == len(set(all_ids)) == 9
