---
create_time: 2026-06-10 10:54:44
status: done
prompt: sdd/prompts/202606/pencil_icon_ignore_plan_prompt_edits.md
---
# Plan: Don't Count Plan/Prompt Files as Edits for the Agents-Tab Pencil Icon

## Problem

The agents tab shows a ✏️ badge (`_FILE_CHANGE_GLYPH`) on rows that "have made file changes". The hint is currently
`_has_file_change_hint(agent) = bool(agent.diff_path)` (`src/sase/ace/tui/widgets/_agent_list_render_agent.py:46`).

For agent families in the `TALE APPROVED` state, this badge appears even though no implementation edits exist yet. Root
cause (verified against a real artifact dir, `~/.sase/projects/sase/artifacts/ace-run/20260610100501`):

1. When a plan is approved with the "tale" action (also "epic"/"legend", which always commit), `handle_plan_marker`
   commits the SDD prompt + plan files (`sdd/prompts/<YYYYMM>/<name>.md` and
   `sdd/{tales,epics,legends}/<YYYYMM>/<name>.md`) via `sase commit`
   (`src/sase/axe/run_agent_exec_plan_sdd.py:commit_sdd_files_for_exec_plan`).
2. The commit workflow captures the pre-commit diff to `<artifacts>/commit_diff.diff` and persists `commit_diff_path`
   into the planner root's `agent_meta.json` (`src/sase/workflows/commit/commit_tracking.py:capture_pre_commit_diff` /
   `_persist_commit_diff_path`).
3. TUI meta enrichment promotes that to `agent.diff_path`
   (`src/sase/ace/tui/models/_loaders/_meta_enrichment.py:208-210, 480-481`).
4. While the coder child runs, the family root mirrors `TALE APPROVED` and renders the pencil — but its
   `commit_diff.diff` contains _only_ the SDD prompt + plan files. The badge is a false positive.

The same false positive can occur for any persisted diff artifact that touches only plan/prompt bookkeeping, e.g. a
prompt-step diff (`capture_vcs_diff()` in `src/sase/xprompt/workflow_executor_steps_prompt.py`) that picked up an
untracked `sase_plan_*.md` in a workspace where that pattern isn't gitignored.

## Goal

The pencil icon should mean "this agent produced reviewable file changes." Diffs whose only touched files are plan /
prompt bookkeeping artifacts must not light it up. Everything else about `diff_path` (file panel display, COMMITS
drawers, mentor matching, etc.) stays unchanged.

## Design

Classify each persisted diff artifact at **load time** (background threads), cache the result, and have the renderer
consume a precomputed boolean. No I/O on the Textual event loop (per `memory/long/tui_perf.md` rules 1 and 7).

### 1. Shared diff-path parsing utility

`src/sase/commit_instructions.py` already parses touched paths from diff text (`_normalize_diff_path`,
`_changed_files_from_diff`, lines 162-200). Extract this parsing into a small shared module (e.g.
`src/sase/diff_paths.py`) exposing `changed_files_from_diff(diff_text) -> list[str]`, and refactor
`commit_instructions.py` to call it. This avoids a second hand-rolled diff parser.

Note on the Rust core boundary: this is presentation-side badge logic layered over Python-only artifact loaders
(`agent_meta.json`, `done.json`, step markers), all of which live in this repo today. No `sase-core` change; if the
artifact model ever moves into the Rust core, the classifier moves with it.

### 2. Plan-artifact path predicate

A path counts as plan/prompt bookkeeping when (matching on path segments so `a/`-prefixes, absolute paths, and the
`.sase/sdd/` variant all work):

- it lies under `sdd/prompts/`, `sdd/tales/`, `sdd/epics/`, or `sdd/legends/`; or
- its basename matches the `/sase_plan` skill convention `sase_plan_*.md` (prefix already referenced in
  `src/sase/llm_provider/_plan_utils.py`).

Deliberately **not** excluded: `sdd/beads/**` (bead mutations are real, reviewable agent work) and everything else.

### 3. Cached classifier

New TUI-side module (e.g. `src/sase/ace/tui/models/_diff_badge.py`):

