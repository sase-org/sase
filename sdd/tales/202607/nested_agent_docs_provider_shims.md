---
create_time: 2026-07-06 19:31:34
status: done
prompt: sdd/prompts/202607/nested_agent_docs_provider_shims.md
---
# Plan: Nested Agent Document Provider Shims

## Goal

Fix `sase init` / `sase init memory` so every discovered project `AGENTS.md` file gets equivalent provider instruction
files in the same directory, not just the project root and home root. If a nested directory contains `AGENTS.md`, SASE
should copy that file's final contents into each configured provider instruction file that SASE manages, matching
current root behavior.

## Current Understanding

- The root memory initialization path already writes provider instruction files as byte-for-byte copies of the root
  `AGENTS.md`.
- The shared provider shim planner lives in the AMD helper layer and is already capable of planning writes/deletes for a
  single directory.
- The read-only `sase memory agent-docs list` inventory already recursively discovers project `AGENTS.md` files and
  prunes directories such as `.git`, `.sase`, `node_modules`, build output, virtualenvs, and caches.
- The bug is in the memory init orchestration: root and home plans call the provider shim planner, but nested project
  agent documents are not included in the init plan/apply path. Bare `sase init` only reports what the memory planner
  reports, so it currently misses this drift.

## Implementation Approach

1. Reuse the existing project `AGENTS.md` discovery rules for nested project agent documents instead of adding a second
   recursive walk with different pruning behavior.
2. Add a small planning/apply helper for "additional agent document directories":
   - Ignore the memory root's own `AGENTS.md`, because it is already handled by `plan_memory_root` /
     `initialize_memory_root`.
   - For every other discovered project `AGENTS.md`, read its current content.
   - Run the existing provider shim planner against that file's parent directory using that content.
   - Surface planned provider writes/deletes as `MemoryFileChange` actions so `sase init --check` and bare `sase init`
     show drift.
   - Apply the planned writes/deletes during `sase init memory` / bare `sase init --yes`.
3. Preserve existing safety behavior from the provider shim planner:
   - Existing exact provider copies are no-ops.
   - Legacy provider shims can be repaired/migrated.
   - Legacy chezmoi `.tmpl` handling remains scoped to home/chezmoi roots, not project subdirectories.
   - Custom delete safety remains enforced through the existing deletion helper.
4. Ensure project commits include nested provider instruction files by adding these nested written/deleted paths to the
   same project result that is passed into the current git deployment path.

## Tests

Add focused tests around the memory init layer:

- Planning test: a project with `demos/tapes/AGENTS.md` and missing provider files should produce create actions for the
  provider instruction files next to that nested `AGENTS.md`.
- Apply/idempotence test: running memory init should create provider files in the nested directory as byte-for-byte
  copies of that nested `AGENTS.md`; a follow-up plan should be empty.
- Bare init check test: with nested provider files missing, bare `sase init --check` should report memory drift instead
  of "No init subcommands need to run."
- Pruning/regression test, if not naturally covered by reusing inventory discovery: nested `AGENTS.md` under ignored
  directories such as `.sase` or `node_modules` should not create provider actions.

## Verification

- Run the focused memory/init tests first.
- Because source/test files will change in this repo, run `just install` and then `just check` before finalizing, per
  repository instructions.
- Verify the user's concrete case by running the updated init/check behavior against the repository state where
  `demos/tapes/AGENTS.md` exists.

## Commit

After implementation and verification, commit the code/test changes using the repository's required SASE commit
workflow.
