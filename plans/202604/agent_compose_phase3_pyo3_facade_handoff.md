# Agent Compose Phase 3 Handoff: PyO3 Binding and Python Facade

## Summary

Phase 3 exposed the pure Rust agent composer through `sase_core_rs.compose_agent_list(input: dict) -> dict` and added a
Python facade/wire layer for parity and debug callers. The TUI and CLI loader paths are still unrouted; product routing
remains a later phase.

## Files Changed

- `../sase-core/crates/sase_core_py/src/lib.rs`
  - Added the PyO3 `compose_agent_list` binding.
  - Deserializes `AgentComposeInputWire`, releases the GIL while calling the pure Rust composer, and returns a plain
    Python dict.
- `src/sase/core/agent_compose_wire.py`
  - Added Python wire dataclasses, JSON projection, dict rehydration, and `Agent` conversion helpers.
- `src/sase/core/agent_compose_facade.py`
  - Added `build_agent_compose_input`, `compose_agent_list`, and debug mismatch logging.
- `tests/test_core_agent_compose.py`
  - Covers wire shape, facade marshalling, stale binding behavior, mismatch diagnostics, Agent conversion, and a real
    extension smoke/parity case.
- `docs/rust_backend.md`
  - Documents the new operation as experimental and unrouted.

## Verification

Run for this phase:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
pytest tests/test_core_agent_compose.py
just check
```

## Open Risks

- The facade currently exposes parity/debug primitives only. Phase 4 still needs to collect real loader inputs once and
  shadow-run Rust during realistic refreshes.
- Python-owned supplements (attempt history, retry-state promotion, tags, dismissed bundles, transient TUI overrides)
  remain outside this compose call by design.
