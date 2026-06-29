---
create_time: 2026-06-29 08:27:19
status: done
prompt: sdd/prompts/202606/per_commit_diffs_and_deltas.md
---
# Plan: Per-commit diffs in the file panel + all-commit Deltas

## Problem

On the **Agents** tab of `sase ace`, the agent metadata panel shows a `COMMITS:` list and a `Deltas:` list, and the
bottom **file panel** loads commit diffs. Today, when an agent makes **more than one commit** on a repo (current or
linked), we only surface the **latest commit**:

- The `Deltas:` field shows only the files touched by the most recent commit.
- The file panel loads a single diff (the latest commit) into one slot.

Example (see `.sase/home/tmp/screenshots/20260629_081244.png`, agent `actstat-1.3`): the agent made two commits —

```
5f5acdf feat(github): add GitHub client, auth, and org expansion (actstat-1.3)
e67754c chore: close bead actstat-1.3 (Phase 3)
```

— but `Deltas:` only lists the three `sdd/beads/*` files from the _last_ commit (`e67754c`). The substantive `feat`
commit's files are invisible, and the file panel only shows that last commit's diff.

### Desired behavior

1. **File panel:** load **each commit's diff as its own page** (one slot per commit), so the user can cycle
   (`<ctrl+n>`/`<ctrl+p>`, `[`/`]`) through every commit's diff.
2. **`Deltas:` field:** show file entries for **all files modified by all commits**, grouped by repo (primary repo at
   top, linked repos below), the same way the `COMMITS:` list is already grouped.

## Root cause

The agent metadata's `COMMITS:` list already contains _all_ commits — it is built from `commit_results.json` into
`step_output["meta_commits"]` (a list of per-commit records). But two pieces are missing/lossy:

1. **Diff capture overwrites a single file.** During the commit workflow, `capture_pre_commit_diff` (in
   `src/sase/workflows/commit/commit_tracking.py`) writes the working-tree diff to a **fixed** path,
   `<artifacts_dir>/commit_diff.diff`, _before each commit_. Every commit clobbers the previous file, so on disk only
   the **last** commit's diff content survives. (For commits on a linked repo it clobbers the same file too, since the
   path is keyed only on the agent's artifacts dir.)

2. **Per-commit diff paths are never threaded to the UI.** Each commit's result marker does record a `diff_path`, and
   `write_result_marker` upserts one record per commit (keyed by `(cwd, sha)`) into `commit_results.json`. But
   `_commit_result_list_record` (in `src/sase/axe/run_agent_helpers_state.py`) only copies `message`/`sha`/`cwd` into
   each `meta_commits` record — it drops `diff_path`. And even if it kept it, every record would point at the same
   overwritten `commit_diff.diff`.

Downstream, the TUI then derives both the `Deltas:` field and the file panel from a **single** diff:

