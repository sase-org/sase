---
create_time: 2026-07-03 06:52:44
status: wip
prompt: sdd/prompts/202607/vcs_prefill_display_names.md
---
# Show the Configured `PROJECT_NAME` (Never the Directory Key) in VCS xprompt Prefill Surfaces

## Problem

Pressing `<ctrl+space>` (the `start_agent_from_changespec` keymap, which reopens the prompt input bar with the last VCS
xprompt workflow prepended) currently prefills `#gh:gh_sase-org__sase` — the canonical on-disk project directory key —
instead of `#gh:sase`, the configured `PROJECT_NAME`. Per the established invariant (see
`sdd/tales/202606/project_display_name_agent_rows.md`, which fixed the same class of leak on the Agents tab): the user
should only EVER see the configured project name; the directory key is storage identity, not a display string.

## Root Cause

The canonical directory key leaks into user-facing prefill text through two persisted replay stores, both fed by the
launch pipeline's ref resolution:

1. **Resolution canonicalizes before extracting the ref.** `resolve_ref_from_prompt()`
   (`src/sase/ace/tui/actions/agent_workflow/_ref_resolution.py:59`) calls `canonicalize_project_aliases_in_prompt()` on
   the prompt _before_ matching the ref pattern, so even when the user types `#gh:sase`, the returned `ref` (and
   `resolved.project_name`) is the canonical key `gh_sase-org__sase`.

2. **The canonical ref is persisted into both replay stores** by `run_single_agent_launch_body()`
   (`src/sase/ace/tui/actions/agent_workflow/_launch_body_single.py:139-144`):
   - `save_replayable_vcs_selection()` (`_launch_history.py:111`) writes `~/.sase/last_agent_selection.json` with
     `project_name = ctx.project_name` (canonical). This is _correct as identity_ — the field is used for
     `sase_projects_dir() / project_name` path building and launchability checks.
   - `record_resolved_vcs_xprompt_usage()` → `record_vcs_xprompt_usage()` (`src/sase/history/vcs_xprompt_mru.py:76`)
     writes the literal prefix string `#gh:gh_sase-org__sase` into `~/.sase/vcs_xprompt_mru.json`.

