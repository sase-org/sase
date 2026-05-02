---
create_time: 2026-04-24 21:27:39
status: done
bead_id: sase-o
prompt: sdd/prompts/202604/nvim_ctrl_t_completion.md
---
# Plan: `<ctrl+t>` Completion Keymap for sase-nvim

## Problem

The `sase ace` TUI prompt input widget (Textual `PromptTextArea`) supports rich completion via `<ctrl+t>` that
dispatches between three modes based on cursor context:

| Mode                          | Triggered when cursor is on…                                       | Data source                           |
| ----------------------------- | ------------------------------------------------------------------ | ------------------------------------- |
| **xprompt**                   | a `#token`                                                         | `sase xprompt list` (JSON)            |
| **file**                      | a path-like token (`/foo`, `~/foo`, `./foo`, `dir/file.ext`, etc.) | local filesystem                      |
| **saved file** (file history) | empty / no token                                                   | `~/.sase/file_reference_history.json` |

The `sase-nvim` plugin currently only supports xprompt completion, and only via the `#@` insert-mode trigger /
`:SaseXPrompts` command — there is no `<ctrl+t>` keymap and no file or file-history support.

We want sase-nvim's `<ctrl+t>` to mirror the TUI: same dispatch logic, same data, same insertion semantics, exposed as
an insert-mode keymap that users can opt into in any buffer (or scoped to specific filetypes / config files).

## Reference (TUI) implementation in `sase_101`

| File                                                           | Purpose                                                                                                                            |
| -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/ace/tui/widgets/prompt_text_area.py` (lines 274-279) | `<ctrl+t>` key handler in `_on_key` → `_try_file_completion_tab()`                                                                 |
| `src/sase/ace/tui/widgets/_file_completion.py` (lines 239-311) | Mixin that does the dispatch: empty token → history, `#…` → xprompt, path-like → file                                              |
| `src/sase/ace/tui/widgets/file_completion.py`                  | Pure logic: `is_path_like_token`, `build_completion_candidates`, `build_file_history_completion_candidates`, `CompletionCandidate` |
| `src/sase/ace/tui/widgets/xprompt_completion.py`               | Pure logic: `is_xprompt_like_token`, `build_xprompt_completion_candidates`                                                         |
| `src/sase/history/file_references.py` (lines 17-89)            | `load_file_references()`, regex that extracts paths from prompts                                                                   |

In-completion bindings (all modes): `<ctrl+n>` / `<down>` next, `<ctrl+p>` / `<up>` prev, `<ctrl+l>` accept, `<esc>`
cancel. File-history mode also supports `<ctrl+d>` to delete the highlighted entry.

## Existing sase-nvim surface

- `plugin/sase_xprompt.lua` — `InsertCharPre` autocmd intercepts `#@`, plus `:SaseXPrompts` and `:SaseXPromptsRefresh`
  user commands.
- `lua/sase/xprompt.lua` — fetches via `sase xprompt list`, caches, dispatches to Telescope or `vim.ui.select`. Exposes
  helpers `_format_display`, `_format_entry`, `_insert_at_cursor`, `_fetch_xprompts`, `_restore_insert_mode`.
- `lua/telescope/_extensions/sase.lua` — Telescope extension registering the `sase.xprompts` picker.
- No tests, no `justfile`, no CI. Code style: 2-space indent, LuaDoc annotations, `vim.*` API only (no third-party deps
  beyond optional Telescope).

## High-level approach

1. **Land thin "list" CLI commands in `sase_101`** to expose file history (and optionally file-system completion
   candidates) as JSON, mirroring the existing `sase xprompt list` pattern. The TUI mixin already centralises the logic
   — we just wrap and re-export it through the CLI so sase-nvim doesn't have to reimplement path/history rules.
2. **Refactor `sase-nvim` into a generic completion dispatcher** (`lua/sase/complete.lua`) that owns `<ctrl+t>` and
   routes to per-mode pickers. Existing xprompt code is folded in but its public entry points (`pick`, `:SaseXPrompts`,
   `#@` trigger) are preserved.
3. **Implement each mode** (xprompt, file, saved-file) as its own picker module under `lua/sase/complete/`, sharing
   common infra: token detection, Telescope extension, insertion + insert-mode restore.

## Phasing

