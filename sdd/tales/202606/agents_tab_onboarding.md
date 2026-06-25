---
create_time: 2026-06-25 15:21:42
status: done
prompt: sdd/prompts/202606/agents_tab_onboarding.md
---
# Plan: Agents-tab Onboarding View

## Summary

Add a polished **onboarding view** that takes over the right-hand pane of the **Agents** tab in the `sase ace` TUI
**whenever there are no agents to show**. When the user has zero agents, the right side is currently a near-empty "No
agent selected" panel — wasted space and a dead end for a new user. We replace that with a welcoming, beautiful,
self-explanatory guide that teaches the user how to:

1. **Launch their first agent** (the keys that open the agent prompt).
2. **Understand the three tabs** (PRs / Agents / AXE) and how to switch between them.
3. **Get more help** — the `?` help pop-up, the `:` command palette, and the documentation website **https://sase.sh**
   (rendered as a clickable link).

The view appears automatically when the Agents list is empty and disappears the instant the user's first agent shows up
— no manual toggling, no new keybinding.

## Goals & Non-goals

**Goals**

- Intuitive: zero new keybindings; it just appears in the obvious place at the obvious time.
- Reliable: driven by a single, well-tested predicate funneled through the existing detail-refresh choke points; correct
  across load, refilter, kill/dismiss, and tab-switch paths.
- Beautiful: matches the existing ACE aesthetic (gold `✦` accents, cyan section headers, teal "keycaps", framed cards)
  and stays clean at any terminal width.
- Accurate & self-maintaining: key hints are pulled from the live keymap registry, so they stay correct even if the user
  has rebound keys, and they satisfy the repo's "keep help docs in sync" rule.

**Non-goals**

- No changes to how agents are actually launched, or to any other tab.
- No persistent "dismiss forever" state — visibility is purely a function of "are there agents?".
- No replacement of the left-hand Agents list (which keeps its own loading/empty behavior).
- No backend/Rust changes (see "Architecture boundary" below).

## Architecture boundary (Rust core)

Per `memory/rust_core_backend_boundary.md`, this is **presentation-only**: a static, TUI-specific informational widget
plus a visibility toggle over Textual widget state. The content is copy _about the TUI itself_ (its tabs, its
keybindings), and the trigger is local Textual view state. It does not implement shared domain behavior another frontend
would need to mirror. **No `sase-core` changes.** All work is Python/Textual in the `sase` repo.

## Where it lives in the UI

The Agents tab is composed in `src/sase/ace/tui/app.py` (`compose`, ~lines 288–294):

```
#agents-view
├─ AgentInfoPanel  (#agent-info-panel)          ← top metrics strip
└─ #agents-content (Horizontal)
   ├─ #agent-list-container  → AgentList         ← LEFT  (the agent list)
   └─ #agent-detail-container → AgentDetail       ← RIGHT (detail pane — what we overlay)
```

We add a **sibling** of `AgentDetail` inside `#agent-detail-container`:

```
#agent-detail-container (width: 1fr)
├─ AgentDetail        (#agent-detail-panel)              ← shown when agents exist
└─ AgentOnboarding    (#agent-onboarding-panel, hidden)  ← shown when zero agents
```

Only one of the two is visible at a time, controlled by a `.hidden` class (`display: none`). Because the onboarding
panel lives _inside_ `#agents-view`, it is automatically hidden along with the whole Agents tab when the user switches
tabs — we only ever manage its visibility _relative to_ `AgentDetail`.

## Trigger logic (the key design decision)

A single predicate decides whether to show onboarding. It is intentionally conservative so the view is genuinely helpful
and never misleading:

```
show onboarding  ⇔  first agent load has completed
                 AND no agent search query is active
                 AND there are zero agents at all
```

Concretely (helper on the Agents display mixin):

- **Loaded gate** — `self._agents_first_load_done` (set in `actions/agents/_loading_apply.py`). Prevents an onboarding
  flash during the brief initial-load window, where the left list already shows its own loading indicator.
- **No-query gate** — `self._agent_search_query` is empty. See "Design decision" below.
- **Zero-agents signal** — the cached unfiltered list `self._agents_with_children` is empty. This is the cleanest "there
  are truly no agents" signal: it is non-empty whenever agents exist but are merely filtered out or are
  hidden-while-starting, so those cases correctly keep the normal detail pane.

### Design decision: empty-because-no-agents vs. empty-because-filtered

The request says "only when there are no agents currently visible." There are two ways the right pane can be agent-less:

