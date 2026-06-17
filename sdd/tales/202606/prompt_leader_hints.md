---
create_time: 2026-06-17 11:48:16
status: done
prompt: sdd/prompts/202606/prompt_leader_hints.md
---
# Plan: Leader-key hints for the prompt input widget

## Summary

When a user presses `,` (the comma **leader**) while in **normal mode** inside the prompt input widget, pop up a small,
beautiful "which-key" style hint panel listing the leader keymaps that are available right now (`,s`, `,S`, `,P`, `,f`).
The panel appears the instant `,` is pressed, sits directly above the prompt where the user's eyes already are, and
disappears the moment they press the second key or `Esc`. It is fully context-aware: it only lists keymaps that will
actually do something in the current mode / stack / stash state.

This closes a real discoverability gap (see Background) without changing any existing keybinding behavior.

## Background & motivation

There are **two independent leader systems** in the TUI, both triggered by `,`:

1. **App-level leader** — active when focus is on the changespecs/agents/axe panes. Pressing `,` runs
   `action_start_leader_mode` (`bindings.py:115`), which renders the available leader keymaps into the bottom
   `#keybinding-footer` bar (`_keybinding_modes.py::update_leader_bindings`). This surface **already gives users a
   which-key style hint.**

2. **Prompt-bar leader** — active only in **normal mode** inside the prompt input widget. The `PromptTextArea`
   intercepts `,` before it can bubble to the app binding (`_vim_normal_motions.py:261-271`), sets
   `self._pending_keys = ","`, and the next key is dispatched by `_handle_stack_leader_key`
   (`_vim_normal_pending.py:218-237`) to the prompt bar's own actions. **This surface has _no_ hint panel today** — the
   only clue is a terse, easily-missed chip in the prompt's border subtitle (`[,s ,S] stash  [,f] fm`), and even that
   only appears for multi-pane stacks.

So the prompt-bar leader is the discoverability gap. This plan adds a hint surface for it that is consistent with — but
visually distinct from — the existing app-level footer hints.

### Leader keymaps in scope (current behavior, unchanged by this plan)

Dispatched in `_handle_stack_leader_key` → prompt-bar methods in `_prompt_input_bar_stack_actions.py`:

| Chord | Action method               | What it does                         | When it is useful               |
| ----- | --------------------------- | ------------------------------------ | ------------------------------- |
| `,s`  | `stash_active_pane()`       | Stash the active pane's draft        | `prompt` mode, pane has text    |
| `,S`  | `stash_all_panes()`         | Stash every non-empty pane           | `prompt` mode, multi-pane stack |
| `,P`  | `request_restore_stash()`   | Open the stash restore picker        | A restorable stash exists       |
| `,f`  | `focus_frontmatter_panel()` | Reveal / focus the frontmatter panel | `prompt` mode                   |

These chords are **hardcoded** (not in `default_config.yml`), so the hint labels are hardcoded too; no keymap-config
changes are required.

## Design (this is the part I'm leading on — the goal is "beautiful")

### Visual

A single bordered panel, mounted **directly above the prompt stack** (closest to the cursor), full width like the
existing completion/frontmatter panels. It uses the help-modal's established color palette for cohesion, but a
`round $accent` border to read as a soft, transient overlay tied to the prompt (the prompt bar itself uses
`solid $accent`).

Multi-pane prompt:

```
╭─ leader ──────────────────────────────────────────────╮
│  ,s   stash this pane                                  │
│  ,S   stash all panes                                  │
│  ,P   restore stash…                                   │
│  ,f   toggle frontmatter                               │
╰────────────────────────────────────────────────────────╯
┌─ Prompt · 2 agents ────────────────────────────────────┐
│ <cursor is here>                                       │
└─────────────────────────────────────────────────────────┘
```

Single-pane prompt with nothing stashed (`,S` and `,P` hidden because they would no-op):

```
╭─ leader ──────────────────────────────────────────────╮
│  ,s   stash this draft                                 │
│  ,f   toggle frontmatter                               │
╰────────────────────────────────────────────────────────╯
```