- `diff_has_real_edits(diff_path: str) -> bool`
- `os.stat` the file; module-level cache keyed by `(expanded path, mtime_ns, size)` with a `Lock` (mirror the cache
  discipline in `src/sase/ace/tui/widgets/file_panel/_diff.py`). Diff artifacts are effectively write-once, so the
  steady-state cost per refresh is one `stat` per unique diff path.
- Scan parsed paths and return `True` on the first non-excluded path (early exit keeps real code diffs cheap).
- Fail open: missing/unreadable file, parse oddities, or zero parsed paths ⇒ `True` (today's behavior — badge shows
  whenever `diff_path` is set — is preserved in all error cases).

### 4. Compute pass + Agent field

- Add `Agent.diff_has_real_edits: bool | None = None` (`src/sase/ace/tui/models/agent.py`).
- Populate it in a short pass at the end of `apply_status_overrides`
  (`src/sase/ace/tui/models/_agent_status_overrides.py`), i.e. _after_ the child→parent `diff_path` propagation at lines
  437-441 so the final `diff_path` values are classified. Both call sites
  (`actions/agents/_loading_compute_merge.py:137` and `models/agent_loader.py:446`) run off the event loop, so both the
  initial load and Tier-1 patch merges get the flag for free without a new refresh path (perf rule 4).

### 5. Renderer

- `_has_file_change_hint` returns `agent.diff_has_real_edits` when classified, falling back to `bool(agent.diff_path)`
  when `None` (defensive: an Agent constructed outside the override pass keeps current behavior).
- Update the memoized render-cache key at `src/sase/ace/tui/widgets/_agent_list_render_cache.py:133` from
  `bool(agent.diff_path)` to the same effective hint value so rows repaint when classification changes.

## What this fixes

- `TALE APPROVED` (and `EPIC`/`LEGEND APPROVED`) family roots whose only diff artifact is the SDD prompt+plan commit
  diff stop showing the pencil — including **historical** rows, since classification reads the existing artifacts.
- Once a coder child produces a real diff (propagated to the root), the pencil appears as before.
- Prompt-step diffs containing only `sase_plan_*.md` are likewise ignored.

## Alternatives considered

- **Capture-side suppression** (skip `_persist_commit_diff_path` for SDD commits, or tag the meta with
  `sdd_only: true`): smaller change, but misses already-written artifacts, misses the `sase_plan_*.md` step-diff source,
  and removes the plan diff from the file panel where it's currently harmless/useful.
- **Excluding all of `sdd/**`**: overreaches — bead files under `sdd/beads/` represent genuine agent work.

## Tests

- Unit tests for the shared diff-path parser extraction (existing `commit_instructions` tests keep passing).
- Unit tests for the classifier: SDD-only diff ⇒ no real edits; mixed SDD+code diff ⇒ real edits; `sase_plan_*.md`-only
  diff ⇒ no real edits; rename-only of a plan file ⇒ no real edits; missing/unreadable diff ⇒ fail-open `True`; cache
  invalidates when mtime/size change.
- Status-override pass test: family root in `TALE APPROVED` with an SDD-only `commit_diff.diff` ⇒ no badge; with a coder
  child's real diff propagated ⇒ badge.
- Rendering test in `tests/ace/tui/widgets/test_agent_display_list_rendering.py`: ✏️ rendered/not rendered per the new
  flag, and the render-cache key reflects it.
- Run `just check` and `just test-visual`; update PNG goldens only if any snapshot legitimately loses a pencil.

## Files expected to change

- `src/sase/diff_paths.py` (new) + `src/sase/commit_instructions.py` (refactor to use it)
- `src/sase/ace/tui/models/_diff_badge.py` (new)
- `src/sase/ace/tui/models/agent.py` (new field)
- `src/sase/ace/tui/models/_agent_status_overrides.py` (classification pass)
- `src/sase/ace/tui/widgets/_agent_list_render_agent.py` (`_has_file_change_hint`)
- `src/sase/ace/tui/widgets/_agent_list_render_cache.py` (cache key)
- `src/sase/ace/tui/widgets/_agent_list_styling.py` (comment on `_FILE_CHANGE_GLYPH` semantics)
- Tests as above