1. **No agents exist at all** (fresh user, or all agents archived/dismissed) — the cold-start case.
2. **Agents exist but a search query filtered them all out.**

I recommend showing onboarding for **case 1 only** (the `no-query` gate). Showing "here's how to launch your first
agent" when the user clearly _has_ agents and just typed a filter would read as a bug ("where did my agents go?"). Case
1 is exactly the first-run / empty-inbox moment where onboarding is valuable and never wrong.

This decision is isolated in one predicate method, so if you'd prefer the literal "empty for any reason" reading, it's a
one-line change (drop the query gate). The filtered-to-empty case keeps today's behavior (the existing minimal empty
detail panel). **Flag for review.**

## Where the toggle is applied

Every Agents-tab render path that decides "show detail vs. show empty" already funnels through two methods in
`actions/agents/_display_detail.py`:

- `_apply_agent_detail_immediate()` — the fast j/k header refresh.
- `_apply_agent_detail_update(...)` — the full/debounced detail update (also reached from the incremental refresh path
  in `actions/agents/_display.py`).

Both currently branch on `current_agent is None → agent_detail.show_empty()`. We introduce one helper —
`_sync_agents_onboarding()` — called at the top of both. It:

1. Queries the onboarding panel and `AgentDetail` (guard `NoMatches`).
2. Evaluates the predicate.
3. Toggles the `.hidden` class on each so exactly one is visible, and (when showing) tells the onboarding panel to
   (re)render with the current keymap registry.
4. Returns a boolean; when onboarding is active, the callers skip the now-hidden `AgentDetail` work (no wasted
   `show_empty()`/footer churn).

This single choke point covers initial load, refilter, kill/dismiss, grouping changes, and the incremental diff path.
Tab-switch into Agents already triggers a display refresh, so it's covered too; we'll verify and, if needed, call the
helper from the tab-switch handler as a belt-and-braces measure. The footer is set to its normal "no selection" state
while onboarding is visible.

## The `AgentOnboarding` widget (content & visual design)

New file `src/sase/ace/tui/widgets/agent_onboarding.py`, exported from `src/sase/ace/tui/widgets/__init__.py`. A
`VerticalScroll` (so content is reachable on short terminals) containing a stack of `Static` "cards". A single
`render(keymaps)` method rebuilds the cards from the keymap registry.

**Key hints are data-driven, not hardcoded.** We reuse `keymaps.key_display_name(...)` and the live registry
(`app._keymap_registry`) — the same source the help modal uses — so every key shown is the user's actual configured
binding:

| Hint                | Source field                          | Default shown       |
| ------------------- | ------------------------------------- | ------------------- |
| Launch (prompt)     | `km.app.start_agent_home`             | `Space`             |
| Launch (pick proj.) | `km.app.start_custom_agent`           | `+`                 |
| Switch tabs         | `km.app.next_tab` / `km.app.prev_tab` | `Tab` / `Shift+Tab` |
| Help pop-up         | `km.app.show_help`                    | `?`                 |
| Command palette     | `km.app.open_command_palette`         | `:` / `;`           |

### Layout (top → bottom)

1. **Hero** — centered wordmark, matching the help modal's title treatment:

   ```
              ✦  Welcome to sase ace  ✦
        Structured Agentic Software Engineering
   ```

   Gold `✦` (`#FFD700`), bold white title, dim cyan (`#87D7FF`) subtitle.

2. **Card ① Launch your first agent** — framed card (Textual `border: round`, `border_title`). Explains, with teal
   keycaps:
   - Press **`<Space>`** to open the prompt bar and dispatch an agent in your home workspace.
   - Press **`+`** to pick a project (or CL) first, then write the prompt.
   - (Footnote) These work from any tab; you can also start ACE from your shell with `sase ace`.

3. **Card ② The three tabs** — framed card. One row per tab, each with a colored name badge and a one-line description
   (copy aligned with `docs/ace.md`), then a "switch with `Tab` / `Shift+Tab`" line:
   - **PRs** — Browse and act on ChangeSpecs (CL/PR-sized units of work): commits, hooks, mentors, and status.
   - **Agents** — Watch running and completed agents; inspect their prompts, diffs, tools, and artifacts. _(you are
     here)_
   - **AXE** — Monitor the Axe daemon and its background automation (hooks, chops, mentors, workflows).

4. **Card ③ Get more help** — framed card, three rows:
   - Press **`?`** — open the **help pop-up** (every keybinding for the current tab).
   - Press **`:`** — open the **command palette** (fuzzy-search and run any command).
   - Visit **https://sase.sh** — the full documentation (rendered as a clickable OSC-8 hyperlink via Rich `Text`
     `style="link https://sase.sh"`, with the literal URL also shown for terminals without link support).

