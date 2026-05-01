---
create_time: 2026-05-01 00:00:00
status: complete
bead_id: sase-1p.2
---

# Agent Compose Phase 2 Rust Core Handoff

## Summary

Implemented the pure Rust `agent_compose` operation family in `../sase-core` without PyO3 or product routing.

Changed files:

- `../sase-core/crates/sase_core/src/agent_compose/wire.rs`
- `../sase-core/crates/sase_core/src/agent_compose/mod.rs`
- `../sase-core/crates/sase_core/src/lib.rs`
- `../sase-core/crates/sase_core/src/notifications/store.rs`

The new core mirrors the Phase 1 Python wire records, builds candidates from `RunningClaimWire`, `AgentArtifactScanWire`,
and `ChangeSpecWire`, keeps PID liveness host-owned via `alive_pids` / `dead_pids`, emits merge/drop diagnostics, applies
the deterministic dedup/status/sort passes, and returns `ComposedAgentListWire`.

`notifications/store.rs` only received clippy hygiene needed for the workspace `-D warnings` gate on the current
toolchain: an explicit lock-file truncate mode and targeted MSRV lint allowances around `fs2` lock calls.

## Verification

Run in `../sase-core`:

- `cargo test -p sase_core agent_compose -- --nocapture`
- `cargo fmt --all -- --check`
- `cargo clippy --workspace --all-targets -- -D warnings`
- `cargo test --workspace`

All passed.

## Ambiguities / Risks

- Phase 1 did not land a serialized compose input/output golden JSON corpus, so Phase 2 pins parity through Rust fixture
  tests that exercise the same contract-sensitive behaviors instead of byte-for-byte Python fixture replay.
- Per-step `agent_meta.json` enrichment for prompt-step markers is still filesystem-owned in Python today. The Rust core
  only consumes data present in the supplied artifact scan, so Phase 3/4 should decide whether extra supplement scan
  inputs are needed before product routing.
- `RunningClaimWire` does not carry `role_suffix` or `parent_timestamp`; follow-up linkage for active claims still
  depends on artifact-scan metadata being supplied.

## Next Phase

Phase 3 is unblocked to add the PyO3 binding and Python facade parity path for `compose_agent_list(input: dict) -> dict`.
