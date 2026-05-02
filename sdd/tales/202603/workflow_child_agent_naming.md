---
create_time: 2026-03-26 14:27:54
status: wip
prompt: sdd/prompts/202603/workflow_child_agent_naming.md
---

# Plan: Workflow-Scoped Agent Naming for Plan/Question/Feedback Follow-ups

## Problem to solve

When `ace-run` workflows spawn follow-up agents (plan approval, question responses, plan feedback replans), follow-up
artifacts currently inherit the exact same `name` from the original agent via `create_followup_artifacts()`. This causes
multiple agents under one workflow chain to present as the same agent name.

Desired behavior:

- The containing workflow keeps the original name.
- Each subsequent child agent under that same workflow gets `<name>.<N>`.
- `N` starts at `1` and increments by `1` for each subsequent child step.
- If a workflow only runs one agent, workflow and agent name remain identical.

## Current behavior (code-level)

- Root agent name is established in `extract_directives_and_write_meta()` (`src/sase/axe/run_agent_phases.py`).
- Follow-up artifacts are created by `create_followup_artifacts()` (`src/sase/axe/run_agent_helpers.py`), which copies
  `name` from base metadata unchanged.
- Follow-up spawning happens in `run_execution_loop()` (`src/sase/axe/run_agent_exec.py`) at all branches:
  - plan feedback replan
  - plan approve/epic follow-up
  - question follow-up
- Workflow entries in the Agents tab are loaded from `workflow_state.json` and enriched by `agent_meta.json`
  (`src/sase/ace/tui/models/_loaders/_workflow_loaders.py` + `_artifact_loaders.py`), so naming support for workflow
  entries already exists via `agent_name` enrichment.

## Design decisions

1. Treat the initial/root agent name as the workflow root name.
2. Assign child names only on follow-up artifact creation.
3. Keep role suffix behavior (`.plan`, `.code`, `.q`, numeric feedback suffixes) independent from child name indexing.
4. Use one monotonic child counter per workflow execution loop, incremented every time a new follow-up artifact is
   spawned.
5. Do not rename the root agent/workflow entry after launch.

## Implementation plan

### Phase 1: Introduce explicit follow-up name override plumbing

- Update `create_followup_artifacts()` signature to accept an optional explicit child agent name (e.g.,
  `name_override: str | None = None`).
- When provided, write that value to `agent_meta.json` `name` instead of copying base `name`.
- Preserve existing metadata inheritance (`model`, `llm_provider`, `vcs_provider`, `approve`, `parent_timestamp`, etc.).

Files:

- `src/sase/axe/run_agent_helpers.py`

### Phase 2: Add workflow-child naming allocator in execution loop

- In `run_execution_loop()`:
  - Capture root name once from `ctx.agent_meta.get("name")`.
  - Track `child_name_index = 0`.
  - Add helper logic:
    - Before each `create_followup_artifacts()` call, if root name exists:
      - increment index
      - compute child name `f"{root_name}.{child_name_index}"`
      - pass via `name_override`
    - If no root name exists, preserve current behavior (no name override).
- Apply this uniformly to all follow-up spawn sites:
  - plan feedback branch
  - plan approve/epic branch
  - question branch

Files:

- `src/sase/axe/run_agent_exec.py`

### Phase 3: Validate workflow-entry naming semantics in loaders

- Confirm workflow parent entry remains root-named (from root artifact `agent_meta.json`).
- Confirm follow-up child entries display new child names from their own `agent_meta.json`.
- If any loader path drops name for workflow entries, add minimal fix in enrich path (likely no change needed because
  `enrich_agent_from_meta()` already sets `agent.agent_name`).

Files to verify:

- `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`
- `src/sase/ace/tui/models/_loaders/_workflow_loaders.py`

### Phase 4: Tests

Add focused regression tests for naming behavior.

1. `create_followup_artifacts` unit behavior:

- Writes `name_override` when provided.
- Falls back to base `name` when override absent.

Suggested file:

- `tests/test_axe_run_agent_helpers.py` (or add new dedicated helper test module if absent)

2. `run_execution_loop` follow-up sequencing behavior:

- Simulate multiple follow-up spawns in one loop (e.g., feedback -> question -> approve).
- Assert `create_followup_artifacts` receives names in order: `<root>.1`, `<root>.2`, `<root>.3`.
- Assert root-only/single-agent path keeps original name unchanged.

Suggested file:

- `tests/test_axe_run_agent_runner_retry.py` or a new `tests/test_axe_run_agent_exec.py` (preferred to keep scope
  clear).

3. Loader-level integration behavior (if needed):

- Parent workflow entry retains root name.
- Child follow-up entries carry suffixed names.

Suggested file:

- `tests/test_agent_loader_dedup_vcs_pid.py` (if easiest to extend existing mocked loader pipeline), or new
  loader-focused test.

### Phase 5: Verification

- Run:
  - `just install` (workspace freshness requirement)
  - targeted tests for new/updated test files
  - `just lint`
- Optionally run broader `just test` if targeted tests pass quickly.

## Edge cases to explicitly handle

- Root agent has no name: do not invent dotted names; keep current behavior.
- Feedback loops currently use numeric role suffixes (`.2`, `.3`, ...); child naming counter must be independent to
  avoid coupling UI role logic with identity naming.
- Question follow-ups chained after plan/code phases must continue incrementing globally within same workflow chain.
- Existing historical artifacts (without dotted names) must still load correctly.

## Acceptance criteria

- For a named root agent `alice`, child follow-ups are named `alice.1`, `alice.2`, ... in creation order.
- Root workflow entry remains `@alice`.
- Single-agent workflows still show one name (`@alice`) with no suffix child names.
- No regressions in status overrides, dedup, or follow-up ordering in Agents tab.
