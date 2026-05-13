---
title: Remove Cross-Workspace Bead Reads
bead_id: sase-3c
tier: epic
create_time: 2026-05-12 22:55:25
status: wip
prompt: sdd/prompts/202605/remove_cross_workspace_bead_reads.md
---

# Goal

Make `sase bead` treat the current repository's `sdd/beads/issues.jsonl` as the single source of truth. The command
should stop reading, merging, deduplicating, or allocating IDs from sibling workspace bead directories such as
`../sase_101/sdd/beads` or legacy `.sase_beads/` stores.

This is not just a CLI display change. Current behavior leaks cross-workspace state through:

- `sase.bead.cli_common.get_read_view()`, which returns `MergedBeadView` when workspace resolution succeeds.
- `sase.bead.workspace`, which discovers primary and numbered sibling workspace bead directories.
- `sase.core.bead_read_facade` and `../sase-core` merged read APIs.
- `BeadProject._workspace_beads_dirs()`, ID allocation, and Rust `workspace_beads_dirs` mutation input.
- tests, docs, and helper bridges that encode merged workspace behavior.

# Non-Goals

- Do not change non-bead workspace allocation, agent launch, ChangeSpec, or VCS provider behavior.
- Do not remove local non-version-controlled SDD mode unless a phase proves it is directly part of `sase bead`
  cross-workspace reads. The requested truth for this repo is `sdd/beads/issues.jsonl`; local-mode cleanup should be
  limited to keeping existing behavior from accidentally reading sibling workspaces.
- Do not perform broad historical SDD rewrite churn. Update current docs and runtime-facing skill/help text; leave old
  prompt transcripts alone unless a test or generated surface depends on them.
- Do not keep an API named "merged" as a compatibility shim if it is no longer semantically merged. Either delete it or
  make remaining callers use a single-store API.

# Current Shape

Python CLI:

- `find_beads_location()` decides the writable bead store.
- `get_project()` opens `BeadProject` for writes.
- `get_read_view()` currently calls `get_project_beads_dirs()` and returns `MergedBeadView` when possible.
- Read-only handlers (`list`, `show`, `ready`, `blocked`, `stats`) use `get_read_view()`, so normal CLI reads can
  display issues from sibling workspace stores.

Workspace discovery:

- `src/sase/bead/workspace.py` resolves a primary workspace from CWD, project files, or workspace providers.
- `_enumerate_workspace_beads_dirs()` returns the primary store plus numbered sibling stores and legacy `.sase_beads`
  stores in version-controlled mode.
- `get_all_project_beads_dirs()` and `get_project_beads_dirs_for_project()` build on that same enumeration.

Mutation and ID allocation:

- `BeadProject.create()` passes `workspace_beads_dirs=self._workspace_beads_dirs()` into Rust.
- `BeadProject._next_child_id()` and `_next_top_level_counter()` also consult `_workspace_beads_dirs()`.
- Rust `BeadCreateRequestWire.workspace_beads_dirs` and mutation helpers use sibling JSONL files to avoid ID reuse. That
  keeps sibling workspace stores in the write path even after CLI reads are changed.

Rust core:

- `../sase-core/crates/sase_core/src/bead/read.rs` implements `merge_workspace_issues()` and merged `show/list/ready`
  APIs.
- `../sase-core/crates/sase_core_py/src/lib.rs` exposes `bead_merged_*` PyO3 bindings.
- Python `sase.core.bead_read_facade` wraps those bindings.

Other readers:

- Mobile/helper bead operations use `MergedBeadView` and project bead-dir enumeration. They may still need cross-project
  listing, but should not read multiple workspace copies for the same project.
- Docs currently document multi-workspace and legacy `.sase_beads/` read behavior.

# Target Behavior

- `sase bead list/show/ready/blocked/stats` reads exactly one store: the current repo's `sdd/beads/issues.jsonl` in
  version-controlled mode.
- `sase bead create/update/open/close/rm/dep/work/sync/doctor` mutates or reads exactly that same current-repo store.
- ID allocation uses only the current store's `config.json` and current `issues.jsonl`.
- Running `sase bead` inside a numbered sibling workspace reads that workspace's own checked-out `sdd/beads`, not the
  primary workspace and not any sibling directories.
