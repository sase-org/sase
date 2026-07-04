---
create_time: 2026-07-04 12:48:07
status: wip
prompt: sdd/prompts/202607/tab_guide_modal.md
---
# Plan: Per-Tab Onboarding "Tab Guide" Modal (`,?`)

## Problem & Product Context

The PRs and Agents tabs each have a dedicated onboarding page that takes over the tab when it is empty
(`ChangeSpecOnboarding`, `AgentOnboarding`). Two gaps remain:

1. The **AXE tab has no onboarding page at all** — and it never will as an empty-state takeover, because the tab always
   has content (lumberjacks, chops, background commands).
2. Once a user has PRs/agents, the existing onboarding pages become **unreachable** — you would have to delete all your
   work to see them again.

This plan adds a **"Tab Guide"** — a popup modal, opened with the leader-mode keymap **`,?`** from any tab, that shows
the current tab's onboarding guide on demand:

- On the **AXE tab** it shows a brand-new AXE guide (new content, designed below).
- On the **PRs / Agents tabs** it shows the same content as their existing onboarding pages, so those guides are always
  one keystroke away even when the tabs are full.
- The keymap is **advertised prominently on the AXE tab** (persistent hint in the top info bar), in the LEADER footer
  hint bar, in the per-tab help modal, and on the existing onboarding pages.

Scope note: this is purely presentation-layer Textual work (widgets, keymaps, modal, CSS). Per the Rust core backend
boundary, nothing here belongs in `sase-core` — no core changes are needed.

## UX Design

### The `,?` keymap

- New leader-mode key `tab_guide: "question_mark"`:
  - `src/sase/default_config.yml` under `ace.keymaps.modes.leader_mode.keys`.
  - Matching default in `LeaderModeKeymaps.keys` (`src/sase/ace/tui/keymaps/types.py:426`).
- `question_mark` is already a valid key name (`_KEY_DISPLAY` maps it to `?`, `keymaps/types.py:146`) and does not
  conflict with the app-level `?` (help modal): leader mode intercepts keys at the app `on_key` level before bindings
  are consulted.
- The mnemonic is deliberate: `?` alone = "what can I press here" (help), `,?` = "what is this tab and how do I use it"
  (guide). The two modals cross-reference each other.
- Works identically on all three tabs; the modal renders whichever guide matches `app.current_tab`.

### The Tab Guide modal

New `TabGuideModal(ModalScreen[None])` in `src/sase/ace/tui/modals/tab_guide_modal.py`:

- **Layout**: centered (`align: center middle`), container ~96 cols wide (the onboarding cards are `max-width: 90` +
  padding), `max-height: 90%`, `background: $surface`, rounded border. The body is a fresh instance of the tab's
  onboarding widget — these are already `VerticalScroll` containers, so long guides scroll naturally inside the modal.
- **Per-tab accent identity** (matches the tab colors already used in `AgentOnboarding._TAB_ROWS`):
  - PRs: teal `#00D7AF`, border title `PRs Guide`
  - Agents: blue `#87D7FF`, border title `Agents Guide`
  - AXE: red `#FF5F5F`, border title `AXE Guide` The border + border-title color takes the tab accent (via a per-tab CSS
    class such as `.-tab-axe` on the container); a dim border subtitle reads `esc closes`.
- **Content reuse, not duplication**: the modal composes a _new instance_ of `ChangeSpecOnboarding` / `AgentOnboarding`
  / `AxeOnboarding` (the tab-takeover instances stay where they are on the main screen; a modal screen is a separate DOM
  tree so the reused element IDs and shared `styles.tcss` card rules apply cleanly). The modal calls
  `set_keymap_registry(app registry)` so every keycap reflects the user's actual bindings, and for `AgentOnboarding`
  forwards the app's current launch-target/plugins state (the same values `_sync_agents_onboarding` in
  `actions/agents/_display_detail.py` uses) so the modal never shows stale "install a plugin" advice.
- **Context-aware footer copy**: the onboarding widgets grow a `context` knob (`"tab"` default | `"modal"`). The
  empty-state footers ("Your first ChangeSpec replaces this guide…") only make sense as a takeover; in the modal every
  widget instead renders one shared footer line: `esc closes · ,? reopens this guide on any tab`.
- **Dismissal**: `escape`, `q`, and `?` all close (mirrors `HelpModal.BINDINGS`); `ctrl+d`/`ctrl+u` half-page scroll
  like the help modal. Opening is idempotent — the leader dispatch guards against pushing a second guide if one is
  already the top screen.

### The new AXE guide (`AxeOnboarding`)

