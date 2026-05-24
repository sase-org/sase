---
create_time: 2026-05-24 13:34:05
status: wip
prompt: sdd/prompts/202605/a90_duplicate_code_child.md
---
# Fix duplicate `-code` child entry under plan-chain root in sase ace TUI

## Problem

In the `sase ace` "Agents" tab, the active plan-chain root `@a90` is showing two near-identical child rows for the same
coder follow-up agent:

```
≡ 🤖 sase (TALE APPROVED) ×7 −3 @a90                            🏃‍♂️ 2m50s
  └─ 1/1-plan 🤖 main (DONE) ◆ @a90-plan                11:41:47 · 2m01s
  └─ 1/1-code 🤖 sase (TALE APPROVED) ◆ @a90-code                 🏃‍♂️ 24s
  └─ 1/1-code 🤖 a90-code (TALE APPROVED) ◆ @a90-code             🏃‍♂️ 24s   ← DUPLICATE
  └─ 1e/1 🐚 diff (DONE) ▼#gh
```

Both `1/1-code` rows reference the same `@a90-code` agent (gold @-tag), the same elapsed time, and the same status. The
visible difference is the label after 🤖 (`sase` vs `a90-code`), which means two distinct `Agent` objects are being
placed under the root.

This regressed (or was first surfaced) by commit `ea47257e4` (_fix: group dotted agent families under root_), which made
`_grouping_name()` prefer `agent.agent_family` over the historical `display_name` derivation.

## On-disk picture (verified)

For `@a90` (root) and `@a90-code` (coder follow-up):

| Dir                                                       | Role                       | agent_meta.json highlights                                                                                                                                                                                                                                                                                                   |
| --------------------------------------------------------- | -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `~/.sase/projects/sase/artifacts/ace-run/20260524113941/` | plan-chain root (@a90)     | `name="a90"`, `cl_name="sase"`, `agent_family="a90"`, `agent_family_role="root"`, `role_suffix="-plan"`, `plan_chain_root=true`, `workflow_name="a90"`. **No `prompt_step_*.json` files** in this directory.                                                                                                                 |
| `~/.sase/projects/sase/artifacts/ace-run/20260524114223/` | code follow-up (@a90-code) | `name="a90-code"`, `cl_name="sase"`, `agent_family="a90"`, `agent_family_role="code"`, `role_suffix="-code"`, `parent_timestamp="20260524113941"`. Directory **also contains `prompt_step_main.json`** (workflow_name=`gh`, step_type=`agent`, parent_step_index=null, step_index=0, total_steps=1, artifacts_dir=this dir). |

So a single artifacts dir (`20260524114223`) carries **both** an agent identity (a follow-up coder) **and** a
prompt_step marker (the embedded `gh` workflow that the coder ran). Two different loaders pick it up:

- `load_done_agents_from_snapshot` / `load_running_home_agents_from_snapshot` read `agent_meta.json` → Agent A:
  `cl_name="sase"`, `agent_name="a90-code"`, `agent_family="a90"`, `role_suffix="-code"`,
  `parent_timestamp="20260524113941"`, `parent_workflow=None`.
- `load_workflow_agent_steps` reads `prompt_step_main.json` → Agent B: `cl_name="main"`,
  `parent_timestamp="20260524114223"`, `parent_workflow="gh"`, `step_type="agent"`, `step_index=0`, `total_steps=1`.

Agent A is correctly the follow-up coder; Agent B is correctly the embedded `gh` workflow's main step _inside_
@a90-code.

## Why both render under @a90

Both rows share `1/1-code` and `@a90-code`. Two distinct mechanisms produce this collision:

1. **Agent A** (the coder follow-up) is routed via `sort_and_reorder` into `followups_by_parent["20260524113941"]` (its
   `parent_timestamp` is the `@a90` root). It is then inserted directly under `@a90` as a child row. Its `step_index` /
   `total_steps` come from `prompt_step_by_parent[parent_ts]` — i.e. the parent's prompt_step markers.
   (`src/sase/ace/tui/models/_agent_ordering.py:80-99`)
2. **Agent B** (the `gh.main` workflow step under @a90-code) does **not** belong under @a90 in `sort_and_reorder` — its
   `parent_timestamp` is @a90-code, so it should render as a child of @a90-code. The duplicate only surfaces in the tree
   rendering (`build_agent_tree`) **after** grouping: `_grouping_name(Agent B)` follows the parent-lookup path on
   `is_workflow_child=True`, returning the family of its parent. With `_apply_workflow_child_identity_from_meta` having
   been a no-op for Agent B (because the parent meta isn't a plan-chain root — it's the coder dir, not the planner dir),
   Agent B was expected to fall back to `display_name`/`cl_name="main"`. Post-`ea47257e4`, however, `_grouping_name()`
   first consults `agent.agent_family`. We need to confirm during implementation whether Agent B is now inheriting
   `agent_family="a90"` from a metadata write-through (the enrichment helper currently gates this on
   `not workflow_child`, but the `_apply_workflow_child_identity_from_meta` branch may set it incorrectly under some
   condition, or a wire-snapshot path may apply it unconditionally — `enrich_agent_from_meta_wire` in
   `_meta_enrichment.py:416` does **not** have the `workflow_child` gate and always sets `agent_family` from
   `meta.agent_family`).