5. **Footer hint** — dim, centered: "Agents you launch appear in the list on the left — this guide makes way as soon as
   your first one shows up."

### Why framed "cards" instead of fixed-width ASCII boxes

The help modal uses fixed 57-char boxes because it lives in a fixed-width modal. The Agents detail pane is fluid
(`width: 1fr`), so hardcoded box widths would break on narrow/wide terminals. Textual container **borders auto-fit the
available width**, giving the same framed look while staying crisp at every size — more reliable _and_ more beautiful
here. Numbered circled glyphs (①②③) mark the steps; colors come from the established ACE palette
(gold/cyan/teal/purple).

### Styling

Add a small block to `src/sase/ace/tui/styles.tcss`:

- `#agent-onboarding-panel { width: 100%; height: 1fr; }` and `.hidden { display: none; }` parity with
  `#agent-detail-panel`.
- Card `Static`s: `border: round $secondary; padding: 0 1; margin: ...; border-title-color`.
- Hero/footer: no border, centered (`text-align: center` / `content-align`).
- Default `AgentOnboarding` starts hidden (compose with `classes="hidden"`), revealed only by the toggle, so the very
  first paint never shows it before the predicate runs.

## Files to change

**New**

- `src/sase/ace/tui/widgets/agent_onboarding.py` — the widget + content builder.
- `tests/ace/tui/widgets/test_agent_onboarding.py` — content/unit tests.
- `tests/ace/tui/visual/test_ace_png_snapshots_agents_onboarding.py` — visual snapshot(s).
- New golden PNG(s) under `tests/ace/tui/visual/snapshots/png/`.

**Edited**

- `src/sase/ace/tui/widgets/__init__.py` — export `AgentOnboarding`.
- `src/sase/ace/tui/app.py` — yield `AgentOnboarding` in `#agent-detail-container`.
- `src/sase/ace/tui/styles.tcss` — onboarding panel + card styling.
- `src/sase/ace/tui/actions/agents/_display_detail.py` — add `_sync_agents_onboarding()` and the empty-tab predicate;
  call it from both detail-apply methods.
- (If verification shows tab-switch doesn't already refresh) the agents tab-switch handler — call the sync helper.

## Testing strategy

- **Predicate unit tests** (pure, no UI): loaded + zero agents + no query → show; with agents → hide; not loaded → hide;
  query active → hide. Covers the four branches and the filtered-vs-truly-empty distinction.
- **Widget content tests** (`AgentOnboarding.render` against a `KeymapRegistry`): asserts the three tab names appear,
  the `https://sase.sh` link is present, and that hints reflect the registry (e.g. swap `show_help` to a custom key and
  confirm the rendered hint follows — proving no hardcoding / no doc drift).
- **Pilot/integration test** on the Agents tab via `AcePage`/`patch_startup_loaders`:
  - Start with `agents=[]` → switch to Agents tab → assert onboarding panel visible and `#agent-detail-panel` hidden.
  - Start with agents present → assert onboarding hidden, detail visible.
  - (Optional) start empty, inject an agent + refresh → assert onboarding flips to hidden.
- **Visual PNG snapshot** (the repo's ACE visual suite, `just test-visual`): render the Agents tab with `agents=[]` and
  snapshot the onboarding view at the standard size — this is the regression guard for "beautiful" and pins the layout.
  Accept the new golden with `--sase-update-visual-snapshots`.
- Run `just check` before completion (note: `just install` first, per the ephemeral-workspace rule).

## Risks & mitigations

- **Flicker during startup** → gated behind `_agents_first_load_done`; widget composes hidden.
- **Stale keys after rebinding** → hints rendered from the live registry on each show; covered by a test that rebinds a
  key.
- **Narrow terminals** → fluid Textual borders + `VerticalScroll`; no fixed-width ASCII art.
- **Perf on hot j/k path** → the sync helper is a cheap class-check + boolean predicate over in-memory state; when
  agents exist it early-returns before any rendering.
- **Docs/help-sync rule** (`src/sase/ace/AGENTS.md`) → because copy describes tabs and help entry points, we keep it
  consistent with `docs/ace.md` and the help modal; the rebinding test guards against key drift.

## Open question for review

1. **Filtered-empty behavior** — confirm the recommended "onboarding only when no agents exist at all (no active query)"
   vs. the literal "empty list for any reason." (One-line toggle either way.)