New widget `src/sase/ace/tui/widgets/axe_onboarding.py`, mirroring the architecture of its siblings (hero + bordered
cards + footer, a static `render_content(registry) -> dict[selector, Text]` for app-free tests, `set_keymap_registry`,
shared `_onboarding_common.append_keycap` / `append_section_heading` helpers). Accent: `#FF5F5F` (the AXE tab color);
keycaps keep the shared teal style so keycaps look identical across all guides.

All keys below are rendered from the live keymap registry via `key_display_name` (never hardcoded); defaults shown for
illustration:

1. **Hero** — `*  Automation, always on  *` with dim-red subtitle "Axe is the daemon that keeps your hooks, mentors &
   workflows moving."
2. **Card "What is Axe?"** — Axe is sase's background daemon, started automatically with `sase ace`. Each cycle it
   completes finished hooks, starts stale ones, launches mentor workflows, polls pending checks, and cleans up zombie
   state — your PRs keep moving while you focus elsewhere. Keycaps: `x` start/stop axe · `Q` quit/restart menu (registry
   fields: `kill_agent`, `stop_axe_and_quit`). Closes with a one-line anatomy of the status bar (Runtime · Cycles ·
   Hooks/Agents runner slots).
3. **Card "Lumberjacks own chops"** — a _lumberjack_ is a scheduled worker that wakes on an interval; each owns _chops_,
   the individual automation tasks it runs every cycle. The lumberjack/chop names in the card reuse the sidebar's
   gold/name styles (`_axe_dashboard_render.LJ_NAME_STYLE` / `CHOP_NAME_STYLE`) so the guide visually echoes the sidebar
   taxonomy. Keycaps: `j`/`k` move through the sidebar · `r` run the selected chop now · next/prev chop run · `E` edit
   chop output (registry fields: `next_changespec` / `prev_changespec`, `run_workflow`, `next_agent_file` /
   `prev_agent_file`, `edit_spec`). Notes that every chop keeps run history — status, duration, and captured output land
   in this dashboard.
4. **Card "Background commands"** — `!!` runs any shell command in a background slot with live output streaming into the
   dashboard; `x` kills a running command, `X` clears output, `r` re-runs a finished one (registry fields: bang-mode
   `run_cmd`, `kill_agent`, `open_agent_cleanup_panel`, `run_workflow`).
5. **Card "Learn more"** — `?` opens the full keybinding reference for this tab; docs link `https://sase.sh`; and the
   punchline: this guide is `,?`, and it works on **every** tab.
6. **Footer** — "Press `,` `?` on any tab to open that tab's guide."

`AxeOnboarding` is modal-only for now (the AXE tab never shows an empty-state takeover), but it is built exactly like
its siblings so it could be mounted anywhere later.

### Advertising `,?`

Four surfaces, one per discovery path:

1. **AXE tab top info bar (the prominent one)** — `AxeInfoPanel` (`widgets/axe_info_panel.py`) renders a persistent
   trailing hint in _every_ mode (loading, axe, lumberjack, chop, bgcmd): a teal keycap `, ?` followed by dim "tab
   guide". This bar is always visible on the AXE tab and currently has spare room, so the hint is prominent without
   stealing space from data. The panel gets the rendered key display from the app when the keymap registry is
   loaded/reloaded (defaulting to `,?`), so custom bindings show correctly. Note: the keybinding footer is intentionally
   _not_ used — per the footer convention (`src/sase/ace/AGENTS.md`), the always-available `,?` is a global action and
   belongs in the help modal, not the footer's conditional-bindings area.
2. **LEADER footer hint bar** — pressing `,` already repaints the footer with available leader keys
   (`update_leader_bindings`, `widgets/_keybinding_modes.py:159`). Append `? → tab guide` for all tabs so the keymap is
   discoverable the moment someone enters leader mode.
3. **Help modal** — add `,? Tab guide` to the "Leader Mode (,)" section of all three per-tab binding builders
   (`modals/help_modal/axe_bindings.py`, `agents_bindings.py`, `changespecs_bindings.py`), keeping the help popup in
   sync per the AGENTS.md requirement.
4. **The existing onboarding pages** — the PRs guide's "Learn more" card and the Agents guide's "Get more help" card
   each gain one line: "reopen this guide anytime with `,?` — it works on every tab." This teaches users, while they
   still see the empty-state page, that the content never becomes unreachable.

## Technical Design

### Leader dispatch wiring

Follow the established pattern in `actions/agent_workflow/_leader_mode.py`:

- Add an `if key == leader_keys["tab_guide"]:` branch to `_dispatch_leader_key` that remembers the key (so `,,` repeat
  works), calls a new `_open_tab_guide_modal()` helper, and refreshes the tab.
- `_open_tab_guide_modal()` is modeled on `_open_models_panel` (line 258): builds
  `TabGuideModal(current_tab=self.current_tab, ...)` with the registry + agents-tab state and `push_screen`s it. It is
  tab-agnostic — no per-tab conditional in the dispatch, matching how `models_panel` behaves.