Five phases. Phase 1 is upstream (sase repo); Phases 2-5 are in sase-nvim. Phase 2 must land before 3-5; once Phase 2 is
in, Phases 3, 4, 5 are largely independent and could be parallelised, but for simplicity the plan assumes sequential
agents.

Each phase is self-contained: an agent should be able to read the plan section + the referenced files and finish without
further context. Each phase ends with a verification step.

---

### Phase 1 — Add `sase` CLI subcommands for file & file-history completion

**Repo:** `sase_101` (main sase repo, this directory).

**Goal:** Expose the data sources the TUI uses so sase-nvim (and other clients) can query them without reimplementing
logic.

**Deliverables:**

1. **`sase file-history list`** — emits JSON `{"paths": ["...", ...]}` (or a bare array; pick whichever matches the
   existing `sase xprompt list` shape). Wraps `sase.history.file_references.load_file_references()`. Most-recent-first
   ordering, same as the TUI shows.

2. **`sase file-history delete <path>`** — removes one entry from `~/.sase/file_reference_history.json`. Used by
   sase-nvim's `<ctrl+d>` binding in file-history mode. Look at how the TUI mixin removes entries
   (`_delete_selected_file_completion` in `_file_completion.py`) and reuse that helper if one exists; otherwise add a
   thin `delete_file_reference(path)` to `src/sase/history/file_references.py` and call it from both places.

3. **`sase file list [--path PATH] [--token TOKEN]`** — emits JSON list of `CompletionCandidate` objects
   (`{display, insertion, is_dir, name}`) by calling `build_completion_candidates()` from
   `src/sase/ace/tui/widgets/file_completion.py`. `--path` defaults to CWD; `--token` is the partial token under cursor
   (used by the same builder). If wiring this up turns out to be substantially more complex than the history commands
   (e.g. the builder takes TUI-specific objects), defer to Phase 5 and have sase-nvim do filesystem walking in Lua
   instead — leave a note in the plan and ship just the history commands.

**Where to register:**

- Look at `src/sase/cli/parser_commands.py` around line 620 for the `xprompt list` registration; mirror that pattern.
- Handler files probably live under `src/sase/cli/handlers/` (check for `xprompt_handler.py` referenced in the report) —
  add `file_history_handler.py` and (if shipping) `file_handler.py`.

**Conventions:** Follow `memory/short/gotchas.md` — every CLI argument needs a short option (`-p` for `--path`, `-t` for
`--token`, etc.).

**Tests:** Add unit tests next to the existing CLI tests for `xprompt list`. At minimum cover: empty history, populated
history, delete-existing, delete-nonexistent (should be a no-op or clear error — match what the TUI does).

**Fix-along:** the report flagged that `prompt_input_bar.py:95` advertises `[^F]` but the actual binding is `<ctrl+t>`.
Fix that string to `[^T]` in this phase since you're in the area.

**Done when:**

- `just check` passes in `sase_101`.
- `sase file-history list` and `sase file-history delete <p>` work end-to-end against
  `~/.sase/file_reference_history.json`.
- (If included) `sase file list --path . --token src/` returns plausible JSON.
- A line in `memory/short/build_and_run.md` or a section in the README documents the new commands.

---

### Phase 2 — sase-nvim dispatcher skeleton + `<ctrl+t>` keymap

**Repo:** `sase-nvim` (`/home/bryan/projects/github/sase-org/sase-nvim/`).

**Goal:** Lay down the infrastructure that Phases 3-5 will plug into. No new completion modes yet — but the existing
xprompt mode keeps working.

**Deliverables:**

1. **`lua/sase/complete.lua`** — public module exposing:
   - `M.trigger(opts?)` — entry point invoked by `<ctrl+t>`. Reads the token under cursor, classifies it (`xprompt` /
     `file` / `file_history` / `nil`), dispatches to the right per-mode picker. For now, only the xprompt branch is
     wired; the others log "not yet implemented" and fall through to a no-op.
   - `M.setup(opts)` — installs the keymap (default `<C-t>` in insert mode, configurable). Default is **opt-in** (no
     keymap unless the user calls `setup`) to avoid clobbering keys for users who installed the plugin only for syntax
     highlighting. Document this clearly.

2. **`lua/sase/complete/_token.lua`** — pure helpers:
   - `token_under_cursor()` → `{text, row, col_start, col_end}` or `nil`.
   - `classify(token)` → `"xprompt" | "file" | "file_history" | nil`. Mirror the rules in
     `src/sase/ace/tui/widgets/file_completion.py:is_path_like_token` and `xprompt_completion.py:is_xprompt_like_token`.
     Empty/no token → `"file_history"`. Port the regexes faithfully and add Lua busted-style tests if any test infra
     exists, otherwise inline `assert`-based smoke tests in a `:lua` block in the README.