Per-row Rich styling (mirrors `help_modal`'s key styling so the whole app feels of-a-piece):

- two-space indent
- the leader `,` rendered dim (`dim #87D7FF`)
- the next key (`s`/`S`/`P`/`f`) in **bold teal** (`bold #00D7AF`) — same as help-modal/footer keys
- aligned gutter, then the description in normal `$text`
- the `,s`/`,f` wording adapts to context ("this pane" vs "this draft").

Border `title=" leader "`, `subtitle="[esc] cancel"`. Empty/no-op states never render the panel.

### Interaction

- **Appears instantly** when `,` is pressed in normal mode — no delay timer. This matches the prompt-bar's existing
  pending model, which has **no timeout** (the pending state persists until the next key or `Esc`). Instant feedback is
  the right call for an explicitly-pressed leader.
- **Dismisses** the moment the leader resolves: pressing a valid key (`s`/`S`/`P`/`f`) runs the action and hides the
  panel; pressing `Esc` clears pending and hides the panel; pressing any other key clears pending (a swallowed no-op
  today) and hides the panel.
- The existing border-subtitle pending indicator (which currently appends the literal `,` while pending) continues to
  work unchanged; the panel is purely additive.

### Why a panel and not a modal

The app already establishes the pattern of **transient panels mounted inside the prompt bar** (`#prompt-completion`,
`#frontmatter-panel`): created hidden, toggled via the `hidden` CSS class, and folded into the bar's auto-grow height
calc. A leader hint is exactly this kind of lightweight, inline, dismiss-on-keystroke surface — a `ModalScreen` would
steal focus and feel heavy. Reusing the panel pattern keeps it consistent and cheap.

## Technical design (high level)

### 1. Single source of truth for the leader keymaps

Today the dispatch switch lives in `PromptTextArea._handle_stack_leader_key`, while the labels live (partially) in the
border-subtitle strings. To keep the hint panel from drifting out of sync with the actual dispatch, **move the canonical
leader table onto the prompt bar**:

- Add a small declarative table on `PromptInputBar` (in `_prompt_input_bar_stack_actions.py`) describing each leader
  entry: the second key, the bound action method, the human label, and an **availability predicate** (`prompt` mode?
  multi-pane? pane has text? stash exists?).
- Derive two things from that one table:
  - `dispatch_leader_key(key)` — performs the action (the dispatcher `_handle_stack_leader_key` becomes a thin delegate
    to this).
  - `leader_hint_entries()` — returns the entries that are currently _available_, for rendering.

This means adding/changing a leader keymap later updates the hint automatically.

### 2. Trigger / show-hide hook

`_update_count_display()` (`_vim_normal_state.py:76`) is the single chokepoint already called on every pending-state
change (it has a handle to the bar via `_find_prompt_bar()` and currently refreshes the border subtitle). Hook the panel
there:

- when `self._pending_keys == ","` → `bar.show_leader_hints()`
- otherwise → `bar.hide_leader_hints()`

Guard both with an idempotent `_leader_hints_visible` flag so the height isn't thrashed on unrelated pending updates
(operators, counts, `f`/`t`, surround, etc.).

`show_leader_hints()` renders `leader_hint_entries()`; if that list is empty (e.g. feedback / approve-prompt bars, where
every leader action is a no-op) it simply does **not** open the panel.

### 3. The panel widget + height integration

- Add `yield Static("", id="prompt-leader-hints", classes="hidden")` to `PromptInputBar.compose`, positioned just above
  `#prompt-stack` (so order is completion → frontmatter → leader-hints → stack, putting the hints nearest the cursor).
- Mirror the completion-panel machinery: `_leader_hints_visible: bool` and `_leader_hints_line_count: int` state, set in
  show/hide, and folded into `_update_height()` (`_prompt_input_bar_stack_rendering.py:407`) alongside `completion_rows`
  / `frontmatter_rows` in both the single-pane and multi-pane branches.
- New TCSS rule in `styles.tcss` next to the completion-panel rules:
  `PromptInputBar #prompt-leader-hints { round $accent border; background: $panel; height: auto; max-height: 8; ... }`
  plus the `.hidden { display: none }` companion.

### 4. Context-awareness details

- `,s`/`,S`/`,f` are `prompt`-mode only (the actions early-return in other modes), so the predicates hide them for
  feedback / approve-prompt bars.
- `,S` only shows when the stack has more than one pane (single-pane "stash all" == "stash this").
- `,P` only shows when a restorable stash exists. The app already computes this via `_has_stashed_prompts()`
  (`_prompt_bar_stash.py:254`); the bar will consult `self.app` defensively (try/except → treat as "no stash") so the
  panel never raises and degrades gracefully to hiding `,P` if the app surface is unavailable.
- `,s` label switches between "stash this pane" (multi-pane) and "stash this draft" (single pane).

## Files to change

- `src/sase/ace/tui/widgets/_prompt_input_bar_stack_actions.py` — leader table, `dispatch_leader_key`,
  `leader_hint_entries`, availability predicates.
- `src/sase/ace/tui/widgets/_prompt_input_bar_completion.py` **or** a small new `_prompt_input_bar_leader_hints.py`
  mixin — `show_leader_hints` / `hide_leader_hints` rendering (Rich `Text`), `_leader_hints_visible` /
  `_leader_hints_line_count` state. (Leaning toward a new focused mixin so the completion module stays single-purpose.)
- `src/sase/ace/tui/widgets/prompt_input_bar.py` — `compose` adds the hidden panel; wire the new mixin / state into
  `__init__`.
- `src/sase/ace/tui/widgets/_vim_normal_pending.py` — `_handle_stack_leader_key` delegates to `bar.dispatch_leader_key`.
- `src/sase/ace/tui/widgets/_vim_normal_state.py` — `_update_count_display` shows/hides the panel based on
  `self._pending_keys == ","`.
- `src/sase/ace/tui/widgets/_prompt_input_bar_stack_rendering.py` — `_update_height` accounts for the leader-hints rows.
- `src/sase/ace/tui/styles.tcss` — `#prompt-leader-hints` styling + `.hidden`.

## Testing

- **Unit / behavior** (alongside `test_leader_keymap_dispatch.py`, reusing `_leader_keymap_helpers.py`):
  - pressing `,` in normal mode shows the panel; `leader_hint_entries()` matches expectation for single-pane,
    multi-pane, feedback, and "stash exists" states.
  - pressing the second key runs the action **and** hides the panel; `Esc` hides; an unknown key hides.
  - the panel never opens when there are no available entries (feedback / approve-prompt).
  - `dispatch_leader_key` parity: every key the old switch handled still routes to the same action (guards against the
    refactor changing behavior).
- **Visual PNG snapshot** (the suite in `tests/ace/tui/visual/`, modeled on the existing
  `prompt_stack_completion_panel_120x40.png` golden): a new `prompt_stack_leader_hints_*` golden capturing the panel
  open over a multi-pane prompt, accepted via `--sase-update-visual-snapshots`.
- `just check` (after `just install`) before handing back.

## Non-goals / out of scope

- No changes to which leader keymaps exist or what they do.
- Not making the prompt-bar leader keymaps configurable in `default_config.yml`.
- Not touching the app-level leader footer.
- No auto-dismiss timer (deliberately instant; can revisit if flicker is ever reported).

## Cross-cutting checks

- **Rust core boundary**: this is presentation-only (transient Textual panel, keybinding hinting, layout, rendering).
  Per `memory/short/rust_core_backend_boundary.md` it stays entirely in this Python repo — no `sase-core`
  wire/API/binding changes.
- **Help popup sync** (`src/sase/ace/AGENTS.md`): verify whether the `?` help modal lists the prompt-bar leader chords;
  if it does, keep wording consistent with the new panel. (The panel itself becomes the primary in-context documentation
  for these keys.)
- **Keymap config** (`memory/short/gotchas.md`): no `default_config.yml` change needed since these chords are hardcoded,
  not config-driven.
