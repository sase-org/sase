---
create_time: 2026-07-06 19:33:03
status: done
prompt: sdd/prompts/202607/tab_onboarding_quickstart.md
---
# Plan: Tab Quick-Start Onboarding Redesign (Agents + PRs tabs)

## Problem & Goals

The Agents and PRs tabs each show a rich, multi-card onboarding page when there is nothing else interesting to display.
Three problems to solve:

1. **The current guide content is valuable but too heavy for an empty-state page.** It should be preserved verbatim
   behind the existing `,?` (leader `tab_guide`) pop-up modal, which already renders the same widgets today.
2. **The empty-state pages should become lightweight "quick starts":** a 1–2 sentence summary of what the tab is about,
   followed by the 5–7 most valuable _global_ keymaps for someone getting started (launching an agent, configuring sase,
   installing plugins, getting help, etc.). The two tabs' pages are identical except for the tab summary.
3. **The PRs-tab visibility logic is broken.** Today onboarding only shows when _zero ChangeSpecs exist anywhere AND
   zero saved queries exist_, and it takes over the whole tab (hiding the search query panel). Instead: the search query
   panel is **always** visible up top, and whenever the current query matches nothing (empty filtered list — for any
   reason), the quick-start page fills the results area below it.

Design goals: intuitive (the page explains itself in context), reliable (visibility driven by one dead-simple
predicate + one CSS class toggle), and beautiful (single accent-colored card, aligned keycap column, consistent with the
existing onboarding visual language).

All of this is presentation-only Textual/Python — no Rust core (`sase-core`) changes.

## Current State (verified)

- `src/sase/ace/tui/widgets/agent_onboarding.py` (`AgentOnboarding`) and
  `src/sase/ace/tui/widgets/changespec_onboarding.py` (`ChangeSpecOnboarding`) render the rich guides. Both take
  `context: "tab" | "modal"` and are used in **two** places:
  - Composed into the tab layouts in `src/sase/ace/tui/app.py` (`#agent-onboarding-panel`,
    `#changespec-onboarding-panel`).
  - Freshly instantiated by `src/sase/ace/tui/modals/tab_guide_modal.py` (`TabGuideModal`, opened by leader `,?` via
    `_open_tab_guide_modal` in `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`).
- PRs visibility: `ChangeSpecOnboardingMixin` in `src/sase/ace/tui/actions/changespec/_onboarding.py`.
  `_should_show_changespecs_onboarding` requires
  `_changespecs_first_load_done and not _all_changespecs and not _saved_queries` — this is the broken gate. When active,
  `-onboarding-active` on `#changespecs-view` hides **both** `#list-container` and `#detail-container` (so the
  SearchQueryPanel disappears too). When inactive-but-empty, the detail panel shows a "No ChangeSpecs match this query"
  yellow panel (`ChangeSpecDetail.show_empty`).
- Agents visibility: `_should_show_agents_onboarding` in `src/sase/ace/tui/actions/agents/_display_detail.py` (first
  load done, no agent search query, no agents). `_sync_agents_onboarding` also drives two async discovery refreshes
  (launch-target availability, plugin presence) whose results feed conditional content in `AgentOnboarding` and are
  snapshotted into `TabGuideModal` at open time.
- Both display mixins call their `_sync_*_onboarding` early in the full-refresh and detail-only-refresh paths and skip
  normal rendering when it returns True. Note `_refresh_display_impl` in
  `src/sase/ace/tui/actions/changespec/_display.py` only calls `search_panel.update_query(...)` _after_ the onboarding
  early-return — that ordering must change.
- Shared Rich helpers: `src/sase/ace/tui/widgets/_onboarding_common.py` (`append_keycap`, `append_leader_keycaps`,
  `leader_key_sequence_display`, ...). Keymap display names come from the live `KeymapRegistry` so custom keymaps render
  correctly; new content must do the same.

## Design

### 1. New shared widget: `TabQuickStart`

New file `src/sase/ace/tui/widgets/tab_quickstart.py`, class `TabQuickStart(VerticalScroll)`, parameterized by
`tab: Literal["agents", "changespecs"]`. One widget, one content pipeline, so the two pages can never drift apart (per
the requirement that they are identical except the summary).

Visual structure (max-width 90, centered, matching existing onboarding chrome):

```
                          ✦  Agents  ✦
     Every agent you launch shows up here — watch prompts, diffs,
      tool calls, and artifacts live, then jump into their work.

   ╭─ Start here ─────────────────────────────────────────────────╮
   │   space   Launch your first agent from the home-workspace    │
   │           prompt bar.                                        │
   │       #   Open the SASE Admin Center — configure sase,       │
   │           install plugins, run updates.                      │
   │     tab   Cycle tabs: Agents · PRs · AXE.                    │
   │       /   Search & filter this tab.                          │
   │       ?   Every keymap for the current tab.                  │
   │     , ?   The full tour of this tab (in-depth guide).        │
   │       :   Command palette — fuzzy-run any command.           │
   ╰──────────────────────────────────────────────────────────────╯
                  (dim, per-tab footer hint line)
```

