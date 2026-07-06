---
create_time: 2026-07-06 14:44:02
status: done
prompt: sdd/prompts/202607/eradicate_raw_project_keys.md
---
# Plan: Eradicate Raw Project Directory Keys From Every User-Facing Surface

## Problem

The rule: the user must NEVER see a raw project directory key (e.g. `gh_sase-org__sase`) anywhere in SASE's user-facing
output. Anywhere the raw key would have appeared, the configured `PROJECT_NAME` (e.g. `sase`) must appear instead.
Storage, identity, launch canonicalization, JSON/machine output, and on-disk files stay canonical.

Commit `228fc78af` (and `285600348` before it) humanized the prompt-display and prefill surfaces they targeted, but a
full sweep of the repo found many remaining violations. Evidence from screenshot `20260706_141758`: the agent detail
panel's COMMITS section shows `gh_sase-org__sase` as the repo group label. The user also reports the fork (`f`) keymap
pre-filling the prompt input with `#gh:gh_sase-org__sase ...`.

This plan fixes every confirmed violation and adds shared helpers + a test convention so new surfaces stay clean.

## Confirmed violations

### A. TUI display leaks

| #   | Surface                                         | Leak site                                                                                  | Source                                                                                                                                           |
| --- | ----------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| A1  | COMMITS section repo label (agent detail panel) | `src/sase/ace/tui/widgets/prompt_panel/_agent_commits.py:67-75` (`_primary_repo_name`)     | raw `meta_project` / `Path(agent.project_file).stem`; rendered at `:286`                                                                         |
| A2  | File panel per-commit diff page labels          | `src/sase/ace/tui/widgets/file_panel/_file_list.py:356` renders `CommitDiffInfo.repo_name` | same `_primary_repo_name` (A1)                                                                                                                   |
| A3  | Visible-agent completion popup badge + snippet  | `src/sase/ace/tui/widgets/_prompt_input_bar_completion.py:333-334`                         | `AgentVcsWorkflow.tag/.display/.project` and `_prompt_snippet()` built from raw stored prompts in `src/sase/ace/tui/agent_completion.py:266-333` |
| A4  | Jump-to-Entry modal (`'`) agent rows            | `src/sase/ace/tui/modals/jump_all_modal.py:130`                                            | `ag.cl_name` instead of `ag.display_name`                                                                                                        |
| A5  | tmux workspace chooser "current" row            | `src/sase/ace/tui/modals/agent_workspace_tmux_modal.py:122`                                | `agent.cl_name or agent.display_name` — cl_name always wins                                                                                      |
| A6  | Runners modal rows                              | `src/sase/ace/tui/modals/runners_modal.py:393,512`                                         | `RunnerInfo`/task `cl_name` from orphan workspace claims (`_runners_data.py:298`)                                                                |
| A7  | Kill-and-restart confirm modal description      | `src/sase/ace/tui/actions/agents/_wait_resume.py:393`                                      | `CL: {agent.cl_name}` raw (audit other `ConfirmKillModal` descriptions too)                                                                      |

### B. TUI prefill / clipboard leaks (text handed to the user for editing or pasting)

| #   | Surface                                                                  | Leak site                                                                                                                                                                                       | Source                                                                                                                                                            |
| --- | ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1  | Fork (`f`) and wait (`%w`, incl. bulk) prompt-bar prefill                | `src/sase/ace/tui/actions/agents/_wait_resume.py:119-160` (`_resolve_vcs_tag`), consumed at `:440,466,487,524,562`                                                                              | raw VCS tag extracted from stored canonical xprompt                                                                                                               |
| B2  | Quick-launch from selected agent (leader-Space) prefill + bar label      | `src/sase/ace/tui/actions/agent_workflow/_entry_quick_launch.py:76-100`                                                                                                                         | raw `agent.cl_name` fed to the `#<provider>:<ref>` prefix builder and `display_name` (sibling `_entry_custom.py:169-172` already uses `project_display_name_for`) |
| B3  | Retry / kill-and-edit / edit-and-relaunch prompt-bar prefill + bar label | `src/sase/ace/tui/actions/agent_workflow/_entry_relaunch.py` (raw prompt read at `:47,86`; `PromptInputBar(initial_value=...)`/`initial_panes` at `:237-240`; `display_name=cl_name` at `:229`) | raw canonical xprompt content                                                                                                                                     |
| B4  | Copy agent prompt (`%p` on Agents tab)                                   | `src/sase/ace/tui/actions/clipboard/_agents.py:77-82`                                                                                                                                           | copies raw xprompt; inconsistent with the (humanized) prompt-history Ctrl+Y copy                                                                                  |

