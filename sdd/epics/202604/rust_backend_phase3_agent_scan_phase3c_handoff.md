---
create_time: 2026-04-29
status: done
bead_id: sase-18.3
---

# Rust Backend Phase 3C — PyO3 Binding and Facade Dual-Run

Closes the Phase 3C subphase of `plans/202604/rust_backend_phase3_agent_scan.md`. This document records the PyO3
binding wired into `sase_core_rs`, the Python facade dispatch hookup, and the test surface Phase 3D–3F can
lean on.

## What landed

| Area              | File / module                                             |
| ----------------- | --------------------------------------------------------- |
| PyO3 binding      | `../sase-core/crates/sase_core_py/src/lib.rs`             |
| Facade dispatch   | `src/sase/core/agent_scan_facade.py`                      |
| Wire rehydrator   | `src/sase/core/agent_scan_wire.py`                        |
| Tests             | `tests/test_core_agent_scan.py`                           |
| Docs              | `docs/rust_backend.md`                                    |

## PyO3 binding

`sase_core_rs.scan_agent_artifacts(projects_root: str, options: dict | None = None) -> dict` is the new entry point:

- The dict shape on input mirrors `AgentArtifactScanOptionsWire` (`include_prompt_step_markers`,
  `include_raw_prompt_snippets`, `max_prompt_snippet_bytes`, `only_workflow_dirs`). Missing keys fall back to the Rust
  `Default` (which matches Python's `AgentArtifactScanOptionsWire()`).
- The walk releases the GIL via `py.allow_threads(...)` so concurrent Python work runs while Rust scans the tree.
- The output is a plain Python `dict`/`list`/primitive shape produced by `serde_json::to_value(&snapshot)` followed by
  the existing `json_value_to_py` walker. That dict round-trips through `agent_scan_wire_from_dict` into Python
  dataclasses, so callers always see `AgentArtifactScanWire`.

`agent_scan_options_from_pydict` deserializes via `serde_json::Value` so partial dicts inherit the Rust struct's serde
defaults — important for callers (and tests) that hand-build options dicts without filling every key.

## Facade dispatch

`scan_agent_artifacts` registers `_rust_scan_agent_artifacts_impl` only when `sase_core_rs` is importable **and**
exposes `scan_agent_artifacts`. The double-check is intentional: it lets users with an older Rust extension wheel keep
running the Python backend without crashing, while still raising `RustBackendUnavailableError` under
`SASE_CORE_BACKEND=rust` so a missing wheel never silently masks a regression.

The adapter passes `_options_to_dict(options)` to the binding so the Rust side never has to guess defaults. The
returned dict is rehydrated by `agent_scan_wire_from_dict` (added in this phase, in `agent_scan_wire.py`) into the same
frozen dataclass tree the Python path produces. That keeps `dataclasses.asdict` parity exactly and lets the dual-run
comparator use direct equality (the snapshots compare equal at every level, including stat counters, on the Phase 3A
fixture corpus per the Phase 3B parity work).

## Tests

`tests/test_core_agent_scan.py` gains six Phase 3C cases:

- `test_scan_agent_artifacts_rust_unavailable_keeps_python` — no extension + default backend leaves the Python path
  working.
- `test_scan_agent_artifacts_rust_without_impl_raises` — `SASE_CORE_BACKEND=rust` without the extension raises
  `RustBackendUnavailableError`.
- `test_scan_agent_artifacts_rust_backend_uses_rust_impl` — installs a fake `sase_core_rs` exposing
  `scan_agent_artifacts`, sets `SASE_CORE_BACKEND=rust`, and asserts the binding is the only path called and its dict
  output rehydrates to the same dataclass shape the Python path produces.
- `test_scan_agent_artifacts_dual_run_logs_comparison` — `SASE_CORE_DUAL_RUN=1` runs both impls, returns the Python
  result, and writes one JSONL record with `match=true`.
- `test_scan_agent_artifacts_dual_run_records_mismatch` — divergent Rust output is logged with `match=false`.
- `test_rust_extension_parity` — when the real `sase_core_rs` is installed, its output equals the Python facade's
  output for the synthetic Phase 3A corpus. Skips with `pytest.importorskip` and an additional `hasattr` guard so older
  wheels do not fail the suite.

The fake-module tests use the existing `_python_snapshot_as_dict` helper to manufacture parity output — that lets the
dual-run "match=true" path exercise the actual rehydration code without re-implementing the wire.

## Verification performed

```bash
just install
just rust-install   # PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 needed on Python 3.14 hosts
.venv/bin/pytest tests/test_core_agent_scan.py
.venv/bin/pytest tests/test_core_facade.py tests/test_core_backend.py tests/test_core_dual_run.py
SASE_CORE_BACKEND=rust .venv/bin/pytest tests/test_core_agent_scan.py
```

```bash
cd ../sase-core
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

All checks green. The real-extension parity test passes with `sase_core_rs` installed; without it the test skips
cleanly so pure-Python contributors are never blocked.

## Open items handed to Phase 3D / 3E / 3F

1. **Production call site rollout.** The facade is now backend-aware, but no production caller has been moved onto
   `scan_agent_artifacts` yet. Phases 3D–3F do that work for `sase.agent.names._lookup`, `sase.agent.running`, and the
   TUI artifact/workflow loaders.
2. **Stat-counter divergence.** The synthetic corpus produces identical `stats` between Python and Rust today, so the
   dual-run comparator can use direct equality. If a real `~/.sase/projects` walk shows transient stat differences
   (e.g., racing OS errors), the facade has the option to plug a custom comparator/serializer in — `dispatch` would
   need a small extension to forward those to `run_with_comparison`. Hold off until a real divergence shows up so the
   shape of the comparator matches the actual mismatch class.
3. **Benchmark surface.** `just bench-agent-scan` still measures the Python facade only. Phase 3D/3E/3F should extend
   it to compare Python facade vs. Rust facade vs. dual-run overhead so the rollout decision in Phase 3H has fresh
   numbers. The wire and dispatch hooks for that exist now.
