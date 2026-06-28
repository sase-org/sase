---
create_time: 2026-06-28 13:13:54
status: done
---
# Plan: Lift xprompt frontmatter into the property panel on prompt-history load

## Problem

When a user loads a prompt from the **prompt history panel** into the prompt input bar, the **xprompt property panel**
(the structured "Frontmatter Panel" shown directly above the top prompt input widget) is _not_ populated with the
prompt's xprompt properties. The leading YAML frontmatter block (the `---`-delimited `name:` / `description:` / `tags:`
/ `input:` / `xprompts:` / `skill:` / `snippet:` properties) stays inline as verbatim body text, and the panel stays
empty/hidden.

The user wants the frontmatter lifted into the structured panel on load, and wants this behavior unified across _all_
prompt-mode bar loads (history load and the bar-construction / relaunch `initial_value` path), so every prompt-mode load
behaves the same.

## Root cause

The Frontmatter Panel is driven entirely by the **raw frontmatter string stored on the prompt-stack state**
(`PromptStackState.frontmatter`). The panel is shown when that string is non-empty (`auto_show_frontmatter_panel` on
mount, `refresh_frontmatter_panel_from_stack` after a reload) and hidden when empty.

The prompt-history **LOAD** action funnels into the stack-rendering helper `load_stack_from_text(text)`, which builds
the new stack via `_state_from_text(text)`. There are **two distinct defects** in that path:

1. **Single-pane frontmatter prompts are never lifted (the "verbatim contract").** For prompt text whose body has no
   real `---` separators (the common case — a single prompt that happens to carry leading YAML frontmatter),
   `_state_from_text` returns `PromptStackState.single(text)`, which deliberately keeps the _entire_ text — frontmatter
   block included — verbatim in one pane. `_stack.frontmatter` stays `""`, so the panel can never populate. This is the
   documented, tested behavior today (`test_single_prompt_with_frontmatter_stays_verbatim`).

2. **Multi-pane frontmatter prompts are lifted but the panel is never refreshed.** For prompt text whose body _does_
   contain real `---` separators, `_state_from_text` returns `PromptStackState.from_text(text)`, which _does_ lift the
   leading frontmatter onto `_stack.frontmatter`. But `load_stack_from_text` never calls
   `refresh_frontmatter_panel_from_stack()` afterward (its sibling `load_stack_from_xprompt_markdown` does), so the
   panel stays hidden even though the data was lifted.

Both history entry points ultimately share this logic:

- The in-bar history picker (`on_prompt_input_bar_history_requested` → LOAD) calls `bar.load_stack_from_text(...)`.
- The "history from last selection" entry (`_start_prompt_history_from_last_selection` → LOAD) mounts a fresh bar via
  `_show_prompt_input_bar_for_home(initial_text=...)`, which constructs `PromptInputBar(initial_value=...)`; that
  constructor also calls `_state_from_text(initial_value)`, and `on_mount` then calls `auto_show_frontmatter_panel()`.

So a single fix at `_state_from_text` (lift single-pane frontmatter) plus the missing
`refresh_frontmatter_panel_from_stack()` call in `load_stack_from_text` corrects every prompt-mode load path at once,
satisfying the "unify everywhere" decision.

## Design decisions (from Q&A)

- **Q1 — Lift it into the panel.** Strip the leading `---…---` frontmatter block out of the body and surface it in the
  structured panel. Re-submission stays byte-identical for canonical prompts. This intentionally reverses today's
  single-pane verbatim contract.
- **Q2 — Unify everywhere.** Apply the same lifting to the bar-construction / relaunch `initial_value` path in prompt
  mode, not just the history LOAD path, and update the existing verbatim test accordingly.

## Scope / non-goals (please confirm)

- **In scope:** lifting **YAML frontmatter** (`---`-delimited blocks containing the Frontmatter-Panel field set: `name`,
  `description`, `tags`, `input`, `xprompts`, `skill`, `snippet`) into the structured panel, on every prompt-mode bar
  load.