- Legacy `.sase_beads/` directories are not part of normal `sase bead` reads. If migration support still exists, it must
  be explicit and not used by default CLI reads.
- Cross-project helper surfaces, if retained, read one canonical store per project and never merge numbered siblings.

# Phase Split

Each phase is intended for one distinct agent instance. Agents should read this full plan, then own only their phase's
write scope.

## Phase 1: Contract And Python CLI Read Path

Purpose: make the user-visible `sase bead` read commands single-store without touching Rust API deletion yet.

Write scope:

- `src/sase/bead/cli_common.py`
- `src/sase/bead/cli_query.py` only if needed for type fallout
- focused CLI tests under `tests/test_bead/`
- current bead docs/help text only where tests require it

Work:

- Replace `get_read_view()` with a single-store `BeadProject` view. It should use the same location that write commands
  use, so read and write commands agree on the source of truth.
- Ensure read commands do not import or instantiate `MergedBeadView`.
- Add or update CLI tests that create different beads in a primary and numbered sibling workspace and prove:
  - running from the primary sees only primary `sdd/beads/issues.jsonl`
  - running from the sibling sees only sibling `sdd/beads/issues.jsonl`
  - duplicate IDs in siblings are not merged by latest `updated_at`
- Keep this phase narrow: do not delete Rust merged APIs yet.

Exit criteria:

- Targeted `sase bead list/show/ready/blocked/stats` tests pass.
- A search shows no read-only CLI handler reaches `MergedBeadView`.

## Phase 2: Mutation And ID Allocation Truth

Purpose: remove hidden cross-workspace state from create and child-ID allocation.

Write scope:

- `src/sase/bead/project.py`
- `src/sase/bead/ids.py`
- `src/sase/core/bead_mutation_facade.py`
- matching tests under `tests/test_bead/` and `tests/test_core_facade/`
- `../sase-core/crates/sase_core/src/bead/mutation.rs`
- `../sase-core/crates/sase_core_py/src/lib.rs`
- `../sase-core/crates/sase_core/tests/`

Work:

- Remove `workspace_beads_dirs` from Python create calls and from the Rust create request wire.
- Make top-level and child ID allocation inspect only the current store.
- Delete or rewrite Python tests that currently expect sibling stores to advance counters.
- Delete or rewrite Rust mutation tests that rely on `workspace_beads_dirs`.
- Confirm `sase bead create` in a sibling checkout may allocate an ID based on that checkout's local `sdd/beads`; that
  is the intended consequence of single-source-per-repo semantics.

Exit criteria:

- No production create path accepts or passes `workspace_beads_dirs`.
- Python and Rust targeted mutation tests pass.

## Phase 3: Remove Merged Read APIs And Workspace Bead Enumeration

Purpose: delete the obsolete implementation surface after callers are gone.

Write scope:

- `src/sase/bead/workspace.py`
- `src/sase/core/bead_read_facade.py`
- `tests/test_bead/test_workspace_resolution.py`
- `tests/test_bead/test_project_rust_delegation.py`
- `tests/test_core_facade/test_bead_read.py`
- `../sase-core/crates/sase_core/src/bead/read.rs`
- `../sase-core/crates/sase_core/src/bead/mod.rs`
- `../sase-core/crates/sase_core/src/lib.rs`
- `../sase-core/crates/sase_core_py/src/lib.rs`
- `../sase-core/crates/sase_core/tests/bead_read_parity.rs`

Work:

- Remove `MergedBeadView` and merged read facade functions from Python.
- Remove Rust `merge_workspace_issues()` and `bead_merged_*` public exports unless a non-CLI caller still proves a need.
- Keep workspace resolution helpers only if they are still needed for path normalization or storage-location selection.
  Rename or split them so their purpose is not "bead dirs across workspaces."
- Convert tests from "merged workspace" expectations to "single current store" expectations, or delete tests whose only
  purpose was merged behavior.

Exit criteria:

