---
create_time: 2026-05-15 16:03:02
status: done
prompt: sdd/prompts/202605/notification_rewrite_merge.md
---
# Fix flaky `notification_append_plus_rewrite_counts_concurrency_preserves_valid_rows`

## Problem

CI job `bead-backend` is failing on Rust test `notification_append_plus_rewrite_counts_concurrency_preserves_valid_rows`
(`../sase-core/crates/sase_core/tests/notification_store_parity.rs:840-880`).

The test runs two threads against a shared `notifications.jsonl`:

- **Append thread** — 80× `append_notification_counts(...)` (exclusive flock, append one line, release).
- **Rewrite thread** — 30× read–modify–write:
  1. `read_notifications_snapshot(path, true)` — takes a **shared** lock, reads, releases.
  2. In-memory: `rows.push(notification("rewrite-{idx}"))`.
  3. `rewrite_notifications_counts(path, &rows)` — takes an **exclusive** lock, tempfile+rename, release.

No lock is held between step 1 and step 3, so:

- Snapshot at T0 sees `[seed, append-0..append-K]`.
- Append thread writes `append-{K+1}..append-M` between T0 and T1.
- Rewrite at T1 overwrites the file with `[seed, append-0..append-K, rewrite-{idx}]`, destroying
  `append-{K+1}..append-M`.

Assertion on line 878 (`append-79`) fails when the rewrite thread's last iteration straddles the final appends. Locally
the test always passes (timing favorable: ~20× runs, all green). On `ubuntu-latest` GitHub runners the race window
opens.

The older sibling test `notification_append_plus_rewrite_concurrency_preserves_valid_rows` (lines 678-719) shares the
exact same RMW pattern using `rewrite_notifications` (full-outcome variant). It currently passes locally but is equally
race-prone — its longer lock window (extra reread under the exclusive lock) just makes the race harder to hit.

The test name (`..._preserves_valid_rows`) and the assertions together state the intended contract: **rewrite must not
destroy rows that were appended concurrently between the caller's snapshot read and the rewrite.** This matches the
real-world UX requirement that a state-update RMW (e.g., "mark as read") must not silently drop newly-arrived
notifications.

## Chosen approach: merge-on-rewrite

Change the rewrite path so that under the held exclusive lock it re-reads the existing on-disk rows and writes the
**union**: the caller's input rows + any existing rows whose `id` is NOT in the caller's input set. Caller's rows win on
`id` collision (this preserves state mutations); rows the caller never saw survive.

This:

- Keeps every public API signature stable (Rust + PyO3 + Python facade + wire schema).
- Matches the test's stated semantics — no test change needed.
- Fixes the latent flakiness in the older sibling test too.
- Costs one extra file read per rewrite, all under the lock we were already taking. Negligible overhead for the small
  files this store uses; the rewrite path already reads back after writing in the full-outcome variants.

### Trade-off accepted

Callers can no longer use rewrite to **delete** rows by passing a shorter list. Surveyed callers:

- `apply_notification_state_update_with_options` (the dismiss/mark-read path): RMW under a continuously-held exclusive
  lock and always passes back **all** rows. Merge-vs-replace produces identical bytes in that codepath.
- `NotificationStateUpdateWire::RewriteAll`: same call path, same lock-held property.
- `src/sase/agent/names/_migration.py:_rewrite_notifications`: bypasses the Rust API; writes JSONL directly. Unaffected.
- Tests: every direct `rewrite_notifications*` call is initial-state setup against a fresh tempdir. None rewrites with a
  shorter list to delete an existing row.

Documented as a comment on the rewrite function. If a future caller genuinely needs replacement semantics we can
introduce a separate `replace_notifications` API, but no caller needs it today.

## Implementation steps (in `../sase-core/`)

### 1. Add a merge helper alongside `rewrite_notifications_unlocked`

File: `crates/sase_core/src/notifications/store.rs`.

