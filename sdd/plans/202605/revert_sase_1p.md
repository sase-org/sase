---
create_time: 2026-05-01 03:19:41
status: done
prompt: sdd/prompts/202605/revert_sase_1p.md
---
# Revert sase-1p Agent Compose Rust Migration

## Goal

Revert the full `sase-1p` agent-loader orchestration / status-override Rust migration and its dependent follow-up fixes,
while preserving unrelated work that landed around it. The rollback spans this `sase` workspace and the sibling
`../sase-core` repo because the bead plan explicitly added Rust `agent_compose` code there.

## Current Context

`sase bead show sase-1p` reports a closed plan bead:

- `sase-1p`: Agent Loader Orchestration & Status Override Rust Migration
- children `sase-1p.1` through `sase-1p.8`, all closed
- linked plan: `../sase/plans/202605/agent_loader_orchestration_status_override_rust.md`

The direct bead-phase work in this repo is visible in these commits:

- `7f9c2f03` - SDD/spec plan for `agent_loader_orchestration_status_override_rust`
- `84f753e1` - create plan beads
- `e2f5f55f` - record epic kickoff
- `731b25b1` - phase 1 Python wire/reference contract
- `0279157e` - close phase 1 bead
- `369d70a7` - update phase 1 bead note
- `85b8f041` - phase 2 handoff note
- `cbb8908e` - phase 3 PyO3/facade parity
- `7bb61f39` - phase 4 TUI shadow integration
- `cbbdbe00` - phase 5 opt-in Rust route
- `e807fda4` - re-work bead metadata
- `2c44f11a` - phase 6 performance gate
- `ff74d087` - phase 7 default Rust routing
- `8db66777` - phase 8 transient override helper
- `e4b7fb44` - dismissed-loader fix and plan/bead completion

There are also dependent follow-up commits without direct `sase-1p.*` markers that should be treated as part of the
rollback unless inspection proves they contain independent value:

- `d5dbc286` - split agent loader helpers, including compose backend helpers
- `5ceffab5` - fix timestamp crash in `agent_compose_wire`
- `6f5859d6` - SDD/spec plan for the Rust waiting-startup fix
- `44f44673` - make Agents tab composition Rust-only
- `fa84f30f` - normalize timestamps from agent compose wire

In `../sase-core`, the related Rust-side commits are:

- `cfb13cb` - pure Rust `agent_compose` core
- `0e348a6` - PyO3 `compose_agent_list` binding
- `73820d7` - running-claim metadata enrichment for Rust product path

## Rollback Strategy

Use non-destructive inverse commits, not history rewriting. The work is already on `master`/`origin/master`, so the
implementation should create revert commits or staged inverse changes rather than resetting branch history.

Keep the working trees clean before starting. If either repo is dirty, stop and inspect before changing anything.

Revert in reverse chronological order to respect dependencies:

1. In `sase`, first revert dependent follow-ups that sit on top of the migration:
   - `fa84f30f`
   - `44f44673`
   - `6f5859d6`
   - `5ceffab5`
   - `d5dbc286`
2. In `sase`, then revert the direct `sase-1p` cluster:
   - `e4b7fb44`
   - `8db66777`
   - `ff74d087`
   - `2c44f11a`
   - `e807fda4`
   - `cbbdbe00`
   - `7bb61f39`
   - `cbb8908e`
   - `85b8f041`
   - `369d70a7`
   - `0279157e`
   - `731b25b1`
   - `e2f5f55f`
   - `84f753e1`
   - `7f9c2f03`
3. In `../sase-core`, revert the Rust-side dependency in reverse order:
   - `73820d7`
   - `0e348a6`
   - `cfb13cb`

Prefer `git revert --no-commit <commits...>` per repo so conflicts can be resolved once and reviewed as a single
rollback. If conflicts are excessive, split into smaller batches: follow-up fixes, loader/routing commits, docs/metadata
commits, then Rust core commits.

## Conflict Handling

Expect conflicts around:

- `src/sase/ace/tui/models/agent_loader.py`
- `src/sase/ace/tui/models/agent_loader_backend.py`
- `src/sase/ace/tui/models/agent_loader_ordering.py`
- `src/sase/ace/tui/models/agent_loader_status.py`
- `src/sase/core/agent_compose_facade.py`
- `src/sase/core/agent_compose_wire.py`
- `tests/test_agent_loader.py`
- `tests/test_core_agent_compose.py`
- `tests/perf/bench_agent_compose.py`
- `sdd/beads/issues.jsonl`
- `docs/rust_backend.md`
- `../sase-core/crates/sase_core/src/lib.rs`
- `../sase-core/crates/sase_core/src/agent_compose/`
- `../sase-core/crates/sase_core_py/src/lib.rs`

Resolve conflicts toward the pre-`sase-1p` Python agent-loader behavior while keeping unrelated later changes,
especially pyvision, axe maintenance, bead CLI splits, general timestamp UI fixes, and unrelated docs/config workflow
updates.

After the revert, remove any orphaned `agent_compose` references in Python, tests, docs, and Rust exports. A successful
rollback should leave no product route, facade, wire type, benchmark, or PyO3 binding for `compose_agent_list`.

## Bead and Documentation State

Because the user requested a revert of all commits related to `sase-1p`, revert the bead/spec/plan metadata that created
and closed the epic rather than manually editing it into a new state. After the inverse commits are staged, run:

- `sase bead show sase-1p`
- `rg -n "sase-1p|agent_compose|compose_agent_list|AgentCompose|SASE_AGENT_COMPOSE"`

Use those results to catch leftover metadata or references that the commit-level reverts did not remove because of later
conflict resolution.

## Verification

In this repo:

- Run `just install` first if the environment has not been refreshed.
- Run focused tests around the restored Python loader path:
  - `just test tests/test_agent_loader.py tests/test_agent_loader_status_overrides.py tests/test_agent_loader_dedup_pid.py tests/test_agent_loader_dedup_vcs.py tests/test_agent_loader_changespec.py`
- Run `just check` before finishing, per repo instructions.

In `../sase-core`, if files changed:

- Run `cargo fmt --all -- --check`
- Run `cargo clippy --workspace --all-targets -- -D warnings`
- Run `cargo test --workspace`

If the full checks are too slow or fail for pre-existing reasons, capture the exact failing command and the first
relevant failure. Do not mask failures by dropping unrelated changes.

## Completion Criteria

- `git status --short` shows only the intended rollback changes in each touched repo.
- No `agent_compose` / `compose_agent_list` product, facade, test, benchmark, doc, or Rust export remains unless it
  predated `sase-1p`.
- The Agents tab loader is back on the Python composition path.
- Unrelated commits that landed around the migration remain intact.
- Verification has been run and reported.
