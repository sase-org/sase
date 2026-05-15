---
plan: sdd/tales/202605/notification_rewrite_merge.md
---
 Why is the bead-backend GitHub Actions job failing? Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
failures:

---- notification_append_plus_rewrite_counts_concurrency_preserves_valid_rows stdout ----

thread 'notification_append_plus_rewrite_counts_concurrency_preserves_valid_rows' (9098) panicked at crates/sase_core/tests/notification_store_parity.rs:878:5:
assertion failed: snapshot.notifications.iter().any(|n| n.id == "append-79")
note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace


failures:
    notification_append_plus_rewrite_counts_concurrency_preserves_valid_rows

test result: FAILED. 21 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.13s

error: test failed, to rerun pass `-p sase_core --test notification_store_parity`
error: Recipe `rust-test` failed on line 361 with exit code 101
Error: Process completed with exit code 101.
```