That wire-snapshot asymmetry is the leading suspect: in production the TUI's snapshot path runs the wire enricher, which
assigns `agent.agent_family = "a90"` to Agent B unconditionally, while the filesystem enricher would not. Combined with
the post-`ea47257e4` grouping change, Agent B then gets placed under the @a90 root banner as if it were a plan-chain
member, with cl_name="main" → display_name="main" but later transformed (probably via `_attach_runtime_children` or
another override pass) to show `agent_name="a90-code"` and the `-code` step label.

## Plan

### Phase 1 — Diagnose with a small repro

1. Write a temporary scratch script (delete after) that, given the on-disk artifacts in
   `~/.sase/projects/sase/artifacts/ace-run/20260524113941` and `…/20260524114223`, runs the full `load_all_agents()` /
   `apply_status_overrides()` / `sort_and_reorder()` / `build_agent_tree()` pipeline and prints every Agent's
   `(cl_name, agent_name, agent_family, role_suffix, parent_timestamp, parent_workflow, step_index, total_steps, agent_type)`.
2. Identify the two Agent objects whose final state matches the two duplicate rows. Note the _exact_ field that differs
   between them and the _exact_ function call that sets `agent_family="a90"` on the second one.
3. Re-run with commit `ea47257e4` reverted on a scratch worktree to confirm the duplicate disappears (or shifts). This
   pins the regression to either the grouping change alone or an interaction with an earlier enrichment defect.

### Phase 2 — Fix

Choose the **narrowest** fix that the diagnosis points at. Likely candidates, ordered by probability:

- **Fix A — Align wire enricher with filesystem enricher.** If `enrich_agent_from_meta_wire` is found to be
  unconditionally writing `agent_family` / `agent_name` / `role_suffix` on workflow children (lines 440-460 of
  `_meta_enrichment.py`), gate those writes on a new `workflow_child: bool = False` parameter that mirrors the
  filesystem helper. The wire variant exists _specifically_ to stay in lockstep with the filesystem variant; the gate
  omission is a drift bug that `ea47257e4` made visible.
- **Fix B — Refuse to group non-plan-chain workflow children by family.** In `_grouping_name()`
  (`src/sase/ace/tui/models/agent_groups/_keys.py:31-46`), do not consult `agent.agent_family` when the agent is a
  workflow child whose parent is **not** itself a plan-chain root. The grouping should only collapse rows that genuinely
  belong to the same plan chain, not any agent that happens to share an `agent_family` string. This is a
  defense-in-depth change even if Fix A resolves the immediate symptom.
- **Fix C — De-dup at render time.** In `_attach_runtime_children`
  (`src/sase/ace/tui/models/_agent_ordering.py:158-178`), reject a second child with the same `agent_name` +
  `role_suffix` + `parent_timestamp`. Use only if A and B together still leave a residual duplicate path.

The plan favors Fix A + Fix B together: Fix A removes the spurious metadata write that confuses grouping; Fix B prevents
the same class of bug from recurring whenever wire/filesystem drift again.

### Phase 3 — Regression coverage

- Add a test in `tests/ace/tui/models/test_agent_groups_grouping_mode_tree.py` that reproduces the exact two-Agent shape
  from the on-disk a90 case (one follow-up coder, one embedded-workflow `main` step under the coder) and asserts only
  one `-code` child appears under the plan-chain root. Use the in-memory `Agent(...)` constructors that the existing
  tests in that file already use, not fixture files.
- If Fix A is applied, add a unit test for `enrich_agent_from_meta_wire` that mirrors the existing filesystem-enrichment
  test for `workflow_child=True` (find the existing test in `tests/ace/tui/models/_loaders/` and parallel it).
- Add a small regression test in `tests/ace/tui/widgets/test_agent_list_grouping.py` that exercises the rendered child
  list under the plan-chain root for this scenario.

### Phase 4 — Validate

1. `just install` (workspace may be stale per the build_and_run.md note).
2. `just check`.
3. Manually inspect: launch the TUI against the live `~/.sase/projects/sase` data and confirm `@a90` (or whichever
   active plan-chain family is present) now shows a single `1/1-code` child row.

## Constraints & call-outs

- This is presentation/loading behavior on the Python TUI side and does not cross the Rust core boundary (see
  `memory/short/rust_core_backend_boundary.md`). Stay in this repo.
- Do **not** modify memory files or the SDD plan files in `sdd/`.
- Per `memory/short/build_and_run.md`, run `just install` before `just check` because this workspace may have stale
  dependencies.
- Per `memory/short/gotchas.md`, no runtime-specific branching — the fix must work for any agent runtime that produces
  the same artifact shape.
- Snapshot is at `~/tmp/sase_snapshot.txt`; the on-disk artifacts that reproduce it live at
  `~/.sase/projects/sase/artifacts/ace-run/20260524113941` and `~/.sase/projects/sase/artifacts/ace-run/20260524114223`.
  Both should still be present until the user cleans them up; capture their contents into a fixture file under
  `tests/ace/tui/models/_loaders/` if the test needs them long-term.

## Out of scope

- Any broader refactor of the wire vs. filesystem enricher split. If the two variants are diverging in ways unrelated to
  this bug, file a follow-up rather than expanding this PR.
- Changes to the `_ensure_synthetic_planner_children` synthetic-row machinery. The diagnostic in Phase 1 should confirm
  that the duplicate is not coming from a synthetic planner; if it is, revisit scope.
- Any change to how the embedded `gh` workflow renders as `1e/1 🐚 diff (DONE) ▼#gh` — that row is correct.
