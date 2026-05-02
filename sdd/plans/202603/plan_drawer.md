---
create_time: 2026-03-28 13:01:29
status: done
prompt: sdd/prompts/202603/plan_drawer.md
---

# Plan: Add PLAN Drawer to COMMITS Entries

## Context

When a coder agent implements a plan created by a planner agent, the `SASE_PLAN` env var is set pointing to the plan
file. Currently, the plan path is only appended to the git commit message as `PLAN=<path>` (via `_handle_sase_plan()`).
The user wants us to also add a `| PLAN: <plan_file_path>` drawer line under each COMMITS entry in the ChangeSpec,
similar to how `| CHAT:` and `| DIFF:` drawers work.

This should work for all commit method types that create COMMITS entries (`create_commit` and `create_proposal`).
`create_pull_request` doesn't create COMMITS entries, so no drawer is relevant there.

## Changes

### Phase 1: Model & Parser (data layer)

**CommitEntry model** — `src/sase/ace/changespec/models.py`

- Add `plan: str | None = None` field to `CommitEntry` dataclass, alongside `chat` and `diff`.

**CommitEntryDict** — `src/sase/ace/changespec/section_parsers.py`

- Add `plan: str | None` to the `CommitEntryDict` TypedDict.
- Initialize `plan=None` in the dict creation (line ~355).

**Parser** — `src/sase/ace/changespec/section_parsers.py`

- Add `| PLAN:` case after `| DIFF:` in the COMMITS section parser (~line 364), extracting the path the same way.

**build_commit_entry** — `src/sase/ace/changespec/section_parsers.py`

- Add `plan` extraction from entry dict and pass to `CommitEntry()` constructor.

### Phase 2: Entry creation (write path)

**add_commit_entry_with_id** — `src/sase/workflows/commit_utils/entries.py`

- Add `plan_path: str | None = None` parameter.
- Emit `      | PLAN: {plan_path}\n` line after the DIFF drawer line when set.

**add_proposed_commit_entry** — `src/sase/workflows/commit_utils/entries.py`

- Same changes as above.

### Phase 3: Workflow integration (pass plan to entries)

**CommitWorkflow.\_append_commits_entry** — `src/sase/workflows/commit/workflow.py`

- Read `SASE_PLAN` env var.
- Compute a display path (replace `$HOME` with `~`).
- Pass `plan_path=` to both `add_commit_entry_with_id()` and `add_proposed_commit_entry()`.

### Phase 4: TUI display (read path)

**commits_builder.py** — `src/sase/ace/tui/widgets/commits_builder.py`

- Add rendering block for `entry.plan` after the DIFF block, using the same styling pattern.
- Show when `show_drawers` is True (same condition as DIFF).
- The plan path should be a clickable hint (same hint pattern as CHAT/DIFF).

### Phase 5: Tests

- Update existing COMMITS entry tests to verify `plan` field parsing.
- Add a test that `| PLAN:` lines are parsed into `CommitEntry.plan`.
- Add a test that `add_commit_entry_with_id` emits `| PLAN:` when given a plan_path.