- `rg "MergedBeadView|merged_.*bead|bead_merged|merge_workspace_issues|workspace_beads_dirs"` has no production matches
  except historical docs/prompts or clearly unrelated text.
- Rust and Python targeted read facade tests pass.

## Phase 4: Helper Bridges And Cross-Project Readers

Purpose: decide and implement the non-CLI compatibility boundary without reintroducing sibling workspace merges.

Write scope:

- `src/sase/integrations/_mobile_helper_beads.py`
- `src/sase/integrations/mobile_helpers.py`
- `tests/test_mobile_helper_beads.py`
- helper docs under `docs/integrations.md` if needed

Work:

- Preserve cross-project listing only if current mobile/helper UX requires it, but change each project group to one
  canonical store path.
- For explicit project reads, resolve the project's primary/canonical `WORKSPACE_DIR/sdd/beads` store only.
- For all-known-project reads, iterate projects but do not include numbered sibling workspace stores or legacy
  `.sase_beads` stores.
- Update `workspace_display` to represent the canonical project store, not whichever merged store won.
- Remove partial-failure tests that only exist because multiple sibling stores could be unavailable; keep tests for a
  missing canonical store.

Exit criteria:

- Mobile/helper bead tests pass with no dependency on `MergedBeadView`.
- Helper code cannot read numbered sibling stores for the same project.

## Phase 5: Documentation, Skills, And User-Facing Cleanup

Purpose: make user-facing guidance match the new source-of-truth rule.

Write scope:

- `docs/beads.md`
- `docs/architecture.md`
- `docs/integrations.md` if helper semantics changed
- `src/sase/xprompts/skills/sase_beads.md`
- CLI onboarding/help strings under `src/sase/bead/`
- current tests/golden output affected by wording

Work:

- Remove or rewrite the `Multi-Workspace Support` documentation.
- State clearly that version-controlled bead state lives in `sdd/beads/issues.jsonl` for the current repo checkout.
- Remove guidance that normal reads recognize `.sase_beads/` or merge primary/sibling workspaces.
- Keep any migration-only mention explicit: "legacy migration command/path", not default read behavior.

Exit criteria:

- Current docs and generated skill text do not advertise cross-workspace bead reads.
- Golden CLI/help tests are updated.

## Phase 6: Full Verification And Dead-Code Sweep

Purpose: ensure the phased work is complete across both repos.

Write scope:

- Tests only, unless final search finds missed production references.

Work:

- In this repo, run `just install` if needed, then targeted bead suites:
  - `pytest tests/test_bead tests/test_core_facade/test_bead_read.py tests/test_mobile_helper_beads.py`
  - any CLI golden tests touched by prior phases
- In this repo, run `just check` before final handoff because production files changed.
- In `../sase-core`, run the appropriate Rust checks:
  - `cargo fmt --all --check`
  - `cargo test --workspace`
  - or the repo's `just check` if present and documented
- Run final searches in both repos for:
  - `MergedBeadView`
  - `workspace_beads_dirs`
  - `bead_merged`
  - `merge_workspace_issues`
  - `.sase_beads`
  - `Multi-Workspace Support`
- Classify any remaining matches as historical, migration-only, or unrelated. Production/runtime matches should be
  fixed, not waived.

Exit criteria:

- All required checks pass in every modified repo.
- Remaining references are documented and intentional.
- `sase bead` read/write semantics are single-store and centered on the current repo's `sdd/beads/issues.jsonl`.

# Risks And Sequencing Notes

- Phase 1 alone changes visible read behavior but leaves create/ID allocation reading sibling stores. Do not stop the
  overall project there.
- Phase 2 changes ID allocation semantics. Duplicate IDs across workspaces become possible until bead JSONL changes are
  merged through normal VCS flow. This is consistent with the requested single-source rule, but it should be called out
  in release notes or docs.
- Removing Rust merged APIs requires updating the Python dependency on `sase_core_rs`. If packaging pins expose an older
  installed extension during local tests, the agent should run the repo's install/build workflow before judging
  failures.
- Mobile/helper bridge behavior is adjacent to the `sase bead` command. The implementation should not preserve sibling
  merges there as a backdoor unless the user explicitly narrows the scope.
