---
create_time: 2026-05-15 13:03:32
status: done
prompt: sdd/prompts/202605/fix_beads_backend_clippy.md
---
# Fix `beads-backend` Clippy Failures in `sase-core`

## Context

GitHub Actions `beads-backend` job is failing because `cargo clippy` (run with `-D warnings`) reports three lints in
`../sase-core/crates/sase_core/src/bead/events.rs`. Per the `memory/short/rust_core_backend_boundary.md` convention,
this code lives in the sibling `sase-core` repo, so all edits and verification happen there — not in `sase_105`.

The lints are mechanical and clippy's suggested replacements are correct. There is no design decision involved; this
plan just records scope and verification.

## Problems

1. **`clippy::clone_on_copy` (line 107)** — `self.operation.clone()` is called on `BeadEventOperationWire`, which
   derives `Copy` (see the derive on line 111–113). Cloning a `Copy` type is redundant.

2. **`clippy::unnecessary_sort_by` (line 288)** — `issues.sort_by(|a, b| event_issue_key(a).cmp(&event_issue_key(b)))`
   is a closure that just defers to a key function; clippy prefers `sort_by_key`.

3. **`clippy::unnecessary_sort_by` (line 387)** — same pattern as #2, applied to `reduced`.

## Approach

Apply clippy's suggested fixes verbatim:

| Line | Before                                                                   | After                                            |
| ---- | ------------------------------------------------------------------------ | ------------------------------------------------ |
| 107  | `.validate_for(self.operation.clone(), &self.issue_id)`                  | `.validate_for(self.operation, &self.issue_id)`  |
| 288  | `issues.sort_by(\|a, b\| event_issue_key(a).cmp(&event_issue_key(b)));`  | `issues.sort_by_key(\|a\| event_issue_key(a));`  |
| 387  | `reduced.sort_by(\|a, b\| event_issue_key(a).cmp(&event_issue_key(b)));` | `reduced.sort_by_key(\|a\| event_issue_key(a));` |

No call-site changes are needed:

- `validate_for` already takes the operation by value (it must, since `BeadEventOperationWire: Copy`), so dropping
  `.clone()` is API-compatible.
- `sort_by_key` returns the same ordering as the closure-based `sort_by` given the existing key function
  `event_issue_key`.

## Verification

In `../sase-core`:

```bash
cargo clippy --all-targets -- -D warnings
cargo test
```

The clippy run must come back clean (the failing lints were the only blockers). Tests should remain green since behavior
is unchanged.

If `sase-core` has its own `just check` (analogous to this repo's), prefer that as the canonical pre-commit check.

## Out of Scope

- Any other clippy warnings not surfaced by this CI run.
- Changes in `sase_105` — none are needed; the binding (`sase_core_rs`) consumes the wire types unchanged.
- Refactoring `event_issue_key` or the validation flow.

## Commit & Push

Single commit in `sase-core` containing only the three edits, with a message along the lines of
`fix(bead/events): satisfy clippy clone_on_copy and unnecessary_sort_by lints`. Push to the branch CI is checking.