3. **`lua/sase/complete/_picker.lua`** — shared Telescope/`vim.ui.select` plumbing. Factor out of
   `lua/telescope/_extensions/sase.lua` the parts that aren't xprompt-specific: in-picker keymaps (`<C-n>`, `<C-p>`,
   `<C-l>`, optional `<C-d>` callback), accept handler that calls back into a mode-specific `insert(item)` function, and
   the insert-mode restore dance currently in `xprompt.lua`'s `restore_insert_mode`.

4. **Refactor existing xprompt code** to use the new shared picker. The current `:SaseXPrompts`, `:SaseXPromptsRefresh`,
   and `#@` trigger MUST keep working unchanged from the user's perspective. `lua/sase/xprompt.lua` becomes a thin
   module whose `pick` is also reachable as `lua/sase/complete/xprompt.lua` (or stays where it is and the new dispatcher
   calls into it).

5. **`plugin/sase_complete.lua`** — registers the `<C-t>` keymap iff the user opted in via `setup({ keymap = true })`.
   Keep it separate from `sase_xprompt.lua` so users can disable one without the other.

**Non-goals:** No new CLI calls. No file or file-history pickers yet. The dispatcher should print
`vim.notify("file completion not yet implemented", vim.log.levels.WARN)` (or equivalent) for unimplemented branches.

**Done when:**

- Pressing `<C-t>` in insert mode (after `setup`) on a `#foo` token opens the existing Telescope xprompt picker.
- Pressing `<C-t>` on a path-like token notifies "not yet implemented" without breaking anything.
- The `#@` trigger still works.
- README updated with a "Setup" section showing `require("sase").setup{ complete = { keymap = true } }`.

---

### Phase 3 — xprompt mode under `<ctrl+t>` (polish)

**Repo:** `sase-nvim`.

**Goal:** Make the `<ctrl+t>` xprompt branch first-class — a clean handoff from Phase 2's stub, including correct token
replacement (not just append).

**Deliverables:**

1. The `<ctrl+t>` xprompt branch should **replace** the `#token` under cursor with `#chosen_name`, not insert beside it.
   Compare with the TUI behaviour — `_file_completion.py` lines around 280-310 show how the token range is computed and
   replaced.