### Files touched (summary)

| Area             | File                                                                          | Change                                                                                   |
| ---------------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Keymap defaults  | `src/sase/default_config.yml`                                                 | `tab_guide: "question_mark"` under `leader_mode.keys`                                    |
| Keymap types     | `src/sase/ace/tui/keymaps/types.py`                                           | same default in `LeaderModeKeymaps`                                                      |
| Dispatch         | `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`                     | new branch + `_open_tab_guide_modal`                                                     |
| New modal        | `src/sase/ace/tui/modals/tab_guide_modal.py` (+ `modals/__init__.py` export)  | `TabGuideModal`                                                                          |
| New widget       | `src/sase/ace/tui/widgets/axe_onboarding.py` (+ `widgets/__init__.py` export) | `AxeOnboarding`                                                                          |
| Existing widgets | `widgets/changespec_onboarding.py`, `widgets/agent_onboarding.py`             | `context` knob for modal footer; `,?` line in help/learn cards                           |
| AXE hint         | `src/sase/ace/tui/widgets/axe_info_panel.py`                                  | persistent `,? tab guide` hint                                                           |
| Footer hints     | `src/sase/ace/tui/widgets/_keybinding_modes.py`                               | `tab guide` entry in `update_leader_bindings`                                            |
| Help modal       | `modals/help_modal/{axe,agents,changespecs}_bindings.py`                      | `,? Tab guide` rows                                                                      |
| Styling          | `src/sase/ace/tui/styles.tcss`                                                | `TabGuideModal` + `#tab-guide-container` + per-tab accent classes; AXE guide card styles |

### Reliability details

- All key displays flow from `KeymapRegistry` — user rebinds of the leader prefix or the `tab_guide` subkey propagate to
  the info-bar hint, the footer, the help modal, and every guide keycap.
- Guard against double-push (check the top of the screen stack before `push_screen`), the same concern
  `action_show_help` handles for the help modal.
- The modal instantiates fresh widgets each open — no shared mutable widget state with the tab-takeover instances, and
  no lifecycle coupling (dismiss simply drops the screen).
- `AgentOnboarding`'s dynamic cards (launch targets / plugins) receive the app's current cached values at open time, so
  the modal always reflects reality.

## Testing

Follow the two existing tiers:

1. **App-free unit tests**
   - `tests/ace/tui/widgets/test_axe_onboarding.py` — mirror `test_changespec_onboarding.py`: assert `render_content()`
     copy, keycap presence, and that keymap overrides (e.g. rebinding `run_workflow`) propagate into the rendered text.
   - Extend `tests/ace/tui/test_leader_keymap_dispatch.py` + `_leader_keymap_helpers.py` with a `tab_guide` counter:
     `,?` dispatches on every tab, `,,` repeats it, and a custom-config rebind of the subkey still dispatches.
   - Extend `tests/ace/tui/test_leader_keybinding_footer.py` — LEADER footer includes `? tab guide` on all tabs.
   - Modal-footer context test — onboarding widgets render the modal footer (not the empty-state footer) when
     `context="modal"`.
   - Help-modal bindings tests — the new row appears in each tab's Leader Mode section.
2. **Pilot + PNG visual snapshots** (`tests/ace/tui/visual/`, following `test_ace_png_snapshots_models_panel.py`: push
   modal → `expect_modal` → `wait_for_visual_idle` → `assert_page_png`)
   - New snapshots: the Tab Guide modal on the AXE tab (the flagship new content) and on the Agents tab (proves content
     reuse + modal footer).
   - Existing AXE-tab snapshots will change because of the new info-bar hint — regenerate intentionally with
     `--sase-update-visual-snapshots` and review the diffs.

Run `just install` then `just check` before finishing (per repo policy), and `just test-visual` for the snapshot suite.

## Implementation Phases

1. **Keymap plumbing** — config default + `LeaderModeKeymaps` + dispatch branch (modal stubbed) + LEADER footer entry +
   dispatch/footer unit tests.
2. **`AxeOnboarding` widget** — content, styles, exports, unit tests.
3. **`TabGuideModal`** — modal, per-tab accents, content reuse with `context="modal"` footers, agents-state forwarding,
   dismissal bindings, styles, pilot tests.
4. **Advertising** — `AxeInfoPanel` hint, help-modal rows, `,?` mentions on the existing onboarding pages, PNG snapshots
   (new + intentional regenerations).

## Out of Scope

- An empty-state takeover for the AXE tab (it can never be empty).
- Any change to when the existing PRs/Agents takeovers appear.
- Rust core (`sase-core`) — presentation-only feature.
