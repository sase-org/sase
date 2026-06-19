---
create_time: 2026-06-19 08:06:23
status: done
prompt: sdd/prompts/202606/reverse_bead_search_order.md
---
# Plan: Reverse `sase bead search` Result Ordering

## Context

`sase bead search` is implemented primarily in the Rust core. The Python CLI path delegates through
`sase.core.bead_read_facade` to the Rust `bead_search` binding, and the fast-path CLI command calls Rust
`execute_bead_cli` directly. The pure search behavior lives in `crates/sase_core/src/bead/search.rs` in the sibling
`sase-core` workspace.

The current search engine filters by status/type/tier through `list_issues_in_issues`, which sorts beads by `created_at`
ascending. Search then scans that ordered list and applies `--limit` as matches are found. This means oldest matching
beads appear first, and `--limit N` returns the oldest N matches.

The requested behavior is the same creation-time ordering but reversed: newer matching beads before older matching
beads. This should apply consistently to compact, JSON, and full output because all three render the same match list.

## Goals

- Make `sase bead search` return matching beads newest-first by bead `created_at`.
- Keep `sase bead list`, `ready`, `blocked`, and child ordering unchanged unless they already consume search results.
- Preserve all existing filters and matching semantics.
- Apply `--limit` after the newest-first ordering so `--limit 3` returns the three newest matches.
- Add focused regression coverage in Rust, where the canonical search ordering is produced.
- Run targeted Rust tests and the repo-required verification for any edited checkout.

## Implementation Steps

1. Update the Rust search engine in `sase-core`.
   - Change `search_issues_in_issues` so it builds the filtered, creation-sorted candidate list, then iterates it in
     reverse creation order for matching.
   - Prefer a narrowly scoped change in `crates/sase_core/src/bead/search.rs`, rather than changing
     `list_issues_in_issues` or shared `sort_by_created_at`, because other bead read commands intentionally use the
     current ascending order.
   - Ensure the limit check still happens while accumulating matches, after reversing the candidate order.

2. Update Rust search tests.
   - Replace the current `keeps_list_ordering` expectation with a test that explicitly asserts newer matches come before
     older matches.
   - Update the limit regression so it proves `limit` keeps the newest matching beads, not the oldest.
   - Add or adjust a same-timestamp case if needed to document the existing tie-breaker behavior. If the current search
     helper only has deterministic creation ordering from `list_issues_in_issues`, avoid inventing broader tie-breaking
     behavior unless the existing helper already provides it.

3. Check CLI coverage.
   - Review the Rust CLI search tests in `crates/sase_core/src/bead/cli.rs`.
   - If the existing CLI tests do not exercise multiple matches, add a compact or JSON test that shows the rendered CLI
     output follows newest-first order. This protects the fast path used by normal `sase bead search` invocations.

4. Check Python fallback expectations.
   - The Python fallback calls `view.search(...)`; once the Rust binding returns matches newest-first, the Python
     renderers should naturally inherit the order.
   - No Python behavior change should be needed unless a Python test encodes the old order. If such a test exists,
     update it to the new contract.

5. Verification.
   - In `sase-core`, run focused Rust tests for bead search and CLI search.
   - Run the broader Rust check appropriate for the sibling checkout, at minimum `cargo test -p sase_core bead::search`
     and the affected CLI tests. If practical, run the full `cargo test -p sase_core`.
   - In the `sase` checkout, run `just install` before `just check` if any files in this repo are changed beyond the
     plan file, per the repo instructions.

## Risks and Mitigations

- `--limit` could accidentally keep the oldest matches if applied before reversing. Mitigation: reverse candidates
  before matching/limiting, and update the limit test to assert newest-first truncation.
- A shared ordering helper change could affect unrelated bead commands. Mitigation: keep the change local to search.
- CLI fast-path and Python fallback could drift. Mitigation: rely on the Rust search binding as the single source of
  truth and add a CLI-level regression if current coverage only tests the pure search function.

## Expected Files

- `../sase-core/crates/sase_core/src/bead/search.rs`
- Possibly `../sase-core/crates/sase_core/src/bead/cli.rs` for a CLI-level ordering regression test