3. **Replay renders the identity key verbatim.** On `<ctrl+space>`, `action_start_agent_from_changespec` →
   `_start_custom_agent_from_selection()` (`src/sase/ace/tui/actions/agent_workflow/_entry_custom.py:166`) builds the
   prefill via `_vcs_prompt_prefix(project_file, selection.project_name)`
   (`src/sase/ace/tui/actions/agent_workflow/_entry_points.py:26`) — embedding the directory key directly into the
   user-visible prompt text (and into the prompt bar's `display_name` label).

Verified live: `~/.sase/last_agent_selection.json` contains `"project_name": "gh_sase-org__sase"` /
`"display_name": "[P] gh_sase-org__sase"`, and `~/.sase/vcs_xprompt_mru.json` contains `#gh:gh_sase-org__sase`. The
project spec (`~/.sase/projects/gh_sase-org__sase/gh_sase-org__sase.sase`) has `PROJECT_NAME: sase`.

### Sibling surfaces with the same leak (same data, same root cause)

- `,.` prompt-history entry (`_entry_prompt_history.py:53-57`) — same `_vcs_prompt_prefix(project_file, project_name)`
  build; the canonical key is substituted into history prompts via `replace_vcs_workflow_tags` and used as the bar's
  `display_name`.
- `<ctrl+g>` `start_last_vcs_xprompt_in_editor` (`_entry_custom.py:48-68`) — inserts `load_launchable_vcs_xprompt_mru()`
  entries verbatim.
- `<ctrl+p>`/`<ctrl+n>` VCS MRU cycling (`src/sase/ace/tui/widgets/_vcs_mru_cycling.py:278-283`) — inserts MRU entries
  verbatim into the prompt text.
- Launch feedback toasts in `_launch_body_single.py` (`"Agent started for {display_name}"`,
  `"Prompt fan-out launch queued for {ctx.display_name}"`, `"Repeat launch queued for ..."`) — `ctx.display_name` is set
  to the canonicalized ref at `_launch_body_single.py:105`.
- Stale-selection notifications in `_entry_points.py:97-117` render `project_name` (canonical) in toast text.

### A related latent MRU bug (alias-unaware pruning)

`_vcs_prefix_ref_is_gone()` (`vcs_xprompt_mru.py:201`) judges resolvability via `resolve_known_project_ref()` against
`get_known_project_workspaces()`, which is keyed by _directory key only_. A display-name-form entry such as `#gh:sase`
(recorded today by the non-home-mode path `record_launched_vcs_xprompt_usage()`, which records the raw user-typed ref)
is wrongly judged "gone" and silently pruned from the MRU. Any fix that surfaces display-form prefixes must make this
pruning alias-aware or such entries will vanish.

## Design

Follow the precedent set by the `project_display_name_agent_rows` work: **the directory key stays the storage identity
everywhere; humanize only at display boundaries.** On-disk formats (`last_agent_selection.json`, `vcs_xprompt_mru.json`,
ProjectSpec paths) do not change, so existing state files display correctly immediately with no migration. This is a
sase-repo-only, display-layer change — no Rust core (`sase-core`) or `sase-github` changes; the display-name map is
already provided by the core wire (`project_display_name_map` / `sase.core.project_lifecycle_wire`) and cached in
Python.

### Step 1 — Public humanize helper for VCS prefixes

In `src/sase/project_display_names.py`, add a small public helper (e.g.
`humanize_vcs_refs_in_text(text, projects_root=None)`) that applies the existing `humanize_project_refs_in_prompt()`
(`src/sase/project_aliases.py:532`) using the existing mtime-keyed `_project_display_name_map_cached()`. Rationale:

- `humanize_project_refs_in_prompt` already implements the exact ref-tag rewrite (fenced-block safe, all VCS workflow
  tags) and is proven in the agent prompt panel (`_agent_display_render.py:67`).
- Reusing the mtime-keyed cache satisfies the TUI perf rule "no per-keystroke disk reads": the `<ctrl+p>` path adds one
  `stat()` + dict lookup per keypress, nothing more.

### Step 2 — Humanize the replay prefill (the reported bug)

In `_start_custom_agent_from_selection()` (`_entry_custom.py`), for the **project** branch, pass
`project_display_name_for(project_name)` as the name embedded in the prefix and as the prompt bar's `display_name`
label. All identity uses (`project_dir`, `preferred_project_spec_path`, `_is_launchable_project`,
`_clear_stale_last_custom_agent_selection`) keep the canonical `selection.project_name`. The **cl** branch is untouched
(ChangeSpec names are already user-facing). Apply the same substitution in `_start_prompt_history_from_last_selection()`
(`_entry_prompt_history.py`) where `name` is a project name.

Round-trip safety: submitting the humanized prefill (`#gh:sase ...`) is exactly today's alias-launch flow —
`resolve_ref_from_prompt` canonicalizes on submit, so resolution, workspace allocation, and replay recording behave
identically. `history_sort_key` keeps its current (canonical) value: the launch pipeline overwrites it with the resolved
ref at submit time anyway, and history grouping keys should stay stable identities.

### Step 3 — Humanize MRU entries at load (fixes `<ctrl+g>` and `<ctrl+p>`/`<ctrl+n>`)

In `load_launchable_vcs_xprompt_mru()` (`src/sase/history/vcs_xprompt_mru.py`), after pruning and the prune write-back
(so the _disk stays canonical_), map each returned entry through the Step-1 helper (threading the existing
`projects_dir` parameter through as the projects root), then dedupe the humanized results preserving MRU order. Both
consumers — `action_start_last_vcs_xprompt_in_editor` and `_handle_vcs_mru_cycle_key` — get correct display strings with
no changes of their own, and cycling stays self-consistent: `_next_vcs_mru_index()` matches the current (now humanized)
tag against the (now humanized) entries by normalized string equality.

### Step 4 — Canonicalize at record + alias-aware pruning (MRU coherence)

- `record_vcs_xprompt_usage()`: canonicalize the incoming prefix via `canonicalize_project_aliases_in_prompt()` before
  the default-prefix check and dedup/insert, so the non-home-mode record path (which records raw user-typed refs like
  `#gh:sase`) stores the canonical form and on-disk dedup collapses spelling variants. (`home` is excluded from the
  alias map, so the `#git:home` default-prefix handling is unaffected.)
- `_vcs_prefix_ref_is_gone()` and `_is_stale_known_project_prefix()`: resolve the parsed ref through
  `resolve_project_alias_ref()` before consulting `known_projects` / ChangeSpec names / spec paths, so alias- or
  display-form entries (legacy on-disk data, hand-edited files) are judged by their canonical project rather than
  wrongly pruned (or wrongly kept).

Write path and read path together give a clean symmetric invariant: **canonical on disk, configured name on screen.**

### Step 5 — Humanize launch feedback strings

In `_launch_body_single.py`, humanize the _notification text only_ (the `"Agent started for ..."`, fan-out, and repeat
toasts) via the Step-1 helper / `project_display_name_for`. Do **not** change `ctx.display_name` itself — it feeds
`LaunchExecutionContext.cl_name` (run identity/naming), which is by-design canonical storage identity; agent rows
already humanize via `Agent.project_display_name`. Similarly humanize the project name rendered in the stale-selection
notifications in `_entry_points.py`.

## Explicitly Out of Scope

- No `sase-core` (Rust) or plugin changes; no wire/API changes.
- No change to on-disk formats or storage identities (`last_agent_selection.json` schema, MRU file, ProjectSpec paths,
  `SelectionItem.project_name`, `ctx.project_name`, `ctx.history_sort_key`, run naming via `cl_name`).
- No migration of existing state files (read-time humanization covers existing canonical data).
- Owner/repo-form MRU entries (e.g. `#gh:sase-org/sase`) remain as typed: the humanize rewrite only replaces refs equal
  to a directory key, and collapsing owner/repo spellings would require workspace-path resolution at display time.
  Canonicalize-at-record (Step 4) does not affect them either (owner/repo refs are not alias-map keys). Accepted: they
  are the user's own spelling, and new home-mode launches already record the resolved canonical form.

## Tests

Fixture pattern: a project dir like `gh_acme__widgets` whose spec contains `PROJECT_NAME: widgets` (follow
`tests/test_project_alias_services.py`); reset the display-name cache between tests (module-level mtime cache).

1. `tests/test_vcs_xprompt_mru.py`:
   - `load_launchable_vcs_xprompt_mru()` returns `#gh:widgets` for an on-disk `#gh:gh_acme__widgets` entry, while the
     file on disk keeps the canonical form after the prune write-back.
   - Humanized duplicates are deduped in load order.
   - A display-form entry `#gh:widgets` on disk is _not_ pruned as gone (alias-aware pruning) and loads humanized.
   - `record_vcs_xprompt_usage("#gh:widgets")` stores the canonical `#gh:gh_acme__widgets` and dedups against an
     existing canonical entry.
2. `tests/ace/tui/test_entry_points_vcs_prefix_selection.py` (+ helpers in `_entry_points_vcs_prefix_helpers.py`):
   `<ctrl+space>` replay of a saved project selection with a `PROJECT_NAME` prefills `#gh:widgets ` (not the directory
   key) and passes the humanized `display_name` to the prompt bar; a project _without_ `PROJECT_NAME` is unchanged; the
   cl branch is unchanged.
3. `tests/ace/tui/widgets/test_prompt_vcs_mru_cycling.py` / `test_vcs_mru_cycling_logic.py`: cycling inserts humanized
   entries, and a prompt prefilled with the humanized tag resumes the ring at the matching index.
4. Prompt-history entry (`,.`): the VCS prefix substituted into a history prompt uses the configured name.
5. `tests/ace/tui/agent_launch_vcs/test_feedback.py`: launch toast reads `Agent started for widgets` when launching
   `#gh:widgets`, while run identity (`cl_name`) still receives the canonical key.

## Validation

Run `just install`, then `just check` (lint + mypy + full test suite including PNG visual snapshots). Manual smoke: with
the existing real state files (canonical entries), `<ctrl+space>` must prefill `#gh:sase`, `<ctrl+p>` must cycle
humanized entries, and launching the prefilled prompt must resolve/launch exactly as before.

## Risk Summary

- Display-only rewrites reading an mtime-cached map; storage identity, resolution, and run naming untouched. Worst-case
  failure mode is cosmetic (a canonical key showing where a display name is unset), matching the prior
  `project_display_name_agent_rows` change.
- The only behavioral (non-cosmetic) edits are the MRU record canonicalization and alias-aware pruning, both of which
  strictly widen what survives/dedups correctly and are covered by dedicated tests.