- **Hero**: tab display name with the existing gold `*`/`✦` framing style, then the summary line in the tab accent
  color. Summaries (1–2 sentences, final copy at implementation time):
  - Agents (`#87D7FF`): "Every agent you launch shows up here — watch prompts, diffs, tool calls, and artifacts live,
    then jump straight into their work."
  - PRs (`#00D7AF`): "Every CL/PR your agents produce is tracked here as a ChangeSpec — commits, hooks, review comments,
    and status, from WIP through Submitted."
- **"Start here" card** — exactly 7 curated global keymaps, rendered as keycaps from the live `KeymapRegistry` (never
  hardcoded key labels), keys right-aligned in a fixed-width column:
  1. `start_agent_home` (default `space`) — launch your first agent.
  2. `open_config_center` (default `#`) — SASE Admin Center: configure sase, install plugins, update sase & plugins.
  3. `next_tab` (default `tab`) — cycle Agents · PRs · AXE.
  4. `edit_query` (default `/`) — search/filter the current tab.
  5. `show_help` (default `?`) — full keymap reference for the tab.
  6. leader `tab_guide` (default `, ?`) — open the preserved in-depth guide (explicitly bridges to the old content).
  7. `open_command_palette` (default `:`) — fuzzy-run any command.
- **Footer** (dim italic, per tab): Agents — "Launch an agent and it appears here."; PRs — "Your agents' PRs appear here
  as they work."
- **No-match callout (PRs only)**: `set_no_match_context(total_changespecs: int)`. When the query matched nothing but
  ChangeSpecs _do_ exist, prepend a slim yellow callout above the hero: "No PRs match this query — N exist. `/` edits
  the query." This keeps the always-on onboarding honest for established users instead of implying they have no PRs.
  Total of 0 clears the callout.

API mirrors the existing widgets so tests and sync code follow the established pattern: `set_keymap_registry(registry)`,
`refresh_content()`, and a mount-free `render_content(registry, ...) -> dict[str, Text]` for unit tests. Content
rebuilds are memoized on (registry identity, no-match total) so the hot refresh paths (tui_perf rule: sync runs inside
`_refresh_display_impl` / debounced detail refreshes) don't rebuild Rich text redundantly.

### 2. `,?` preserves the current guides (modal-only widgets)

- `AgentOnboarding` and `ChangeSpecOnboarding` stay where they are but become **modal-only**: remove the `context`
  parameter and the `context == "tab"` footer branch (dead once the tab no longer composes them); update docstrings to
  say they are the `,?` tab-guide content. All ids, classes, cards, and modal copy stay byte-for-byte the same so the
  `,?` pop-up renders exactly as today — the tab-guide PNG snapshot goldens must **not** change (this is the regression
  guard for "preserve the current content").
- `TabGuideModal` and `_open_tab_guide_modal` keep working unchanged apart from dropping the `context="modal"` argument.

### 3. PRs tab: always-visible query, onboarding in the results area

- **Predicate** (`_onboarding.py`): `_should_show_changespecs_onboarding` becomes simply
  `self._changespecs_first_load_done and not self.changespecs` (the _filtered_ list). Saved queries and
  `_all_changespecs` no longer gate it. This covers both the fresh-install case and the query-matched-nothing case with
  one rule.
- **Layout**: move the quick-start inside the right column so the SearchQueryPanel stays pinned on top. In `app.py`,
  compose `TabQuickStart(tab="changespecs", id="changespec-quickstart-panel", classes="hidden")` inside
  `#detail-container` as a sibling after `#detail-scroll`. CSS (`styles.tcss`): `-onboarding-active` on
  `#changespecs-view` now hides `#list-container` and `#detail-scroll` only — **not** `#detail-container`. Result: query
  bar full-width up top, quick-start filling the results region beneath it; when a query starts matching again, one
  class removal restores the normal two-column layout.
- **Sync** (`_sync_changespecs_onboarding`): rewrite to the simple shape — compute predicate, toggle
  `-onboarding-active` + widget `hidden` class, and when showing: push the keymap registry, call
  `set_no_match_context(len(self._all_changespecs))`, and return True. Delete the current early-return maze.
- **Query bar correctness**: in `_refresh_display_impl`, hoist `search_panel.update_query(self.canonical_query_string)`
  above the onboarding early-return so the bar always reflects the live query ("always show the search query up top").
  The `ChangeSpecDetail.show_empty` yellow panel remains only as a defensive fallback for the out-of-range-index case;
  the empty-list case now always routes to the quick-start.

### 4. Agents tab: same trigger, new content

- Keep `_should_show_agents_onboarding` and the existing full-takeover CSS (`#agents-view.-onboarding-active` hiding
  list + info panel) exactly as-is — the user only flagged the PRs logic as broken.
- In `app.py`, compose `TabQuickStart(tab="agents", id="agent-quickstart-panel", classes="hidden")` in place of the old
  `AgentOnboarding` panel; `_sync_agents_onboarding` targets it and drops the per-widget `set_launch_targets_available`
  / `set_plugins_installed` calls (the quick-start has no conditional cards).
