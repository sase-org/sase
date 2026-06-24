---
create_time: 2026-06-24 16:21:08
status: done
prompt: sdd/prompts/202606/directive_arg_completion.md
---
# Plan: Auto-completion for `%effort:` and `%auto:` directive argument values

## Goal

When a user types the `:` separator (and any partial text after it) for a directive whose argument is drawn from a
**fixed set of valid values**, pop a completion menu of those values. Initially this covers the two such directives:

- `%effort:` → `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`
- `%auto:` → `plan`, `tale`, `epic`

This must work in **both** front-ends:

1. The **ACE TUI prompt input widget** (Python / Textual).
2. **Neovim**, via the **xprompt LSP server** (Rust, in the `sase-core` linked repo).

The behavior mirrors how directive _name_ completion (`%eff…` → `%effort`) and `#+` VCS-project completion already work:
the menu opens automatically as you type (gated by the directive auto-menu setting), supports prefix filtering, accepts
a selection by replacing the partial token, and stays in parity between the Python TUI and the Rust LSP.

## Background / current state (important — narrows the scope)

Research shows the two front-ends are in very different states today:

### Rust core / xprompt LSP — already implemented

On `sase-core` master the directive-argument machinery already exists and already covers `effort` and `auto`:

- The directive registry (`crates/sase_core/src/editor/directive.rs`) already contains `effort` (`takes_argument: true`)
  and `auto` (alias `a`, `takes_argument: true`).
- `directive_argument_candidates()` already returns the shared effort vocabulary for `effort`, and
  `("plan", "tale", "epic")` for `auto`.
- Context detection (`crates/sase_core/src/editor/completion.rs::directive_arg_token` /
  `detect_directive_context_at_position`) already classifies `%effort:` and `%auto:` as `DirectiveArgument` context,
  validated against the registry via `canonical_directive_name`.
- The LSP server already advertises `:` as a completion trigger character and dispatches `DirectiveArgument` contexts to
  `directive_argument_candidates`.

**Conclusion:** The Neovim/LSP side most likely already works end-to-end. The LSP portion of this work is therefore
**verification + a regression test + making sure the Python repo builds/uses the current core**, not new feature code.
If verification turns up a gap, the fix is small (a registry/candidate or detection tweak) and lands in `sase-core`.

### Python ACE TUI — missing

The TUI completes directive **names** only. `directive_completion.py` builds `%effort` / `%auto` name candidates and
shows a static, display-only argument _hint_ (`:level`, `:plan|tale|epic`) in the panel — but there is **no menu for the
value after the `:`**. The completion pipeline has no `directive_arg` kind. This is the bulk of the implementation work.

### Parity convention (how Python and Rust stay in sync)

Editor completion is intentionally implemented **in parallel** in Python and Rust and kept in parity by shared
vocabularies and golden/parity tests — not by calling Rust through the `sase_core_rs` binding. Precedents:

- VCS-project completion: mirrored Python (`xprompt/vcs_project_completion.py`) + Rust (`editor/completion.rs`), kept in
  parity by a shared golden-vector table duplicated in both test suites.
- Directive-name completion: reimplemented as pure Python in `directive_completion.py`.
- Effort vocabulary: `EFFORT_LEVELS_ORDERED` exists independently in `src/sase/xprompt/effort.py` and
  `crates/sase_core/src/effort.rs`, with an in-code comment noting they mirror each other.

This plan follows that convention: the TUI gets a **pure-Python** value-completion provider that reuses the existing
Python vocabularies, and a parity test ties the value sets to the canonical Rust lists.

## Single source of truth for the value sets

- **Effort:** reuse `EFFORT_LEVELS_ORDERED` from `src/sase/xprompt/effort.py`. No new list.
- **Auto:** the valid modes `("plan", "tale", "epic")` currently live **inline** inside `directives.py` (the `%auto`
  validation). Extract them into a single named constant (e.g. `AUTO_MODES_ORDERED`, plus a frozenset for membership) in
  the directive-types module, and have the existing `%auto` validation import and use it. The completion provider then
  reads the same constant, so the menu can never drift from what the parser accepts.