### C. CLI display leaks

| #   | Surface                                                                          | Leak site                                                                                                                                                       | Source                                                                                      |
| --- | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| C1  | `sase agents list` PROJECT + PROMPT columns                                      | `src/sase/agents/cli_list.py:121,127`                                                                                                                           | `record.project_name` raw key; prompt text un-humanized (JSON path correctly canonical)     |
| C2  | `sase agent show` Project + Prompt output                                        | `src/sase/agents/cli_show.py:44-50,72-79`                                                                                                                       | `parse_agent_artifact_path` project key; raw `raw_xprompt.md` contents                      |
| C3  | `sase changespec current` (plain + markdown + diagnostics)                       | `src/sase/main/changespec_handler.py:221,231,247`                                                                                                               | `cs.project_basename` / `context.project` raw                                               |
| C4  | `sase workspace list` human table header                                         | `src/sase/main/workspace_handler_list.py:83-88`                                                                                                                 | `key={project_key}` and `Project: {ctx.project_name}` raw (JSON branch correctly canonical) |
| C5  | `sase prompt search` compact + full renderers                                    | `src/sase/prompt/cli_search.py:240-311,418-443`                                                                                                                 | raw `hit.text`; contrast `prompt list` which humanizes                                      |
| C6  | Prompt-history fzf pickers (`sase prompt run/edit/select`, query-editor history) | `src/sase/prompt/cli_run.py:135-139`; `src/sase/history/prompt_store.py:676-690` (`format_prompt_for_display`) via `src/sase/main/query_handler/_editor.py:144` | raw `entry.text` in picker rows                                                             |
| C7  | `sase prompt stats` "Largest Prompts" previews                                   | `src/sase/prompt/cli_stats.py:85-86` via `src/sase/history/prompt_stats.py:123`                                                                                 | raw prompt text                                                                             |
| C8  | `sase prompt show` (pretty/markdown) and `sase prompt copy`                      | `src/sase/prompt/cli_show.py:31,44-62`, `cli_copy.py:27`                                                                                                        | raw `record.text` (see Decisions for the raw/JSON/export carve-out)                         |
| C9  | Mobile gateway changespec tag catalog                                            | `src/sase/integrations/_mobile_helper_catalog.py:49-60` (`project` field from `changespec_tags.py:80-85`)                                                       | `cs.project_basename` raw in a field the mobile client renders to humans                    |

### D. ChangeSpec names that embed the directory key (systemic)

`ensure_project_prefix(project, cl_name)` is called with the canonical project key when a PR is created with an explicit
name (`src/sase/workflows/commit/workflow.py:136` via `compute_suffixed_cl_name`, and
`src/sase/workspace_provider/changespec.py:171`; also the `_derive_cl_name` fallbacks `{project_name}_agent_changes`).
This mints stored ChangeSpec NAMEs — and matching git branch names — like `gh_sase-org__sase_fix_just_tests_1` (one such
name exists in the current archive). Every surface that shows a ChangeSpec name or an agent `cl_name` then displays the
raw key: ChangeSpecs-tab rows/detail, `Agent.display_name` fallback (`src/sase/ace/tui/models/agent.py:406`),
notifications, `sase ace` CLI panel, etc.

## Design

Philosophy unchanged: **storage/identity stays canonical; humanize at display and prefill boundaries.** Launch
re-canonicalizes aliases (`canonicalize_project_aliases_in_prompt`), so humanized prefill/copy text is safe to resubmit.
The display-name map already comes from the Rust core (`project_display_name_map`); everything here is presentation-only
Python glue — no `sase-core` changes.

### Part 1 — Shared helpers (extend `src/sase/project_display_names.py`)

All built on the existing mtime-keyed cached map (`_project_display_name_map_cached`; one `stat()` + dict lookup):

1. `humanize_cl_name(name)` — new. Exact directory-key match → display name; leading `<key>_` prefix → `<display>_`
   (longest-key match). For ChangeSpec names, agent `cl_name` fallbacks, runner/claim labels, notification cl_name
   fields. Safe no-op for names without a known key.
