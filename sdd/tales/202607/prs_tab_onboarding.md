---
create_time: 2026-07-03 13:36:48
status: done
prompt: sdd/prompts/202607/prs_tab_onboarding.md
---
# PRs Tab Onboarding Page

## Product Context

The Agents tab already greets new users with a polished onboarding page when there are no agents to show. The PRs tab
has no equivalent: a fresh install lands on a cryptic `Search Query » !!!` bar, an empty results list, and a yellow "No
Results" panel — none of which explain what the tab is for or how anything ever appears on it.

This plan adds a first-class onboarding page to the PRs tab that:

- Replaces the search query bar and the query results panel (the tab's entire normal chrome) while active.
- Shows **only** when the user has no ChangeSpecs at all _and_ no saved queries (all saved queries in
  `~/.sase/saved_queries.json` are inherently ChangeSpec queries — the ace query language only filters ChangeSpecs — so
  "no saved queries for ChangeSpec" is simply an empty store).
- Explains what the tab is for and why/when agents will create ChangeSpecs.
- Links to the relevant sase.sh docs pages (ChangeSpecs, pluggable VCS, plugins/GitHub integration).
- Steps aside automatically — and immediately — the moment the first ChangeSpec lands or the user saves a query.

## Design

### When the page shows (the predicate)

Show the onboarding page iff **all** of:

1. The first ChangeSpec disk load has completed (new `_changespecs_first_load_done` flag — prevents an onboarding flash
   during startup before data arrives; mirrors `_agents_first_load_done`).
2. `_all_changespecs` (the **unfiltered** list) is empty.
3. The in-memory saved-queries cache (`app._saved_queries`) is empty.

**Design decision — unfiltered, not filtered.** The request says "when the default query has no results", and condition
2 satisfies that (an empty corpus yields zero results for _every_ query, including the default). Deliberately keying on
the unfiltered list rather than the filtered results means the page can never mask real data: a user whose ChangeSpecs
are merely filtered out by the current query keeps the normal query bar + "No Results" panel, which is what they need to
fix their query. Onboarding strictly means "you have never had a ChangeSpec and have never saved a query."

**Escape hatches stay live.** All app-level bindings keep working while onboarding shows. In particular `/` (edit query)
still opens the query modal; if the user saves a query from it (`#<N> <query>`), the saved-queries cache invalidation
immediately re-syncs and dismisses the page. Power users are never trapped.

### What the page shows (visual design)

A centered, scrollable column of cards, structurally identical to the Agents onboarding (`AgentOnboarding`) so the two
pages read as one family — but accented with the PRs tab color `#00D7AF` (from `tab_bar.py`) instead of the Agents blue
`#87D7FF`, tying the page to its tab. Cards use `max-width: 90`, rounded borders, and border titles (no step numbering —
these cards are informational, not sequential steps).

```
                          *  Your agents' work, shipped as PRs  *
                     Every CL/PR your agents produce, tracked in one place

   ╭─ What is a ChangeSpec? ────────────────────────────────────────────────╮
   │ One ChangeSpec = one CL/PR. Each tracks the full life of a change:     │
   │   WIP → Draft → Ready → Mailed → Submitted        (status lifecycle)   │
   │ …plus its commits, hook runs, review comments, and mentors.            │
   │ Stored as plain text you can open anytime: ~/.sase/projects/           │
   ╰─────────────────────────────────────────────────────────────────────────╯
   ╭─ How ChangeSpecs get here ─────────────────────────────────────────────╮
   │ Agents create them for you. Launch an agent against a project or CL    │
   │ and its work is registered here automatically; the commit workflow     │
   │ appends commits and hook results as the agent makes progress.          │
   │  <key>  switch to the Agents tab and launch your first agent.          │
   ╰─────────────────────────────────────────────────────────────────────────╯
   ╭─ Learn more ───────────────────────────────────────────────────────────╮
   │ https://sase.sh/change_spec/  ChangeSpec anatomy & lifecycle.           │
   │ https://sase.sh/vcs/          sase's pluggable VCS system.              │
   │ https://sase.sh/plugins/      sase-github & other PR integrations.      │
   │  <key>  open the help pop-up for this tab.                              │
   ╰─────────────────────────────────────────────────────────────────────────╯
        Your first ChangeSpec replaces this guide with the live PR list.
```

Details that make it beautiful and consistent:

- **Hero**: centered two-line hero mirroring the Agents hero style (gold `*` flourishes, bold white title, dim `#00D7AF`
  subtitle).
- **Status lifecycle chain**: render each status name in its canonical color via `get_status_color()` from
  `src/sase/ace/display_helpers.py` with dim `→` separators, so the chips match the colors users will later see in the
  real list/detail panels. This is the single most informative line on the page — it teaches the whole lifecycle at a
  glance.
- **Keycaps**: reuse the exact keycap chip styling from the Agents onboarding (`bold #1a1a1a on #00D7AF`), driven by the
  live `KeymapRegistry` (`key_display_name(...)`) so the copy always matches the user's actual keymap. The "switch to
  the Agents tab" hint uses the `prev_tab` binding (Agents is the previous tab from PRs in `TAB_ORDER`).
- **Links**: rendered exactly like the Agents onboarding docs link — Rich `Text` spans with
  `style="bold #00D7AF link <url>"`, which Textual emits as clickable OSC-8 terminal hyperlinks while remaining readable
  as literal URLs in terminals without hyperlink support. Three links: `https://sase.sh/change_spec/`,
  `https://sase.sh/vcs/`, `https://sase.sh/plugins/` (these slugs are confirmed against the docs site source in
  `docs/` + `mkdocs.yml`).
- **Footer**: dim italic reassurance line explaining the page disappears by itself.

### How it appears/disappears (reliability)

Follow the proven Agents-tab mechanism exactly — always-mounted widget, CSS-class toggling, no mount/unmount churn:

- The onboarding widget is composed once inside `#changespecs-view` with `classes="hidden"`.
- A sync method toggles the `hidden` class on the onboarding panel and adds/removes an `-onboarding-active` class on
  `#changespecs-view`; TCSS rules collapse `#list-container` (info panel + results list + ancestors panel) and
  `#detail-container` (search query bar + detail scroll) while active. This is precisely "replace the search bar and
  results panel."
- Every path that can change the answer already funnels through the existing refresh entry points, so no new refresh
  machinery is needed (per the TUI perf rule "route refreshes through the existing fast path"):
  - **First ChangeSpec arrives**: inotify watcher → `_schedule_changespecs_async_refresh()` →
    `_apply_reloaded_changespecs()` → `_refresh_display()` (on-tab) or the `watch_current_tab` refresh on switch-back
    (off-tab). Page hides, list paints.
  - **Last ChangeSpec disappears**: same reload path; page reappears (if still no saved queries).
  - **User saves/deletes a saved query**: `_invalidate_saved_queries_cache()` gets a one-line re-sync hook.
  - **Tab switch / startup**: `watch_current_tab` → `_refresh_display()`; startup mount loads ChangeSpecs _before_ the
    first `_refresh_display()`, so the first paint already decides correctly — no flash in either direction.

### Performance

- The sync is O(1): a predicate over in-memory state (`_all_changespecs`, `_saved_queries`, one bool) plus CSS class
  toggles. No disk I/O anywhere on the render path (the saved-queries check uses the existing in-memory cache seeded at
  startup, same one `SearchQueryPanel` uses).
- Card content is rebuilt only when the page is actually shown (mirroring `_sync_agents_onboarding`'s "fast path out"
  when onboarding is hidden and the normal panels are already visible).
- No timers, no async discovery jobs (unlike Agents onboarding, this page needs no dynamic availability probes — content
  is static + keymap-driven).

### Rust core boundary

Presentation-only: Textual widget, TCSS, and show/hide glue. The underlying domain data (ChangeSpec list, saved queries)
is already exposed; saved queries are a Python-local store (`src/sase/ace/saved_queries.py`). No `sase-core` changes.

## Implementation Steps

### 1. Extract shared onboarding helpers

Create `src/sase/ace/tui/widgets/_onboarding_common.py` with the keycap/section-heading `Text` helpers currently private
to `src/sase/ace/tui/widgets/agent_onboarding.py` (`_append_keycap`, `_append_section_heading` — the latter gains an
accent-color parameter). Update `agent_onboarding.py` to import them; zero behavior change (existing agent-onboarding
tests and PNG goldens must stay green).

### 2. New widget: `ChangeSpecOnboarding`

`src/sase/ace/tui/widgets/changespec_onboarding.py`, modeled line-for-line on `AgentOnboarding`:

- `ChangeSpecOnboarding(VerticalScroll)` composing five `Static`s: `#changespec-onboarding-hero`,
  `#changespec-onboarding-what`, `#changespec-onboarding-how`, `#changespec-onboarding-learn` (cards, class
  `changespec-onboarding-card`), `#changespec-onboarding-footer`.
- Module constants for the three docs URLs and the `#00D7AF` accent.
- `set_keymap_registry(registry)` + `refresh_content()` + a **pure** `render_content(registry) -> dict[selector, Text]`
  builder so unit tests verify copy without a mounted app (same testing seam as `AgentOnboarding.render_content`).
- Card builders as static/class methods; lifecycle chain built from `("WIP", "Draft", "Ready", "Mailed", "Submitted")` ×
  `get_status_color()`.
- Export from `src/sase/ace/tui/widgets/__init__.py`.

### 3. Compose + styles

- `src/sase/ace/tui/app.py` `compose()`: yield
  `ChangeSpecOnboarding(id="changespec-onboarding-panel", classes="hidden")` as a direct child of `#changespecs-view`
  (sibling of `#list-container`/`#detail-container`).
- `src/sase/ace/tui/styles.tcss` (mirror the agents block at ~1356-1444):
  - `#changespecs-view.-onboarding-active #list-container { display: none; }`
  - `#changespecs-view.-onboarding-active #detail-container { display: none; }`
  - `#changespec-onboarding-panel { width: 1fr; height: 100%; padding: 1 2; align-horizontal: center; scrollbar-gutter: stable; }`
  - hero/card/footer rules copying the agents ones with `border-title-color: #00D7AF`.

### 4. State, predicate, and sync

- `src/sase/ace/tui/actions/_state_init.py`: add `_changespecs_first_load_done = False` (next to
  `_agents_first_load_done`); declare the attribute in `actions/startup.py`.
- `src/sase/ace/tui/actions/changespec/_loading.py`: set the flag `True` in `_apply_changespecs()` and
  `_apply_reloaded_changespecs()` (after state is applied, before the display refresh).
- New `src/sase/ace/tui/actions/changespec/_onboarding.py` → `ChangeSpecOnboardingMixin`:
  - `_should_show_changespecs_onboarding()` — the three-condition predicate above, all reads via `getattr(..., default)`
    so bare test stubs work.
  - `_sync_changespecs_onboarding() -> bool` — mirrors `_sync_agents_onboarding`
    (`src/sase/ace/tui/actions/agents/_display_detail.py:301`): fast-path `False` when hidden and the normal chrome is
    already visible; guarded widget lookups (treat a missing/absent `query_one` or `NoMatches` as "skip cleanly" —
    several existing tests drive the display mixin on plain stub objects); toggles `hidden` on the panel and
    `-onboarding-active` on `#changespecs-view`; pushes the live keymap registry into the widget when showing. Reuse the
    `_set_widget_hidden` / `_widget_has_class` helpers (lift them from `DetailMixin` into a small shared home both
    mixins import).
  - Make `ChangeSpecOnboardingMixin` a base of `ChangeSpecDisplayMixin` (or add it to `ChangeSpecMixin`'s bases in
    `actions/changespec/_core.py`) so the methods exist wherever the display mixin is used.
- Hook the sync into the two changespec paint paths in `src/sase/ace/tui/actions/changespec/_display.py`:
  - `_refresh_display_impl()`: sync first; when onboarding is visible, apply `_apply_empty_footer_update()` and return —
    skip the list/search/detail/info-panel painting (all hidden). The next full refresh after the page hides repaints
    everything, so nothing goes stale.
  - `_refresh_changespec_detail_only_impl()`: same early-out.
- `src/sase/ace/tui/actions/_startup_loads.py` `_invalidate_saved_queries_cache()`: after reloading the cache, call the
  sync (guarded) so saving/deleting a query updates the page immediately.

### 5. Tests

- **Widget unit tests** — `tests/ace/tui/widgets/test_changespec_onboarding.py` (mirror `test_agent_onboarding.py`):
  `render_content` includes all three sase.sh URLs, the five lifecycle statuses, and the `~/.sase/projects` pointer;
  keycap copy follows a custom `KeymapRegistry`.
- **Predicate + integration tests** — `tests/ace/tui/test_changespecs_onboarding.py` (mirror
  `test_agents_onboarding.py`): predicate truth table on a stub app (first-load gate, saved-query gate, unfiltered-list
  gate — including the "ChangeSpecs exist but are filtered out ⇒ no onboarding" case); mounted `AcePage` tests for:
  visible after empty startup on the PRs tab; hidden when saved queries exist despite zero ChangeSpecs; hidden when
  ChangeSpecs exist; hides after the first ChangeSpec arrives via reload; reappears after the last one disappears;
  layout assertions (`-onboarding-active` set, `#list-container`/`#detail-container` `display: none`, search bar not
  visible).
- **PNG visual snapshot** — `tests/ace/tui/visual/test_ace_png_snapshots_changespecs_onboarding.py` with golden
  `changespecs_onboarding_120x40.png` (generate via `just test-visual` + `--sase-update-visual-snapshots`); assert the
  SVG contains the ChangeSpec docs URL and hero copy.
- **Fallout audit**: sweep existing tests that mount the PRs tab with zero ChangeSpecs and assert the old "No Results"
  chrome (detail `show_empty`, footer `show_empty`, visible search bar) — update them to either seed a saved query
  (keeping the legacy path under test) or assert the onboarding page. Stub-based tests (e.g.
  `tests/ace/tui/test_changespec_detail_only_refresh.py`) must pass unchanged thanks to the guarded sync.

### 6. Verify

- `just install`, then `just check` (lint + mypy + full test suite including visual snapshots).
- Manual smoke: run the TUI against an empty sase home → PRs tab shows the page, links are clickable, `/`-save-query
  dismisses it, creating a ChangeSpec dismisses it, deleting the ChangeSpec + queries brings it back.

## Out of Scope

- No changes to the Agents/AXE onboarding content.
- No dynamic discovery cards (plugin probes etc.) on this page — static + keymap-driven only.
- No `sase-core` (Rust) changes.
- No docs-site changes.