2. Use the cached `_fetch_xprompts` from `lua/sase/xprompt.lua` (don't re-shell out). Confirm cache invalidation still
   works via `:SaseXPromptsRefresh`.

3. Insert-mode restore: cursor ends up immediately after the inserted `#name`, in insert mode. Reuse
   `_restore_insert_mode`.

4. Edge cases:
   - Cursor on `#` alone (empty xprompt token) → still open picker, replace the lone `#`.
   - Cursor on `#xpr|ompt` (mid-token) → use the whole `#xprompt` as the token to replace.
   - Cursor on `# foo` (with space) → not an xprompt token, classifier returns `nil` and we fall to file-history (empty
     token under cursor).

5. Tests / manual verification checklist in the PR description: each edge case above plus a regression check that `#@`
   still works.

**Done when:** `<C-t>` on `#fo|` shows the xprompt picker; accepting `#foobar` replaces the partial token cleanly;
`:SaseXPrompts` and `#@` still behave.

---

### Phase 4 — saved-file (file-history) mode

**Repo:** `sase-nvim`. Depends on Phase 1's `sase file-history list` and `sase file-history delete`.

**Goal:** Wire `<C-t>` on an empty cursor to a Telescope picker over `sase file-history list`, with `<C-d>` deletion.

**Deliverables:**

1. **`lua/sase/complete/file_history.lua`** — fetches via `vim.fn.jobstart({"sase", "file-history", "list"}, ...)`,
   caches results, exposes `pick(opts)`. Modeled after `lua/sase/xprompt.lua`.

2. **Telescope extension:** add a `file_history` picker to `lua/telescope/_extensions/sase.lua` (or a new sibling
   extension). Border title `"recent files"`, subtitle `"[^L] accept  [^D] delete"` (mirror the TUI). Inserted text is
   the bare path (no `@` prefix — the TUI doesn't add one back either; double-check by reading `_file_completion.py`).

3. **`<C-d>` deletion:** in-picker keybind that shells out `sase file-history delete <selected>` and refreshes the
   picker in place. Use Telescope's `actions.refresh` pattern.

4. **Fallback:** when Telescope isn't installed, `vim.ui.select` with no delete support is fine.

5. **Cache:** invalidate on each successful insert (the user just used a path, so its position in the recency list will
   change next time anyway — easier to just refetch). Add `:SaseFileHistoryRefresh` user command for parity with
   xprompt.

**Done when:** `<C-t>` with empty cursor opens a picker of recent paths; selecting one inserts the path; `<C-d>` removes
the entry from `~/.sase/file_reference_history.json` and the picker.

---

### Phase 5 — file (filesystem) completion mode

**Repo:** `sase-nvim`. Depends on Phase 2. Optionally depends on Phase 1's `sase file list` (decide based on whether
Phase 1 shipped it).

**Goal:** Wire `<C-t>` on a path-like token to file completion.

**Two options — pick one in this phase based on what Phase 1 delivered:**

**Option A (preferred if Phase 1 shipped `sase file list`):** Shell out `sase file list --path <dir> --token <token>`,
render results in the picker.

**Option B (Lua-native fallback):** Walk the filesystem in Lua using `vim.loop.fs_scandir`. Replicate the rules from
`src/sase/ace/tui/widgets/file_completion.py`:

- Resolve `~` → `$HOME`.
- Token like `dir/par|` → list `dir/`, filter by prefix `par`.
- Show `📁 dir/` for directories (with trailing `/`) and `📄 file.ext` for files.
- Accepting a directory drills down (re-opens the picker rooted there). The TUI does this; Telescope's `attach_mappings`
  can re-invoke the picker with new opts.

**Deliverables:**

1. **`lua/sase/complete/file.lua`** — picker module, either Option A or B.
2. **Telescope picker** — border title shows the directory being browsed; supports the directory-drilldown UX.
3. **Edge cases:** absolute paths (`/etc/foo|`), home-relative (`~/proj|`), explicit-relative (`./src|`, `../sib|`),
   dot-dirs (`.sase/foo|`), bare-relative-with-extension (`mod/file.lua|`). Each should land in the right starting
   directory.
4. **README:** add a brief "Completion modes" table mirroring the one at the top of this plan.

**Done when:** `<C-t>` on `src/sase/ace/tui/wid|` shows files under `src/sase/ace/tui/widgets/` filtered to that prefix;
accepting a directory drills down; accepting a file inserts the full path.

---

## Cross-cutting notes

- **Don't introduce runtime-specific assumptions.** The CLI commands added in Phase 1 are runtime-agnostic; sase-nvim is
  one consumer, but Codex/Gemini/Claude integrations might consume the same data later.
- **Memory/preferences won't run hooks** — the `<C-t>` keymap is a Neovim binding, not a sase hook. No `update-config`
  skill needed.
- **Each phase MUST run `just check` in the appropriate repo before completion.** For Phase 1 that's `sase_101`. For
  Phases 2-5 there's no `just check` in sase-nvim today — instead, manually load the plugin in Neovim and verify the
  deliverables checklist for the phase. Consider adding a minimal `selene`/`luacheck` config + a `Makefile` target as a
  side quest in Phase 2, but it's not blocking.
- **Commit boundaries:** each phase is one PR/commit (or a small commit series). Don't bundle phases — the user
  explicitly wants them executed by separate agent instances.
- **`chezmoi apply`:** none of these phases touch `~/.local/share/chezmoi/`, so this isn't needed. Mentioned for
  completeness because `external_repos.md` requires it for chezmoi changes.

## Open questions for the user before kicking off Phase 1

1. **CLI command shape:** prefer `sase file-history list` (noun-verb under a single `file-history` group) or
   `sase history file-refs list` (matches the internal module name `file_references.py`)? The plan assumes the former.
2. **Should Phase 1 attempt `sase file list`?** It's the trickiest of the three commands because the builder takes
   TUI-aware inputs. Easiest path is to ship just the history commands in Phase 1 and have Phase 5 use Lua-native
   filesystem walking (Option B).
3. **Default keymap:** opt-in via `setup({ complete = { keymap = true } })` (plan assumes this), or unconditional bind
   on `<C-t>` in insert mode? The latter is more discoverable but risks clobbering user keymaps.