- `agent_delta_entries` (in `prompt_panel/_agent_deltas.py`) parses the **one** `get_agent_diff(agent)` result (which,
  for completed agents, reads the single `agent.diff_path` — the last commit's overwritten diff).
- `_desired_file_list` (in `file_panel/__init__.py`) adds a single `_LIVE_DIFF_SENTINEL` page for that one diff (plus
  linked-repo and extra-file pages).

So both the lossy capture and the lossy metadata must be fixed, then the TUI taught to fan out over all commits.

### Scope note: completed vs. active agents

`meta_commits` (the full commit list) is only assembled for **terminal** agents (DONE/FAILED) by the done-marker loader
(`models/_loaders/_done_loaders.py`). Active/running agents keep their existing behavior: a live working-tree diff
page + live linked-repo delta pages. This plan therefore gates the new per-commit behavior on the presence of
`meta_commits`, which naturally limits it to terminal agents (the screenshot's case) and leaves the live path for active
agents untouched. Extending the full commit list to running agents is a possible follow-up, explicitly out of scope
here.

### Rust core boundary

Per the repo's `rust_core_backend_boundary` rule, shared backend behavior belongs in `../sase-core`. The
commit/diff-capture and delta-derivation logic involved here lives entirely in Python today and has **no** counterpart
in the Rust core (confirmed: no commit/diff/delta logic exists under `../sase-core`). This change extends the existing
Python implementation rather than reimplementing core logic in Python, so it stays in this repo. No Rust wire/API change
is required.

## Design

Thread a per-commit `diff_path` from capture → metadata → UI, then fan the file panel and `Deltas:` field out over the
commit list. Work in layers:

### Layer 1 — Capture each commit's diff to its own file

`src/sase/workflows/commit/commit_tracking.py`

- In `capture_pre_commit_diff`, when running in agent context (`SASE_ARTIFACTS_DIR` set), write the diff to a **unique
  per-commit file** under a dedicated subdir, e.g. `<artifacts_dir>/commit_diffs/NNN.diff`, where `NNN` is a stable,
  zero-padded sequence derived from the count of existing diff files in that subdir (agents commit sequentially, so a
  simple count is race-free). Return that unique path.
- Keep refreshing the legacy `<artifacts_dir>/commit_diff.diff` as a copy of the most recent diff, for backward
  compatibility with any external reader (none found in-tree, but cheap insurance). The marker's `diff_path` should be
  the **unique** path so each `commit_results.json` record gets a distinct diff.
- The non-agent (human CLI) fallback already writes a unique timestamped file under `~/.sase/diffs/`; leave it as-is.
- `write_result_marker` already records `diff_path`/`commit_diff_path` per marker and upserts one record per
  `(cwd, sha)` into `commit_results.json`; with unique paths, each record now carries its own diff. Verify the upsert
  keeps the per-commit records distinct.

### Layer 2 — Propagate per-commit diff path into `meta_commits`

`src/sase/axe/run_agent_helpers_state.py`

- In `_commit_result_list_record`, also copy `diff_path` (preferring `diff_path`, falling back to `commit_diff_path`)
  into each record, expanding `~`. This makes every `meta_commits` record self-describing.

### Layer 3 — Shared accessor: ordered per-commit diff descriptors

`src/sase/ace/tui/widgets/prompt_panel/_agent_commits.py`

- Add a small frozen dataclass (e.g. `CommitDiffInfo`) carrying `repo_name`, `short_sha`, `subject`, `diff_path`, and an
  `is_primary` flag, plus a function `agent_commit_diffs(agent) -> list[CommitDiffInfo]` that:
  - parses `step_output["meta_commits"]`,
  - resolves each record's repo via the existing `_repo_name_for_commit_cwd` helper,
  - keeps only records with a non-empty `diff_path`,
  - orders them like the `COMMITS:` display (primary repo first, then linked repos; chronological within each), and
  - **dedups by resolved `diff_path`** so legacy markers (which share one overwritten path) gracefully collapse to a
    single slot instead of N identical ones.
- This is pure dict parsing (no file I/O), so it is cheap to call from render/UI code.
- Reuse the existing repo-attribution helpers so file-panel/Deltas grouping always matches the `COMMITS:` grouping.

### Layer 4 — File panel: one page per commit

`file_panel/_messages.py`, `file_panel/__init__.py`, `file_panel/_display.py`

- Add a commit-slot id scheme mirroring the existing linked-slot scheme: a `COMMIT_DIFF_PREFIX`, plus
  `commit_slot_id(index)`, `is_commit_slot(value)`, `commit_slot_index(value)`.
- In `_desired_file_list`: when `agent_commit_diffs(agent)` is non-empty, prepend one commit page per commit (in the
  ordered/grouped sequence above). Keep the `_LIVE_DIFF_SENTINEL` page **except** suppress it when commit pages exist
  _and_ the agent is terminal — for a terminal agent the live sentinel resolves to `agent.diff_path` (the last commit),
  which would duplicate a commit page. Linked-repo live pages and extra-file pages are unchanged.
- In `_display_file_at_current_index`: when the current page is a commit slot, resolve its `CommitDiffInfo` (via
  `agent_commit_diffs(self._current_agent)`) and render the diff with the existing `display_static_diff(diff_path)` path
  (off-thread read, diff lexer, line numbers — already implemented).
- In `current_source_label`: return a friendly label for commit slots (repo name + short sha, with the workspace glyph
  for linked-repo commits), so the panel border/title and the `● files [i/N] · <label>` indicator read clearly.
- In `_display.py`'s `_handle_static_read_result` path-match guard: treat commit slots like static files — resolve the
  slot's expected `diff_path` and compare it to the worker's `result.path` (instead of comparing the raw slot id), so
  commit-diff reads are not dropped as "stale".
- `get_current_file_path` for a commit slot returns the real `.diff` file path (it is a readable file, so open/zoom
  actions keep working).

### Layer 5 — `Deltas:` field: union across all commits, grouped by repo

`prompt_panel/_agent_deltas.py`, `prompt_panel/_agent_display_header_summary.py`

- Add a merge helper that unions parsed `DeltaEntry`s by path: combine line stats (sum) and pick a single change type
  per file (single type when all agree; otherwise fold to `M`). Document this as an intentional approximation — the
  exact net delta would be `git diff base..head`, which is unavailable once a terminal agent's workspace is released, so
  unioning the persisted per-commit diffs is the reliable source.
- Rework `agent_delta_entries(agent)`:
  - when `agent_commit_diffs(agent)` is non-empty, read + parse each **primary-repo** commit diff and merge → primary
    `Deltas:` entries;
  - otherwise fall back to today's behavior (parse the single `get_agent_diff(agent)`).
  - This runs inside `build_detail_header_summary`, which already executes in a background worker
    (`run_worker(..., thread=True)`) and already performs diff I/O, so the added file reads stay off the event loop.
- Add `agent_commit_linked_delta_groups(agent)` that builds `LinkedDeltaGroup`s from **linked-repo** commit diffs (group
  by repo, parse + merge each repo's commits).
- In `build_detail_header_summary`, source `linked_delta_groups` from the live cached groups when present (active
  agents) and otherwise from `agent_commit_linked_delta_groups` (terminal agents). They are mutually exclusive by
  status, so a simple "live or commit-derived" choice is unambiguous.
- Rendering needs no change: `build_delta_entries_section` already renders primary entries first and then per-repo
  linked groups with repo headers.

### Layer 6 — Tests, visual snapshot, docs

- Add/extend unit tests (see "Testing" below).
- Add or update a PNG visual snapshot for a multi-commit terminal agent showing the full `Deltas:` list and a multi-page
  file panel (`[1/N]`).
- Update the `?` help popup / `agents_bindings.py` and `src/sase/ace/AGENTS.md` if the file-panel cycling docs describe
  the diff page, to note commits are now separate pages. (Per `src/sase/ace/AGENTS.md`, any `sase ace` behavior change
  must keep the help popup in sync.)

## Considered and rejected

- **Append commit diff paths to `agent.extra_files`.** Less code (extra files already render as diffs and cycle), but:
  no friendly per-commit label (would show `000.diff`), muddies the "plans/PDFs/images" meaning of `extra_files`, and
  doesn't address the `Deltas:` aggregation at all. The dedicated commit-slot concept is clearer and matches the
  existing linked-slot pattern.
- **Recompute net deltas with `git diff base..head` in the TUI.** This is what the ChangeSpec `DELTAS` field does
  (`ace/deltas/compute.py`), but it needs a live workspace, which is gone for terminal agents. Unioning persisted
  per-commit diffs works without the workspace.

## Files to change (summary)

- `src/sase/workflows/commit/commit_tracking.py` — unique per-commit diff capture.
- `src/sase/axe/run_agent_helpers_state.py` — carry `diff_path` into `meta_commits` records.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_commits.py` — `CommitDiffInfo` + `agent_commit_diffs` accessor.
- `src/sase/ace/tui/widgets/file_panel/_messages.py` — commit-slot id helpers.
- `src/sase/ace/tui/widgets/file_panel/__init__.py` — commit pages in `_desired_file_list`, dispatch + labels.
- `src/sase/ace/tui/widgets/file_panel/_display.py` — commit-slot path-match guard.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_deltas.py` — multi-commit union + linked commit groups.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_header_summary.py` — choose live vs. commit-derived linked
  groups.
- Tests + a visual snapshot; help popup / `AGENTS.md` doc touch-ups if applicable.

## Edge cases & compatibility

- **Legacy terminal agents** (markers written before this change): their `commit_results.json` records share one
  overwritten diff path. Dedup-by-`diff_path` in `agent_commit_diffs` collapses them to a single page/entry set — i.e.
  exactly today's behavior, no regression.
- **Missing/unreadable diff file:** skip that commit's page and fall back to the live diff if no commit pages remain.
  `display_static_diff` already handles missing files gracefully.
- **Active agents:** no `meta_commits` ⇒ no commit pages ⇒ unchanged live behavior.
- **Single-commit agents:** one commit page; the suppressed live sentinel means the panel shows exactly one diff page,
  same as today.
- **Explicit-diff-step agents (#gh/#pr):** for terminal agents with commit pages, the single explicit/live diff page is
  suppressed in favor of the finer-grained per-commit pages, which is the requested behavior; the union still covers
  every touched file.
- Sanity-check that file-panel consumers that read the "current file" generically (zoom/`<ctrl+o>` open, keybinding-mode
  helpers) behave with commit slots.

## Testing

Static + targeted (the full suite/visual run can be killed by the sandbox; rely on targeted subsets plus `just lint`):

- **Capture:** two sequential commits produce two distinct files under `commit_diffs/` and two `commit_results.json`
  records with distinct `diff_path`s (`tests/workflows/test_commit_workflow.py`,
  `tests/test_commit_workflow_artifacts.py`).
- **Metadata:** `meta_commits` records include `diff_path` (`tests/test_done_agent_loader.py`).
- **Accessor:** `agent_commit_diffs` ordering, repo grouping, and dedup-by-path
  (new/`tests/ace/tui/widgets/test_agent_display_step_metadata.py`).
- **File panel:** a multi-commit terminal agent yields N commit pages, cycling renders each diff, labels correct, live
  sentinel suppressed (`tests/ace/tui/test_file_panel_selection_preserved.py`).
- **Deltas:** union across commits dedups paths and sums stats; linked-repo commits group under their repo
  (`tests/ace/tui/widgets/test_agent_deltas.py`, `tests/ace/tui/test_deltas_builder.py`).
- **Visual:** a multi-commit agent snapshot (`tests/ace/tui/visual/...`); refresh goldens with
  `--sase-update-visual-snapshots` only if the change is intentional.
- Finish with `just check` (after `just install`), aware the test phase may be SIGTERM-killed in the sandbox; the
  implementer should run the targeted subsets above directly when so.
