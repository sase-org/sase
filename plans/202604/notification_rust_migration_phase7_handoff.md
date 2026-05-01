# Notification Store Rust Migration Phase 7 Handoff

Bead: `sase-1n.7`. Plan: `plans/202604/notification_rust_migration.md`.

Phase 7 locks in the Rust-backed notification store as the production path. The legacy Python parser/rewrite
implementation is no longer present in `src/sase/notifications/store.py`; public store calls route through
`sase.core.notification_store_facade`, which calls `sase_core_rs`.

## Regression Floor

The Phase 7 floor now includes notification-store anchors in
`tests/perf/baselines/phase7_regression_floor.json`, and `tests/perf/phase7_check_regression.py` runs
`tests/perf/bench_notification_store.py` when those anchors are present.

Command used for the capture:

```bash
.venv/bin/python tests/perf/bench_notification_store.py --runs 3 --warmup 1 --count 5000 --output /tmp/notification-store-rust-phase7.json
```

| Scenario | Phase 1 Python median | Phase 7 Rust median | Result |
| --- | ---: | ---: | --- |
| `notification_store_5k_load_snapshot` | 12.700 ms | 13.190 ms | Absolute ceiling only; snapshot/count path is parity-ish on this corpus. |
| `notification_store_5k_mark_dismissed_burst` | 5857.335 ms | 4865.040 ms | Faster under Rust-backed writes. |
| `notification_store_5k_mark_all_read` | 79.459 ms | 71.685 ms | Faster under Rust-backed writes. |
| `notification_store_append_plus_rewrite_concurrency` | 160.460 ms | 1940.894 ms | Correctness-first anchor; writes now serialize under one lock and avoid truncate-before-lock exposure. |
| `notification_modal_dismiss_burst` | n/a | 3186.558 ms | New modal-level absolute ceiling anchor. |

## Cleanup Audit

- No production notification code opens `notifications.jsonl` with `"w"`.
- `src/sase/notifications/store.py` comments/docstrings describe the Rust-backed store path.
- `docs/notifications.md` now documents `sase_core_rs` as the production store backend.
- TUI notification actions mutate through store helpers; no modal action performs Python JSONL parse/rewrite directly.

## Residual Risks

The append-plus-rewrite concurrency benchmark is slower than the Phase 1 Python baseline because the Rust backend now
serializes append and rewrite under the same sidecar lock before using tempfile/rename. Phase 7 treats that as an
accepted correctness tradeoff: the previous baseline was faster partly because it could expose an empty or partially
rewritten file.
