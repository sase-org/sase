"""Reusable artifact-link index parity comparison and timing helper.

Phase ``parity-baseline`` (bead:sase-1kj.8.1.1) of
``plan:202610/artifact_link_inverted_index.md``. Later native-index and
python-integration phases import this module against the same saved
aggregate and the committed sanitized fixture.

This module is the public facade; implementation lives in
:mod:`tests.perf._artifact_link_index_bench_serialize`,
:mod:`tests.perf._artifact_link_index_bench_fixture`, and
:mod:`tests.perf._artifact_link_index_bench_measure`.

Public entry points today are ``load_artifact_links_snapshot``,
``_build_link_index``, ``link_index_for_snapshot``, and
``build_patches_relation_index``. Cold construction is timed through
``_build_link_index``; warm reuse through ``link_index_for_snapshot``.
Eager-consumer work (walking ``by_ref`` / ``targets_by_ref``) is timed
separately so a later lazy handle cannot report deferred chip work as
eliminated.

Run::

    .venv/bin/python -m tests.perf.artifact_link_index_bench write-fixture-goldens
    .venv/bin/python -m tests.perf.artifact_link_index_bench capture \\
        --project gh_sase-org__sase --output-dir /tmp/artifact-link-parity
    .venv/bin/python -m tests.perf.artifact_link_index_bench measure \\
        --aggregate /path/to/aggregate.json
"""

from __future__ import annotations

from tests.perf._artifact_link_index_bench_fixture import (
    FIXTURE_CHIPS_PATH,
    FIXTURE_DIR,
    FIXTURE_INPUT_PATH,
    FIXTURE_PATCH_INDEX_PATH,
    SYNTHETIC_SCALE_ROWS,
    build_synthetic_scale_rows,
    fixture_patches,
    fixture_snapshot,
    identity_from_payload,
    identity_payload,
    load_fixture_input,
    load_saved_aggregate,
    patches_from_payload,
    pinned_identity,
    snapshot_from_rows,
    snapshot_from_saved_aggregate,
    source_key_from_payload,
)
from tests.perf._artifact_link_index_bench_measure import (
    Timed,
    build_parser,
    build_patch_index,
    capture_live_aggregate,
    clear_link_index_cache,
    consume_eager_index,
    dump_json,
    host_metadata,
    input_hash,
    main,
    measure_snapshot,
    patches_contract,
    query_index,
    timed_call,
    unique_ref_count,
    write_fixture_goldens,
)
from tests.perf._artifact_link_index_bench_serialize import (
    chip_payload,
    diagnostic_payload,
    edge_payload,
    index_enumeration_refs,
    parity_diff,
    serialize_link_index,
    serialize_relation_index,
    target_payload,
)

__all__ = [
    "FIXTURE_CHIPS_PATH",
    "FIXTURE_DIR",
    "FIXTURE_INPUT_PATH",
    "FIXTURE_PATCH_INDEX_PATH",
    "SYNTHETIC_SCALE_ROWS",
    "Timed",
    "build_parser",
    "build_patch_index",
    "build_synthetic_scale_rows",
    "capture_live_aggregate",
    "chip_payload",
    "clear_link_index_cache",
    "consume_eager_index",
    "diagnostic_payload",
    "dump_json",
    "edge_payload",
    "fixture_patches",
    "fixture_snapshot",
    "host_metadata",
    "identity_from_payload",
    "identity_payload",
    "index_enumeration_refs",
    "input_hash",
    "load_fixture_input",
    "load_saved_aggregate",
    "main",
    "measure_snapshot",
    "parity_diff",
    "patches_contract",
    "patches_from_payload",
    "pinned_identity",
    "query_index",
    "serialize_link_index",
    "serialize_relation_index",
    "snapshot_from_rows",
    "snapshot_from_saved_aggregate",
    "source_key_from_payload",
    "target_payload",
    "timed_call",
    "unique_ref_count",
    "write_fixture_goldens",
]


if __name__ == "__main__":
    raise SystemExit(main())