2. `humanize_vcs_refs_in_text(text)` — existing; use at every remaining text boundary (prefills, snippets, CLI prompt
   previews/pickers).
3. `project_display_name_for(key)` — existing; use for bare project label fields (columns, headers, repo labels).

### Part 2 — TUI fixes

- **A1/A2**: in `_agent_commits.py`, resolve the primary repo label via `agent.project_display_name` falling back to
  `project_display_name_for(raw)` (mirroring `project_display_label` used by the header/workflow renderers). Humanize at
  the source (`_primary_repo_name` / `_repo_name_for_commit_cwd`) so COMMITS grouping, `CommitDiffInfo` ordering
  (`is_primary` comparisons), and file-panel labels stay mutually consistent. Linked-repo names (`sase-core` etc.) are
  not directory keys and pass through unchanged.
- **A3**: humanize in `_vcs_workflow_from_prompt` (tag + project fields) and `_prompt_snippet` so every consumer of
  `AgentCompletionCandidate` renders clean; keep `search_text` matching both displayed and canonical forms so filtering
  never narrows.
- **A4/A5/A7**: switch to `agent.display_name` (already humanized for project agents), with `humanize_cl_name` as the
  fallback for non-project rows; audit the other `ConfirmKillModal`/notify description builders in the same files while
  there.
- **A6**: runners/claims carry no Agent object — pass their `cl_name` labels through `humanize_cl_name` at render.
- **B1**: humanize the returned tag inside `_resolve_vcs_tag` (single choke point for fork, single wait, bulk wait).
- **B2**: use `project_display_name_for` for the quick-launch ref and bar `display_name`, matching `_entry_custom.py`.
- **B3**: pass the relaunch prompt(s) through `humanize_vcs_refs_in_text` before mounting `PromptInputBar`
  (`initial_value` and each of `initial_panes`); use `agent.display_name` for the bar label. Stored xprompt files remain
  untouched; submit re-canonicalizes.
- **B4**: humanize the copied prompt in `_copy_agent_prompt`, consistent with the prompt-history Ctrl+Y copy.

### Part 3 — CLI fixes

- **C1/C2/C3/C4**: map project label fields through `project_display_name_for` / `humanize_cl_name`; pass prompt text
  through `humanize_vcs_refs_in_text`. Human-readable table/plain/markdown output only — every `--json` branch and
  stored file stays canonical. For C4, replace the `key=<project_key>` fragment with the humanized name (the raw key
  remains available via `--json` and `sase project show`).
- **C5/C6/C7**: humanize snippet/preview/picker-row text at render. For fzf pickers, confirm selection is resolved by
  index/id — never by parsing the displayed (now humanized) text back into a lookup key.
- **C8**: humanize `sase prompt show` pretty/markdown output and `sase prompt copy` clipboard text (paste surfaces;
  launch re-canonicalizes). `show -f raw`, `--json`, and `export` file contents stay byte-exact canonical as documented
  escape hatches (see Decisions).
- **C9**: humanize the mobile catalog's `project` field value (it exists solely for client-side human display); no
  schema/shape change, canonical `tag`/identity fields untouched.

### Part 4 — ChangeSpec names (D)

Two complementary moves:

1. **Stop minting raw-key names**: at the `ensure_project_prefix` call sites (and `_derive_cl_name` fallbacks), prefix
   with `project_display_name_for(project)` instead of the canonical key. Project-file routing, locking, and suffix
   reservation keep using the canonical key — only the human-facing name string changes. New explicit-name PRs then
   produce `sase_<name>_<N>` ChangeSpec/branch names. This is a deliberate behavior change to name-generation (flagged
   for review); uniqueness is preserved by the existing per-project reservation flow.
2. **Humanize legacy names at display**: apply `humanize_cl_name` where ChangeSpec names / agent `cl_name`s render: the
   `Agent.display_name` cl_name fallback (`models/agent.py:406`), ChangeSpecs-tab row + detail (NAME/PARENT) builders,
   `sase ace` CLI panel (`src/sase/ace/display.py`), `sase changespec current` NAME line, jump-modal changespec rows,
   and notification cl_name display (AXE tab + `sase notify` CLI). Implementation should sweep remaining
   `cl_name`-display consumers with the shared helper; identity, dedup, filtering keys, branch lookups, and stored NAME
   fields stay canonical. Any name-lookup CLI path that accepts a typed name should try the typed form first, then
   re-canonicalize a display-name prefix through the alias map so users can type what they see.

