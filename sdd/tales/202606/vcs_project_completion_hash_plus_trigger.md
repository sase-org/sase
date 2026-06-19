---
create_time: 2026-06-19 14:54:22
status: done
prompt: sdd/prompts/202606/vcs_project_completion_hash_plus_trigger.md
---
# Plan: Change VCS project completion trigger from `+` to `#+`

## Goal

Change the trigger for the **VCS Project Completion** feature (epic bead `sase-4z`) from a bare `+` to `#+` — i.e.
require a `#` immediately before the `+`. The change must apply to **both** front ends that drive this completion:

1. The `sase ace` **TUI prompt input** (Python).
2. The **xprompt LSP** server used by Neovim (Rust), which the Neovim plugin inherits passively.

After this change:

- Typing `#+` at the start of a prompt, at the start of a line, or after whitespace opens the active-projects menu;
  `#+sa` filters by project name; accepting a project prepends/replaces the VCS workflow tag exactly as today (e.g.
  `#+sa` → `#gh:sase `).
- A **bare `+`** (no preceding `#`) no longer opens the menu. This is the intended, deliberate behavior change.
- `#` alone keeps doing what it does today (xprompt `#foo` completion). The new menu only appears once the `+` is typed
  directly after a triggering `#`.

## Why this is the right design (and why it's mostly contained)

The trigger token is the only thing that changes. The **expansion algorithm is untouched**: today the canonical
transform removes the trigger token span `[start, end)` and prepends/replaces the VCS tag. By making the trigger token
_start one character earlier_ (at the `#` instead of the `+`) and treating the query as the text after `#+`, the
existing strip-and-prepend logic produces byte-identical results. For example, `#+‸` (cursor after `+`) deletes the `#+`
token and prepends `#gh:sase ` → `#gh:sase ` — the same output the bare `+` produced before.

This is enforced by the cross-language parity contract (see `memory/rust_core_backend_boundary.md`): the trigger
detection + expansion live in the Rust core (`editor/completion.rs`, `editor/token.rs`) and are mirrored in Python
(`xprompt/vcs_project_completion.py`), kept honest by a shared golden-vector table. The change must be made
**identically on both sides**.

### The key risk — coexistence with `#`-prefixed completions — is already handled by precedence

`#` is already a trigger for several completions. I verified that `#+` cannot be mis-claimed by any of them, because the
completion dispatcher checks the VCS-project context _before_ the generic `#`-token path, and the `#`-token paths all
require a real name after `#`:

- **xprompt reference / `#name` completion**: the xprompt name regex requires a leading letter/underscore
  (`#([a-zA-Z_]…)` in Python `processor.py`; `scan_name` in Rust). `#+` has no name, so it is never an xprompt
  reference.
- **xprompt-argument completion (`#name(` / `#name:` / `#name+`)**: detection requires a scanned name followed by `(`,
  `: `, or `:: ` (Python `cursor_prefix_may_contain_xprompt_args` checks for `:`/`(`; Rust
  `starts_with_xprompt_directive`). `#+` has neither a name nor those markers, so it is never an xprompt-arg context.
  The `#name+` plus-arg syntax is unaffected — it still requires a name before the `+`.
- **Dispatch order** (Rust `classify_completion_context`, Python `_try_*`/refresh chain): xprompt-arg → directive →
  **vcs_project** → generic `#`/path/snippet token. Because vcs_project is detected before the generic xprompt token
  path, a `#+…` token is routed to vcs_project. No reordering is required; the change is purely "make the vcs_project
  detector match `#+` instead of `+`."

### Trigger characters do **not** change

The LSP currently advertises both `#` and `+` as completion trigger characters. We keep both:

- `#` already fires a request (for `#foo` xprompt completion) — unchanged.
- `+` must remain a trigger character so that typing the `+` in `#+` fires a fresh completion request, at which point
  the server classifies `#+` as vcs_project and returns the project menu. Removing `+` would break auto-opening of the
  menu under `vim.lsp.completion` (which only auto-triggers on advertised trigger characters). A bare `+` request now
  simply classifies as "no context" and returns nothing — harmless.