- **Discovery plumbing stays, slimmed**: the launch-target and plugin discovery results are still needed by
  `TabGuideModal` (snapshotted at open). Keep scheduling both refreshes from `_sync_agents_onboarding` (so fresh
  installs have warm values before the user ever presses `,?`) and additionally schedule both from
  `_open_tab_guide_modal` (so established users get fresh values by their next open).
  `_apply_agents_onboarding_launch_targets_available` / `_apply_agents_onboarding_plugins_installed` become store-only
  (no widget query).

### 5. Styling (`styles.tcss`)

- Delete the now-unused `#agent-onboarding-panel` / `#changespec-onboarding-panel` id blocks; keep all
  `agent-onboarding-*` / `changespec-onboarding-*` hero/card/footer rules (still used inside the modal).
- Update the two `#changespecs-view.-onboarding-active` rules per §3.
- Add `#agent-quickstart-panel`, `#changespec-quickstart-panel`, and shared `.tab-quickstart-hero` /
  `.tab-quickstart-card` / `.tab-quickstart-callout` / `.tab-quickstart-footer` rules: centered, max-width 90,
  `border: round` card with per-tab `border-title-color` accent (Agents `#87D7FF`, PRs `#00D7AF`), matching the
  established onboarding look.

## Files to Change

| File                                                      | Change                                                                  |
| --------------------------------------------------------- | ----------------------------------------------------------------------- |
| `src/sase/ace/tui/widgets/tab_quickstart.py`              | **New** — `TabQuickStart` widget                                        |
| `src/sase/ace/tui/widgets/__init__.py`                    | Export `TabQuickStart`                                                  |
| `src/sase/ace/tui/widgets/agent_onboarding.py`            | Modal-only: drop `context` param + tab footer branch                    |
| `src/sase/ace/tui/widgets/changespec_onboarding.py`       | Modal-only: same                                                        |
| `src/sase/ace/tui/modals/tab_guide_modal.py`              | Drop `context="modal"` args                                             |
| `src/sase/ace/tui/app.py`                                 | Compose quick-starts; move PRs panel into `#detail-container`           |
| `src/sase/ace/tui/actions/changespec/_onboarding.py`      | New predicate + simplified sync                                         |
| `src/sase/ace/tui/actions/changespec/_display.py`         | Hoist `search_panel.update_query` above onboarding return               |
| `src/sase/ace/tui/actions/agents/_display_detail.py`      | Sync targets quick-start; store-only apply methods                      |
| `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py` | Schedule discovery refreshes on modal open                              |
| `src/sase/ace/tui/styles.tcss`                            | Quick-start styles; PRs `-onboarding-active` scope; drop dead id blocks |

## Testing

- **New** `tests/ace/tui/widgets/test_tab_quickstart.py`: `render_content` reflects custom keymap registries (custom key
  for `start_agent_home` etc. appears in the keycaps); the two tabs render identical keymap rows and differ only in
  hero/footer; no-match callout appears only for `changespecs` with total > 0.
- **Rewrite** `tests/ace/tui/test_changespecs_onboarding.py`: predicate is now loaded-and-filtered-empty (shows even
  with saved queries and with existing-but-filtered-out specs — inverting two current tests); integration asserts
  SearchQueryPanel stays visible and shows the live query text while `#list-container`/`#detail-scroll` hide;
  quick-start hides again when a match appears; no-match callout shows the correct total.
- **Update** `tests/ace/tui/test_agents_onboarding.py` (new widget id/content),
  `tests/ace/tui/widgets/test_agent_onboarding.py` + `test_changespec_onboarding.py` (context param removal; modal copy
  unchanged), `tests/ace/tui/actions/test_agents_onboarding_launch_targets.py` (store-only apply),
  `tests/ace/tui/modals/test_tab_guide_modal.py` (constructor tweak only).
- **PNG snapshots** (`just test-visual`): regenerate goldens for the agents/changespecs onboarding suites (new design),
  and add a scenario for the PRs "query matches nothing but specs exist" state. The
  `test_ace_png_snapshots_tab_guide.py` goldens must pass **unchanged** — any diff there means the `,?` content was not
  preserved.

## Verification

1. `just install`, then `just check` and `just test` (includes visual suite).
2. Accept intentional golden changes with `--sase-update-visual-snapshots` only for the two redesigned suites; confirm
   tab-guide goldens untouched.
3. Manual pass with `sase ace`: fresh-empty PRs tab, no-match query on a populated PRs tab (query bar + callout), empty
   Agents tab, and `,?` on both tabs showing the original guides.

## Perf Notes (per tui_perf memory)

No new I/O or subprocess work on the event loop: quick-start content is small memoized Rich text; visibility syncs
remain cheap class/hidden toggles in the existing refresh paths; discovery refreshes keep their coalesced
`asyncio.to_thread` shape. No new refresh code paths are introduced.