- **Out of scope:** inline prompt body directives that use the `%…` / `#…` mini-language (e.g. `%name:`, `#git:`,
  `%m:`). These are _not_ YAML frontmatter and are not modeled by the Frontmatter Panel; they correctly remain in the
  prompt body. (The example screenshot shows a prompt built from these inline directives; note that those specifically
  will not move into the panel — only a leading `---…---` YAML block will.) If the intent was actually to surface the
  inline directives, that is a different, larger feature and this plan should be re-scoped.
- `initial_panes` (bulk kill-and-edit) keeps its own one-verbatim-pane-per-agent contract and is **not** changed.
- Feedback / approve-prompt bars mount no panel and are **not** changed.

## Technical approach

Keep the raw-frontmatter-string-as-source-of-truth model intact (it preserves the byte-stable join/attach contract used
at launch). Only change _where_ frontmatter is lifted off the loaded text, and ensure the panel is re-synced.

### 1. Lift frontmatter for single-pane prompt-mode loads

In the prompt-stack state model, add a frontmatter-lifting single-pane construction that:

- extracts the leading frontmatter (reusing the existing `_extract_frontmatter` helper, which already matches the launch
  parser), and
- keeps the **remaining body verbatim** as exactly one pane (no canonical `split_prompt_text` pass, so leading/trailing
  body whitespace is preserved exactly as authored — unlike `from_text`, which strips/normalizes).

This can be a small new classmethod on the state (e.g. a `lift_frontmatter` keyword on the existing single-pane
constructor, since its only callers are the two lines of `_state_from_text`). When the text has no frontmatter, the
result is byte-identical to today's verbatim single pane (verified), so non-frontmatter single prompts are unaffected.

Update `_state_from_text` so the prompt-mode single-pane branch uses this lifting constructor. The multi-pane branch
already lifts via `from_text` and is unchanged. Feedback / approve-prompt modes still use the plain verbatim `single`.

### 2. Refresh the panel after a whole-bar history load

Add the missing `refresh_frontmatter_panel_from_stack()` call at the end of `load_stack_from_text` (mirroring
`load_stack_from_xprompt_markdown`). This both **shows** the panel when the loaded prompt lifted frontmatter and
**hides** it when a subsequent load clears all properties. It does not steal focus from the body. This fixes defect #2
(multi-pane) and completes defect #1 for the in-bar history picker path.

### 3. `initial_value` construction path is covered automatically

The `PromptInputBar(initial_value=...)` constructor already routes through `_state_from_text`, and `on_mount` already
calls `auto_show_frontmatter_panel()`, which reveals the panel when `_stack.frontmatter` is non-empty. With change #1,
single-pane frontmatter is lifted at construction time, so the panel auto-shows on mount for the relaunch /
history-from-last-selection / quick-launch paths with no further change. (The Frontmatter Panel is composed from
`_stack.frontmatter`, so it already receives the lifted value.)

### Byte-identical re-submission

On submit, `current_prompt_text()` → `PromptStackState.join()` re-attaches the lifted frontmatter above the (stripped)
body. For canonical prompts (frontmatter immediately followed by the body, no surrounding body whitespace) this
reproduces the original bytes exactly (verified). For prompts with extra leading/trailing body whitespace, `join()`
strips it — but `join()` already stripped on submit before this change and already does so for multi-pane prompts, so
this is consistent existing behavior, not a new regression. Worth a one-line note in the plan/PR; not expected to matter
in practice.

## Files to change (repo-relative)

- `src/sase/ace/tui/widgets/prompt_stack.py`
  - Add the frontmatter-lifting single-pane construction (body kept verbatim, frontmatter lifted).