So the trigger-character list is intentionally left as-is on both the LSP server and the Neovim side (Neovim inherits
the server's list and configures nothing itself).

## Detailed design

### 1. Trigger token detection (core logic, both languages)

New rule: the token immediately preceding the cursor must begin with `#+`, with the `#` at BOF / start-of-line / after
whitespace, and the `#`/`+` adjacent (no space between). The filter query is the text after `#+` up to the cursor.

- **Python** — `src/sase/xprompt/vcs_project_completion.py`:
  - `find_vcs_project_trigger`: after walking back to the token start, require `prompt[start:start+2] == "#+"` (instead
    of `prompt[start] == "+"`); set `query = prompt[start + 2 : cursor]`. The returned `VcsProjectTrigger.start` points
    at the `#`, `end` at the next whitespace/EOL — so the span the expansion consumes now includes the `#`.
  - Update the `VcsProjectTrigger` and `find_vcs_project_trigger` docstrings to describe the `#+` trigger.
- **Rust** — `../sase-core/crates/sase_core/src/editor/token.rs` (open with `sase workspace open -p sase-core 11`):
  - `vcs_project_trigger_token`: require the token text to start with `#+`; the token byte span starts at the `#`.
  - `is_vcs_project_trigger_token`: change `token.starts_with('+')` to `token.starts_with("#+")`.
  - Query extraction in `editor/completion.rs::build_vcs_project_completion_candidates`: change the query slice start
    from `t0 + 1` to `t0 + 2` (skip past `#+`).

The expansion functions (`apply_vcs_project_selection` / `_strip_trigger_token` / `vcs_prepend_offset` / the Rust
`vcs_project_byte_edits` merge path) need **no logic change** — they operate on the trigger span, which now correctly
covers `#+query`. We will, however, re-verify the Rust byte-edit "merge at prepend site" branch against the new BOF `#+`
cases via golden vectors.

### 2. LSP wiring (Rust)

- `crates/sase_xprompt_lsp/src/lsp_convert.rs::vcs_project_completion_item`: change the client-side filter text from
  `format!("+{}", candidate.name)` to `format!("#+{}", candidate.name)` so client filtering matches the typed `#+…`.
  Confirm the item's `textEdit` range still starts at the trigger-token start (the `#`), which it will because the byte
  edits derive from the trigger span.
- `crates/sase_xprompt_lsp/src/server.rs`: **no change** to the `triggerCharacters` list (keep `#` and `+`).

### 3. TUI prompt input (Python)

- `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py` (auto-open block, ~lines 309–318): the menu still
  auto-opens on a `+` keypress, but `_try_vcs_project_completion` → `find_vcs_project_trigger` now gatekeeps on `#+`, so
  a bare `+` no longer opens it. Because the TUI does **not** auto-open any menu on a plain `#` keypress, the common
  flow (`#` then `+`) leaves `_file_completion_active == False` when `+` is pressed, so the existing
  `not self._file_completion_active` guard still permits the open. Tighten the comment to describe the `#+` trigger;
  optionally add an explicit "previous char is `#`" precondition for clarity (the detector already enforces it, so this
  is cosmetic).
- The active-menu refresh path (`_file_completion.py::_refresh_file_completion_from_cursor`, vcs_project branch) needs
  no change — it re-runs `_get_vcs_project_trigger`, which now keeps the menu alive only while a `#+…` token is present
  (deleting back to just `#` dismisses it).
- Update the `+`-trigger doc comments/docstrings in `_file_completion_context.py`, `_file_completion.py`,
  `_prompt_input_bar_completion.py`, and `vcs_project_completion.py` to say `#+`.

## Files to change

**Primary repo (`sase`)**

- `src/sase/xprompt/vcs_project_completion.py` — trigger detection (`find_vcs_project_trigger`) + docstrings.
- `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py` — auto-open comment/precondition.
- `src/sase/ace/tui/widgets/{_file_completion.py,_file_completion_context.py,_prompt_input_bar_completion.py}` — doc
  comment wording (`+` → `#+`).
- `tests/test_xprompt_vcs_project_completion.py` — golden vectors + trigger-detection unit tests.
- `tests/ace/tui/widgets/test_vcs_project_completion.py` — auto-open + acceptance widget tests.
- `memory/glossary.md` — **VCS Project Completion** entry (note: Tier-1 memory file; editing it is covered by approval
  of this plan).

**`sase-core` sibling** (`sase workspace open -p sase-core 11`)

- `crates/sase_core/src/editor/token.rs` — `vcs_project_trigger_token`, `is_vcs_project_trigger_token` (+ their unit
  tests).
- `crates/sase_core/src/editor/completion.rs` — query offset (`t0 + 2`) + `vcs_project_golden_vectors` table.
- `crates/sase_xprompt_lsp/src/lsp_convert.rs` — `filterText` → `#+{name}`.
- `crates/sase_xprompt_lsp/src/server.rs` — only the LSP-level vcs_project classification tests (inputs `+` → `#+`); the
  `triggerCharacters` assertions stay (still includes `+`).

**`sase-nvim` sibling** (`sase workspace open -p sase-nvim 11`)

- `tests/lsp_vcs_project_smoke.lua` — `filterText` assertion `+sase` → `#+sase`; test-case inputs `+…` → `#+…`; comment
  wording. The `+`-trigger-advertised assertion stays valid.
- `README.md` — the `+` trigger documentation (completion table row + the prose + the manual smoke-check steps) → `#+`.

## Tests

Mirror every change on both sides of the parity contract.

1. **Python golden vectors** (`_GOLDEN_VECTORS`): rewrite every `+‸` case as `#+‸`, e.g.
   - `"#+‸"` → `"#gh:sase "`
   - `"#+sa‸"` → `"#gh:sase "`
   - `"Describe this repo. #+‸"` → `"#gh:sase Describe this repo."`
   - `"#+s‸\n"` → `"#gh:sase \n"` and `"#+s‸\nmore text"` → `"#gh:sase \nmore text"` (preserve the blank-line regression
     coverage from the prior fix)
   - `"#git:foo Fix bug #+‸"` → `"#gh:sase Fix bug"`; `"#gh!!:foo do X #+‸"` → `"#gh:sase do X"`
   - `"Line one\n#+‸"` → `"#gh:sase Line one\n"`
   - `"---\nname: x\n---\nBody #+‸"` → `"---\nname: x\n---\n#gh:sase Body"`
   - `"%model:opus Body #+‸"` → `"%model:opus #gh:sase Body"`
   - Replace the old mid-prompt `"Fix +bug‸ here"` case with `"Fix #+bug‸ here"` → `"#gh:sase Fix here"` (keeps coverage
     of the "query trims forward to the next whitespace" path).
2. **Python trigger-detection unit tests** (`test_xprompt_vcs_project_completion.py`):
   - Positive: `find_vcs_project_trigger("#+sa", 4)` → span `(0, 4)`, query `"sa"`; after whitespace; after newline;
     BOF.
   - Negative (the behavior change): bare `+` no longer triggers — `find_vcs_project_trigger("+", 1) is None`, `"+sa"`
     is None; `"# +"` (space between) is None; `"c#+x"` (embedded) is None; `"#"` alone is None.
3. **Rust golden vectors + token unit tests** (`completion.rs::vcs_project_golden_vectors`, `token.rs` tests): byte-
   identical updates to the Python set, including the BOF `#+` and trailing-newline cases (exercise the byte-edit merge
   path), plus positive/negative `is_vcs_project_trigger_token` / `vcs_project_trigger_token` cases.
4. **Rust LSP classification tests** (`server.rs`): update vcs_project request inputs from `+` to `#+`; confirm a bare
   `+` request no longer classifies as vcs_project; keep the `triggerCharacters`-includes-`+` assertion.
5. **TUI widget tests** (`tests/ace/tui/widgets/test_vcs_project_completion.py`): update the auto-open test to type `#+`
   (menu opens) and add a bare-`+`-does-not-open assertion; update the canonical-acceptance parametrization `+` → `#+`.
6. **Neovim smoke test** (`tests/lsp_vcs_project_smoke.lua`): `filterText` → `#+sase`; cases `#+s`,
   `Describe this repo. #+`, `#git:foo Fix bug #+`, `#gh!!:foo do X #+`; keep the start-of-line no-blank-line guard (now
   `#+s`).
7. Re-run the ACE PNG visual snapshot suite — the vcs_project panel snapshot renders with an empty prefix and should be
   unaffected, but confirm no golden drift.

## Verification

- Primary repo: `just install` then `just check`.
- `../sase-core`: `cargo fmt --check`, `cargo test -p sase_core`, `cargo test -p sase_xprompt_lsp`.
- `../sase-nvim`: run `tests/lsp_vcs_project_smoke.lua` headless with `SASE_XPROMPT_LSP_CMD` pointed at the freshly
  built sibling LSP binary.
- Manual end-to-end:
  - TUI (`sase ace`): empty prompt → type `#` (no project menu), then `+` (project menu opens), filter `#+sa`, accept →
    `#gh:sase `; confirm a bare `+` opens nothing.
  - Neovim: in an eligible buffer, type `#+` → menu opens; `#+s` filters; accept → `#gh:sase …`; confirm a bare `+` does
    nothing and that `#foo`/`#foo+`/`#foo:`/`#foo(` xprompt completions are unaffected.

## Risks & mitigations

- **Parity drift** between Python and Rust — mitigated by making the identical detection change on both sides and
  extending the shared golden-vector table in lockstep.
- **Regressing `#`-prefixed completions** (`#name`, `#name:`, `#name(`, `#name+`) — mitigated by the precedence analysis
  above and by explicit negative tests that `#+` routes to vcs_project while `#foo…` routes to the xprompt paths.
- **Discoverability of the new trigger** — bare `+` silently stops working. Mitigated by updating the glossary and the
  Neovim README so the documented trigger matches behavior. (No in-app help string references the `+` trigger today
  beyond the glossary.)
- **Editing a Tier-1 memory file** (`memory/glossary.md`) — per `AGENTS.md` this needs user approval; approval of this
  plan authorizes that single doc edit.

## Out of scope

- No change to the expansion/normalization algorithm, the `%directive`/frontmatter placement rules, or the VCS-tag MRU
  cycling feature (it uses `find_vcs_workflow_tag_prepend_offset`, not the trigger).
- No change to the LSP trigger-character set.
- No migration/backward-compat shim for the old bare `+` trigger (the request is to require `#`).