This keeps "what the menu offers" and "what the parser validates" identical by construction, for both directives.

## Design — Python ACE TUI

Model the new value-completion path on the existing **directive-name** completion path (closest structural analog — same
`%` token family) and the **`xprompt_arg_value`** path (closest "value after a separator" analog).

### 1. Pure-logic provider (extend `directive_completion.py`)

Add two pieces alongside the existing name-completion logic:

- **Context extraction** — `extract_directive_arg_token_around_cursor(line, col)` returning
  `(arg_start, arg_end, directive_name, partial)` or `None`. It detects the pattern `%<name>:<partial>` where the cursor
  sits in the argument region (at or after the `:`). It resolves `<name>` through the directive aliases (so `%a:` maps
  to `auto`), and only succeeds for a recognized directive. `arg_start`/`arg_end` bound the partial value token so
  acceptance can replace exactly that span. Must fire with an **empty** partial (cursor immediately after `:`), so the
  full value list shows the instant `:` is typed.

- **Candidate building** — `build_directive_arg_completion_candidates(directive_name, partial)` returning
  `(candidates, shared_extension)`:
  - Look up the canonical directive's ordered value list from a small mapping
    `{ "effort": EFFORT_LEVELS_ORDERED, "auto": AUTO_MODES_ORDERED }`. Directives **not** in this mapping (e.g. `model`,
    `name`, `group`) return `[]` — no menu — matching the Rust "open text" behavior.
  - Filter values by case-insensitive prefix on `partial`; empty `partial` returns all values in canonical order.
  - Build `CompletionCandidate`s with `display`/`insertion` = the value, and metadata carrying a short per-value
    description for the panel (e.g. effort level / auto-mode meaning).
  - Compute `shared_extension` (common prefix beyond `partial`) the same way name completion does, so Tab can extend a
    unique partial.

### 2. Wire into the completion pipeline

Mirror the directive-name wiring across the four pipeline touch-points (new completion kind: `"directive_arg"`):

- **Context bridge** (`_file_completion_context.py`): add `_get_directive_arg_token_context()` returning
  `(row, arg_start, arg_end, directive_name, partial)`.
- **Open / trigger** (`_file_completion_open.py`): add `_try_auto_directive_arg_completion()` and call it from
  `_try_auto_prompt_reference_completion()`. Precedence: attempt directive-arg **before** directive-name (they are
  mutually exclusive by token shape — an arg token contains a `:` — but ordering keeps intent clear). Also handle the
  directive-arg case in the explicit `Ctrl+T` / Tab completion entry point so manual completion works too.
- **Refresh** (`_file_completion_refresh.py`): when the active kind is `"directive_arg"`, re-extract context and rebuild
  candidates after each edit; clear the menu when the cursor leaves the arg region.
- **Render** (`_prompt_input_bar_completion.py`): add a `_append_directive_arg_completion_row()` branch that styles the
  value and shows its description (consistent with the directive-name row styling).
- **Accept:** reuse the existing selection-acceptance machinery, replacing `[arg_start, arg_end)` with the chosen value.

### 3. Setting / gating