### Performance notes (per `memory/tui_perf.md`)

- Every helper reads the mtime-cached map: one `stat()` + dict lookup per call, no disk reads on paint or keystroke
  paths. `humanize_cl_name` is an O(#keys) prefix check against a tiny map; acceptable on per-row paths, but memoize
  per-item where rows already cache summaries (completion candidates are built once per popup; agent list rows go
  through `display_name` which is a property — keep the helper allocation-free and short-circuit when the map is empty
  or the name contains no `_`-joined key prefix).
- Prefill/copy/CLI paths are one-shot; snippet/preview humanization operates on already-truncated text.
- No new refresh paths, no event-loop I/O; nothing here touches the agent-list rebuild fast path.

## Decisions called out for review

1. **Byte-exact escape hatches stay canonical**: `--json` everywhere, `sase prompt show -f raw`, `sase prompt export`
   file contents, stored files, and git/branch data. These are machine/storage boundaries, not display.
2. **`sase project list/show` keeps showing the directory key** (labeled, e.g. `sase (gh_sase-org__sase)`): it is the
   identity-administration surface — the one place the mapping itself must be inspectable. Will remove on request.
3. **Agent chat/response prose**: displayed chat text already humanizes `#<workflow>:<ref>` tags. Bare directory keys
   inside prose or file paths (e.g. `~/.sase/projects/gh_sase-org__sase/...` quoted in an agent reply) are NOT rewritten
   — rewriting paths would display locations that don't exist and break copy/paste of paths. If the absolute rule should
   extend even here, say so and a fence-protected bare-key pass can be added to the chat renderer.
4. **ChangeSpec name generation change** (Part 4.1) alters future branch/PR names — approve explicitly.
5. **Existing stored names are not migrated** (the archived `gh_sase-org__sase_fix_just_tests_1` keeps its stored
   NAME/branch); it is humanized at display by Part 4.2.

## Tests

- Shared: `tests/test_project_display_names.py` — `humanize_cl_name` (exact key, `<key>_` prefix, longest-match,
  unknown-name no-op, empty-map fast path). Add a tiny shared assertion helper (e.g.
  `assert_no_raw_project_keys(text, keys)`) in a test util and use it across the new surface tests so future regressions
  read as rule violations.
- TUI: extend the existing per-surface test files — `_agent_commits` label + `CommitDiffInfo.repo_name`
  (tests/ace/tui/widgets), completion candidate badge/snippet + `search_text` dual matching, jump/tmux/runners modal
  rows, kill-confirm description, fork/wait/quick-launch/relaunch prefill text (assert humanized tag AND that the stored
  xprompt file is unchanged), clipboard copy.
- CLI: `sase agents list`/`agent show`/`changespec current`/`workspace list`/`prompt search`/`prompt stats`/fzf picker
  line builders/`prompt show`+`copy` — pretty output humanized, `--json` byte-identical to before.
- ChangeSpec naming: `compute_suffixed_cl_name` writes reservation into the canonical project file while returning a
  display-name-prefixed NAME; a revive/lookup round-trip on a legacy raw-prefixed NAME still resolves (identity safety
  guard).
- Run `just install`, then the required `just check` (fmt, lint, mypy, full tests incl. PNG visual snapshots —
  regenerate goldens intentionally with `--sase-update-visual-snapshots` only where a raw key legitimately became a
  display name).

## Risks / edge cases

- **Filter/lookup regressions**: wherever displayed text changes, filtering must match displayed AND canonical forms
  (completion `search_text`, modal filters); typed-name lookups accept both forms.
- **Grouping consistency**: COMMITS/file-panel humanize at the shared source so group keys, `is_primary`, and labels can
  never disagree; two projects sharing a display name would merge display groups only (identity keys unaffected).
- **Ambiguous/missing display names**: all helpers no-op when the key has no distinct display name — zero behavior
  change for unconfigured projects.
- **Prefill round-trips**: humanized prefill/copy text relies on launch canonicalization; tests assert a fork-prefill
  submit produces a canonical stored prompt.
- **Runners/claims**: claim labels may be arbitrary; `humanize_cl_name` only rewrites exact/known-prefix matches.
