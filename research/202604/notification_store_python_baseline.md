# Notification Store Python Baseline

Phase 1 baseline for `plans/202604/notification_rust_migration.md`.

Command:

```bash
.venv/bin/python tests/perf/bench_notification_store.py --runs 3 --warmup 1 --output /tmp/notification-store-baseline.json
```

Corpus:

- 5,000 deterministic synthetic JSONL notifications from `tests/fixtures/notifications/generate.py`.
- Store path patched to a temp directory; no user `~/.sase` notification data is read or written.
- Python implementation in `src/sase/notifications/store.py`.

Results:

| Scenario | min ms | median ms | p95 ms | max ms |
| --- | ---: | ---: | ---: | ---: |
| `notification_store_5k_load_snapshot` | 11.334 | 12.700 | 16.377 | 16.377 |
| `notification_store_5k_mark_dismissed_burst` | 5848.621 | 5857.335 | 5871.609 | 5871.609 |
| `notification_store_5k_mark_all_read` | 79.047 | 79.459 | 82.035 | 82.035 |
| `notification_store_append_plus_rewrite_concurrency` | 144.433 | 160.460 | 175.063 | 175.063 |

Handoff notes:

- Small fixture: `tests/fixtures/notifications/store_contract.jsonl`.
- Shared generator: `tests/fixtures/notifications/generate.py`.
- Contract tests: `tests/test_core_notification_store.py`.
- Benchmark harness: `tests/perf/bench_notification_store.py`.
- The empty-file observation concurrency contract is currently marked `xfail`; Phase 4 should make that contract pass
  when append/rewrite move to one lock/tempfile/rename implementation.