Reuse the existing `auto_directive_menu` setting to gate the value menu as well (it is conceptually "directive
completion"), so no new config surface is needed. If, during review, separating turns out to be preferable, add a
dedicated `auto_directive_arg_menu` setting and its default in `src/sase/default_config.yml` (per the default-config
convention for new config values). Recommendation: reuse the existing setting unless there's a reason to split.

## Design — Neovim / xprompt LSP (Rust)

Primary task is **verification**, since the backend already supports `effort`/`auto` argument candidates:

1. Confirm end-to-end in Neovim that typing `%effort:` and `%auto:` (including the empty-arg case right after `:`)
   yields the expected value menu through the LSP.
2. Ensure the Python repo is built against current `sase-core` (rebuild the `sase_core_rs` binding / LSP binary via the
   standard install step) so the shipped LSP reflects the registry that already contains `effort`/`auto`.
3. Add a focused **regression test** in `sase-core` asserting that `%effort:` and `%auto:` classify as
   `DirectiveArgument` and that `directive_argument_candidates` returns the full effort vocabulary and `plan|tale|epic`
   respectively (lock in the behavior so a future registry edit can't silently drop it).
4. Only if verification reveals a real gap: make the minimal registry/detection/candidate fix in `sase-core` (bindings +
   tests updated there per the core-backend-boundary rule).

All `sase-core` changes go through the linked-repo workflow.

## Parity guarantee

- **Effort:** Python and Rust both derive candidates from their respective `EFFORT_LEVELS_ORDERED`, which already mirror
  each other. No drift risk beyond the existing mirrored constants.
- **Auto:** after extracting `AUTO_MODES_ORDERED` in Python, add a Python test asserting the ordered auto modes equal
  the canonical list that the Rust `directive_argument_candidates("auto")` arm produces (hard-coded expected
  `("plan", "tale", "epic")`), with a cross-reference comment on both sides — the same mirroring discipline used for the
  effort vocabulary.

## Testing

**Python (TUI provider, pure-logic — primary coverage):**

- Arg-token extraction: detects `%effort:`/`%auto:` with cursor after `:` (empty and partial); alias form `%a:` resolves
  to `auto`; does not fire for a bare `%effort` name (no colon), for non-directive `%` tokens, or when the cursor is
  back in the name; correct `arg_start`/`arg_end` spans.
- Candidate building: full effort vocabulary and full auto modes for empty partial; prefix filtering (`%effort:h` →
  `high`; `%auto:t` → `tale`); case-insensitivity; unknown/open-text directive (`%model:`) yields no candidates;
  `shared_extension` extends a unique partial.
- Acceptance replaces exactly the partial span with the selected value.
- Auto-mode parity test (Python list vs. canonical Rust list).

**Python (TUI integration):** a widget-level test that typing `%effort:` opens the value menu and selecting an item
inserts it; confirm the menu closes when leaving the arg region. Add/refresh PNG snapshot coverage for the new
completion-kind row if the visual suite covers the completion panel.

**Rust (`sase-core`):** the regression test described above for `effort`/`auto` argument classification + candidates.

## Documentation / housekeeping

- Update the ACE `?` help popup / any prompt-input completion docs if they enumerate completion triggers, to mention
  directive-argument value completion (per the ace help-popup-sync convention).
- Consider a glossary note that `%effort` / `%auto` arguments auto-complete from a fixed value set in both the TUI and
  the Neovim LSP.

## Out of scope (possible follow-ups)

- Value completion for open-text directives (`%model`, `%name`, `%group`, `%wait`, `%repeat`) — these have no fixed
  value set; the provider returns no candidates for them by design.
- Extending TUI value completion to the `%model:<model>@<effort>` suffix (the Rust LSP already handles this; the TUI
  could mirror it later, but it's beyond the `%effort:` / `%auto:` request).

## Files expected to change

**Python (this repo):**

- `src/sase/ace/tui/widgets/directive_completion.py` — arg-token extraction + value-candidate building.
- `src/sase/ace/tui/widgets/_file_completion_context.py` — directive-arg context bridge.
- `src/sase/ace/tui/widgets/_file_completion_open.py` — auto + explicit trigger for the new kind.
- `src/sase/ace/tui/widgets/_file_completion_refresh.py` — refresh handling for the new kind.
- `src/sase/ace/tui/widgets/_prompt_input_bar_completion.py` — render the value rows.
- `src/sase/xprompt/_directive_types.py` (and `src/sase/xprompt/directives.py`) — extract `AUTO_MODES_ORDERED` as the
  single source of truth for `%auto` modes and have the parser use it.
- `src/sase/default_config.yml` — only if a dedicated gating setting is chosen over reusing `auto_directive_menu`.
- Tests under `tests/` for the provider, integration, and auto-mode parity; PNG snapshots if applicable.

**Rust (`sase-core` linked repo):**

- `crates/sase_core/src/editor/directive.rs` / `completion.rs` — regression tests for `%effort:` / `%auto:` argument
  candidates (and a minimal fix only if verification finds a gap).