- `src/sase/ace/tui/widgets/_prompt_input_bar_stack_rendering.py`
  - `_state_from_text`: prompt-mode single-pane branch lifts frontmatter; update its docstring (it currently states
    single-prompt frontmatter rendering is "unchanged"/verbatim).
  - `load_stack_from_text`: call `refresh_frontmatter_panel_from_stack()`; update its docstring.
  - `load_stack_from_xprompt_markdown` docstring: it contrasts itself against `load_stack_from_text`'s old "keeps
    frontmatter verbatim" behavior — reword, since both now lift; the remaining distinction is that the markdown path
    always splits/strips the body while the text path keeps a lone body verbatim.
  - `xprompt_markdown_for_editor` docstring: the note about single-pane inline frontmatter "living verbatim in the pane"
    is now stale (it is lifted onto the stack); reword.
- `src/sase/ace/tui/widgets/prompt_input_bar.py`
  - Constructor comment for `initial_xprompt_markdown` claims it is "distinct from `initial_value` history-load
    semantics, which keep a single frontmatter prompt as one verbatim pane" — update, since `initial_value` now lifts
    too.

## Tests

Update:

- `tests/ace/tui/widgets/test_prompt_input_bar_stack.py`
  - `test_single_prompt_with_frontmatter_stays_verbatim` → rewrite (rename) to assert lifting: the pane holds only the
    body, `_stack.frontmatter` holds the `---…---` block, the panel is visible, and `current_prompt_text()` round-trips
    to the original bytes.
  - Confirm `test_single_prompt_renders_one_solo_pane`, `test_fenced_separator_does_not_split`,
    `test_load_multi_agent_xprompt_invocation_stays_single_pane`, `test_load_single_cancelled_prompt_stays_single_pane`
    still pass (no frontmatter ⇒ unchanged verbatim single pane).
- `tests/ace/tui/widgets/test_prompt_input_bar_stack_xprompt_markdown.py`
  - Reword the explanatory docstrings of `test_load_stack_from_xprompt_markdown_lifts_single_body_pane` and
    `test_initial_xprompt_markdown_lifts_frontmatter_and_splits`, which cite the old "history load keeps frontmatter
    verbatim" contrast. The assertions themselves stay valid (that path is unchanged).

Add:

- Single-pane history LOAD lifts frontmatter and **shows** the panel
  (`load_stack_from_text("---\nmodel: opus\n---\ndo the thing")`).
- Multi-pane history LOAD lifts frontmatter and **shows** the panel (regression guard for defect #2:
  `load_stack_from_text("---\nmodel: opus\n---\nalpha\n---\nbeta")`).
- History LOAD of a plain prompt after a frontmatter prompt **hides** the panel again (the refresh hide-branch).
- `initial_value` construction with single-pane frontmatter lifts it and **auto-shows** the panel on mount;
  `current_prompt_text()` round-trips.
- Body-verbatim guard: a single no-frontmatter prompt with surrounding whitespace stays exactly verbatim in its pane
  (guards against accidentally routing single panes through the body-stripping `from_text`).

## Risks / considerations

- **Whitespace on re-submit** for non-canonical bodies (covered above) — accept as consistent existing `join()`
  behavior; note in the PR.
- **Stale docstrings/comments** across the stack-rendering and bar modules reference the verbatim contract; all
  identified spots are listed under "Files to change" so the documented contract and code stay in sync.
- Per the ace `AGENTS.md`, no help-popup / footer / ChangeSpec-suffix surfaces are touched by this change, so those sync
  requirements do not apply.

## Verification

- Run the focused widget suites: `tests/ace/tui/widgets/test_prompt_input_bar_stack.py`,
  `tests/ace/tui/widgets/test_prompt_input_bar_stack_xprompt_markdown.py`,
  `tests/ace/tui/widgets/test_prompt_input_bar_initial_panes.py`.
- Run `just check` (lint + mypy + tests) before completing, per repo policy (after `just install`).
- Manual: in `sase ace`, open the prompt bar, `^K` history, LOAD a prompt that carries a leading `---…---` YAML block —
  confirm the property panel appears above the input populated with the lifted fields, the body shows without the
  frontmatter block, and submitting reproduces the original prompt.
