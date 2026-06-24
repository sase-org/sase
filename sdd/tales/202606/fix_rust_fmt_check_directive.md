---
create_time: 2026-06-24 06:40:42
status: done
prompt: sdd/prompts/202606/fix_rust_fmt_check_directive.md
---
# Fix `rust-fmt-check` CI failure in `directive.rs`

## Problem

The `rust-fmt-check` CI step fails with:

```
Diff in .../sase-core/crates/sase_core/src/editor/directive.rs:337:
-        assert!(
-            build_directive_completion_candidates("%approve")
-                .candidates
-                .is_empty()
-        );
+        assert!(build_directive_completion_candidates("%approve")
+            .candidates
+            .is_empty());
error: Recipe `rust-fmt-check` failed on line 412 with exit code 1
```

CI runs `cargo fmt --all -- --check` against the **sase-core** repository (the `rust-fmt-check` recipe in the sase
repo's `Justfile`, line 412).

## Root Cause

This is **not** a toolchain/version mismatch and **not** a flaky CI issue. The committed source is genuinely
unformatted:

- The offending block lives in the test `approve_is_a_hidden_deprecated_alias_of_plan` in
  `crates/sase_core/src/editor/directive.rs`. It was introduced by commit `50c6e82` (_feat(editor)!: add %tale directive
  and repurpose %plan for plan auto-approval (sase-56.1)_).
- The author wrote the `assert!(...)` in a hand-expanded multi-line form. Under the repo's `rustfmt.toml`
  (`max_width = 80`), rustfmt's canonical form keeps `assert!(` on the same line as the first method-chain argument and
  closes with `);` at the end — the "compressed" form CI demands.
- Running `cargo fmt --all -- --check` locally with **the same stable toolchain CI uses** (rustfmt 1.9.0-stable, pinned
  via sase-core's `rust-toolchain.toml` → `channel = "stable"`) reproduces the **identical** diff. So the problem is
  purely that `cargo fmt` / `just rust-fmt` was not run before committing `50c6e82`.
- There is no local pre-commit guard for Rust formatting in the sase-core repo, so unformatted Rust can be committed and
  is only caught downstream by the CI `rust-fmt-check` step.

A full-repo `cargo fmt --all -- --check` reports **exactly one** diff — this single block in `directive.rs`. Nothing
else in sase-core is unformatted, so the fix is fully contained.

## Fix

The change is entirely within the **sase-core** repository; no files in the sase (primary) repo change.

1. In the sase-core repo, reformat the source with the canonical formatter rather than editing by hand (to guarantee the
   output matches what CI expects):
   - `cargo fmt --all` run from the sase-core repo root, or equivalently `just rust-fmt` run from the sase repo (which
     delegates to `cd <sase_core_dir> && cargo fmt --all`).
   - This rewrites only the `assert!(...)` block at `crates/sase_core/src/editor/directive.rs:~340` into the compressed
     form:
     ```rust
     assert!(build_directive_completion_candidates("%approve")
         .candidates
         .is_empty());
     ```

2. Verify the fix:
   - `cargo fmt --all -- --check` in sase-core must exit cleanly with no diff.
   - Run `just rust-check` from the sase repo (fmt-check + clippy + test against sase-core) to confirm the reformat
     didn't disturb anything and the test still compiles/passes.

3. Commit the formatting-only change to the sase-core repo and push so the sase CI `rust-fmt-check` step goes green.
   (Commit via the standard SASE commit workflow; this plan does not commit anything by itself.)

## Scope / Non-Goals

- This is a formatting-only fix. No behavior, test logic, or directive semantics change.
- **Optional follow-up (not required to unblock CI):** the underlying process gap is that nothing runs `rustfmt` locally
  before commit in sase-core. A future hardening could add a pre-commit / commit-time `cargo fmt --check` guard (or wire
  `just rust-fmt-check` into the sase commit hooks) so unformatted Rust is caught before it reaches CI. Call this out
  for the user but keep it out of the core fix unless they want it.

## Verification Checklist

- [ ] `cargo fmt --all -- --check` (sase-core) exits 0 with no diff.
- [ ] `just rust-check` (from sase repo) passes (fmt-check + clippy + test).
- [ ] `git diff` in sase-core shows only the reformatted `assert!` block in `directive.rs` — no other files touched.