- Introduce `fn merge_and_rewrite_notifications_unlocked(path, input: &[NotificationWire]) -> Result<(), String>`:
  1. Call `read_rows_unlocked(path, include_dismissed=true)` to read existing rows + stats (we must include dismissed so
     we don't silently drop dismissed concurrent appends; invalid/blank lines are already filtered by
     `read_rows_unlocked` and should not be resurrected — that's a separate, existing data-hygiene property).
  2. Build a `BTreeSet<&str>` (or `HashSet`) of input row ids.
  3. Build the final write list: `input` rows first (preserving caller order), then existing rows whose `id` is not in
     the input id set (preserving file order).
  4. Hand off to a small inner helper (extracted from current `rewrite_notifications_unlocked`) that does the tempfile +
     fsync + rename + parent fsync. Both functions reuse this writer to avoid duplicating the durability dance.

- Replace the two public callers (`rewrite_notifications_with_options` and the `RewriteAll` branch of
  `apply_notification_state_update_with_options`) to call `merge_and_rewrite_notifications_unlocked`. Keep
  `rewrite_notifications_unlocked` available for the state-mutation path
  (`if changed_count > 0 { rewrite_notifications_unlocked(...) }`) where the caller already holds the lock and passes
  all rows — that path doesn't need merge semantics but using merge is also safe (identical result). For simplicity,
  route every internal call through the merge helper. The extra read is cheap and keeps the invariant unconditional.

- Add a short comment above the helper explaining the contract: "Rewrite is a _merge_: caller's rows win on id
  collision; rows present on disk but absent from the input are preserved (they may be concurrent appends from another
  thread)."

### 2. Tests in `sase-core`

Add the following to `crates/sase_core/tests/notification_store_parity.rs`:

- `notification_rewrite_preserves_unseen_rows`: write rows A,B,C directly; call
  `rewrite_notifications(path, &[A_modified, D])`; assert final file contains A_modified, B, C, D (A's mutation applied,
  B and C preserved, D appended).
- `notification_rewrite_counts_preserves_unseen_rows`: same as above with the counts variant.
- `notification_rewrite_all_preserves_unseen_rows`: same property exercised via
  `apply_notification_state_update(path, RewriteAll { ... })`.

Keep the existing

- `notification_append_plus_rewrite_concurrency_preserves_valid_rows`
- `notification_append_plus_rewrite_counts_concurrency_preserves_valid_rows` unchanged — they're now non-flaky.

Existing tests that should still pass unchanged:

- All `notification_rewrite_*` byte-identical parity tests (input rows are written in caller order, identical bytes).
- All `apply_notification_state_update` / dismiss / mark-read tests (they pass full row sets after mutation; merge with
  empty diff produces identical output).
- `notification_loads_legacy_defaults_and_skips_bad_rows` (rewrite path doesn't touch read-side filtering).

### 3. Verification

In `../sase-core/`:

```
cargo fmt --all
cargo clippy --workspace --all-targets -- -D warnings
cargo test -p sase_core --test notification_store_parity
just rust-check    # if a justfile exists in sase-core; otherwise the three commands above cover it
```

Stress-run the previously-failing test ≥100× locally to confirm the race is closed:

```
for i in $(seq 1 100); do cargo test -p sase_core --test notification_store_parity \
  notification_append_plus_rewrite_counts_concurrency_preserves_valid_rows --quiet 2>&1 \
  | grep -E "result|FAILED" ; done
```

In `sase_10` (this repo):

```
just install   # workspace requires editable reinstall after the Rust .so changes
just check     # ruff + mypy + pytest, exercises the Python facade
```

The Python facade in `src/sase/core/notification_store_facade.py` and `src/sase/notifications/store.py` is unchanged —
they just call through PyO3 wrappers whose signatures and return shapes are stable. No wire schema bump, no migration.

### 4. Commit & PR

Cross-repo:

- `../sase-core` gets a feat/fix commit: `fix(notifications): make rewrite merge concurrent appends (sase-35.3)` —
  implementation + new tests.
- `sase_10` requires no source change. If a `.so` artifact or `Cargo.lock` is vendored or pinned, bump as needed.
  (Verify by checking `pyproject.toml` for any sase-core version pin.)

The `bead-backend` CI job checks out `sase-org/sase-core` on each run, so the PR in sase-core alone unblocks the failing
job — provided the sase-core PR lands first, or both PRs are coordinated.

## Out of scope

- Optimistic concurrency control / version tokens (option B in the analysis). Heavier API surface, would require Python
  facade + test changes for no additional benefit given option A's verified caller analysis.
- RAII lock guards from `read_notifications_snapshot` (option C). Would break the Python facade.
- Test relaxation (option D). Hides the bug.
- Deduplication of duplicate-id rows present on disk _before_ a rewrite. Pre-existing data-hygiene concern, orthogonal
  to this race fix.
