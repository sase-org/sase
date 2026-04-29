"""Golden corpus for the agent-artifact scan facade (Phase 3A, sase-18.1).

Fixtures are built programmatically by :func:`build_fixture_tree` so a Rust
port can populate the same tree shape from Rust tests without checking in
hundreds of small JSON files.

The corpus covers the cases listed in
``../../../sase_100/plans/202604/rust_backend_phase3_agent_scan.md`` for
Phase 3A:

- running ``ace-run`` agent with ``agent_meta.json``
- done ``ace-run`` agent with ``done.json``
- failed and retried done agents
- home-mode ``running.json``
- workflow root with ``workflow_state.json``
- prompt step markers with ``meta_*`` outputs and hidden / pre-prompt flags
- waiting agents with ``waiting.json``
- malformed JSON files that should be skipped/counted
- missing optional files
"""

from .fixture_builder import (
    EXPECTED_DECODE_ERRORS,
    EXPECTED_OS_ERRORS,
    EXPECTED_TIMESTAMPS,
    build_fixture_tree,
    fixture_summary,
)

__all__ = [
    "EXPECTED_DECODE_ERRORS",
    "EXPECTED_OS_ERRORS",
    "EXPECTED_TIMESTAMPS",
    "build_fixture_tree",
    "fixture_summary",
]
