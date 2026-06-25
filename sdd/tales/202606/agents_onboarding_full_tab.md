---
create_time: 2026-06-25 15:52:35
status: done
prompt: sdd/prompts/202606/agents_onboarding_full_tab.md
---
# Plan: Agents-tab Onboarding Takes Over the Full Tab

## Summary

The Agents-tab onboarding view (the welcome/guide shown when the user has zero agents) currently renders only in the
**right-hand detail pane**. The left agent-list pane (a fixed 60-column column) and the top info strip stay on screen,
so the onboarding sits in a narrow ~half-width slot next to an empty list and a "0 agents" status strip — visually
cramped and a bit confusing for a first-run user ("why is there an empty list box next to the welcome screen?").

This change makes the onboarding **take over the entire Agents tab** when there are genuinely no agents: the left
agent-list pane disappears and the top info strip is hidden, so the onboarding guide fills the full width of the tab.
The instant the user's first agent appears, the normal split layout (list on the left, detail on the right, info strip
on top) returns automatically.

There is **no new state, predicate, or keybinding** — we reuse the exact same onboarding predicate and the same single
choke point (`_sync_agents_onboarding`) that already toggles the onboarding panel. We only add a layout side-effect:
collapse the surrounding chrome while onboarding is active.

## Goals & Non-goals

**Goals**

- When onboarding is active (loaded + zero agents + no active search query), the **left agent-list pane is hidden** and
  the onboarding fills the full tab width.
- The **top info strip** (`#agent-info-panel`) is also hidden so the onboarding is a clean, full-bleed takeover rather
  than sitting under a "0/0" status row. _(Flagged for review below — this is the one judgment call.)_
- Layout reverts to the normal split (list + detail + info strip) the moment the first agent shows up, with no manual
  toggle and no flicker.
- The onboarding stays **beautiful at full width** — content is centered in a readable max-width column rather than
  stretched edge-to-edge across ~120 columns.

**Non-goals**

- No change to the onboarding **trigger logic** — same predicate (`_should_show_agents_onboarding`), same gates (loaded
  / no-query / zero-agents). This plan is purely about how much of the tab the onboarding occupies.
- No change to the filtered-empty behavior (a search query that filters all agents out still keeps the normal split
  layout and the existing minimal empty detail pane).
- No backend / Rust changes (see boundary note).
- No changes to the PRs or AXE tabs, or to the artifact-viewer collapse behavior.

## Architecture boundary (Rust core)

Per `memory/rust_core_backend_boundary.md`, this is **presentation-only**: it toggles Textual widget visibility / layout
classes in response to existing local view state. No shared domain behavior, no wire/API surface another frontend would
mirror. **No `sase-core` changes.** All work is Python/Textual in the `sase` repo.

## How it works today (and the one precedent we mirror)

The Agents tab is composed in `src/sase/ace/tui/app.py` (`compose`):

```
#agents-view  (Vertical)
├─ AgentInfoPanel        (#agent-info-panel)            ← top status strip (1 row)
└─ #agents-content (Horizontal)
   ├─ #agent-list-container  → AgentList                ← LEFT  (fixed width: 60)
   └─ #agent-detail-container (width: 1fr)              ← RIGHT (fills remaining width)
      ├─ AgentDetail        (#agent-detail-panel)        ← shown when agents exist
      └─ AgentOnboarding    (#agent-onboarding-panel)    ← shown when zero agents
```

There is already a proven pattern for collapsing the left list: the **artifact viewer**. When a tracked artifact tmux
pane is live, `src/sase/ace/tui/actions/agents/_panel_artifacts.py` adds the `-artifact-viewer-active` class to
`#agents-content`, and `styles.tcss` hides the list:

```css
#agents-content.-artifact-viewer-active #agent-list-container {
  display: none;
}
```

Because `#agent-detail-container` is `width: 1fr`, hiding the list makes the detail container (and the onboarding panel
inside it, `width: 100%`) automatically expand to the **full tab width** — no width math needed. We reuse this exact
mechanism for onboarding.

## Design

### 1. A new layout class on `#agents-view`, toggled by the onboarding predicate

We add an `-onboarding-active` class to the **`#agents-view`** container (not `#agents-content`) because we want it to
control **two** things — the left list (inside `#agents-content`) and the info strip (a sibling of `#agents-content`):

```css
#agents-view.-onboarding-active #agent-list-container {
  display: none;
}
#agents-view.-onboarding-active #agent-info-panel {
  display: none;
}
```

This is independent of and composes cleanly with the artifact-viewer class (different class name, different host; and in
practice the artifact viewer never coexists with the zero-agents state). Using a separate class keeps the two concerns
orthogonal.

### 2. Drive it from the existing single choke point

`_sync_agents_onboarding()` in `src/sase/ace/tui/actions/agents/_display_detail.py` is already the **one** place that
decides onboarding-visible-vs-not and toggles the `.hidden` class on `AgentOnboarding` / `AgentDetail`. We add a small
helper and call it from there:

```python
def _set_agents_onboarding_layout(self, active: bool) -> None:
    """Collapse the agents-tab chrome (left list + info strip) while onboarding."""
    try:
        view = self.query_one("#agents-view")
    except (NoMatches, LookupError):
        return
    if active:
        view.add_class("-onboarding-active")
    else:
        view.remove_class("-onboarding-active")
```

It is called inside `_sync_agents_onboarding()` at the point where that method already commits to a visibility decision
(after the existing hot-path early-return guard), so:

- **Entering onboarding** (`show_onboarding == True`): add the class → list + info strip collapse, onboarding fills the
  tab.
- **Leaving onboarding** (first agent arrives): the existing code path already runs (because `AgentDetail` still carries
  the `hidden` class, the hot-path early-return is skipped), so we remove the class → normal split layout returns.

The existing hot-path early-return (`not show_onboarding and detail already visible → return False`) is preserved
untouched, so steady-state j/k navigation with agents present pays **zero** extra cost — when agents exist and the
detail pane is already visible, we never touch `#agents-view`'s class list. This satisfies the TUI-perf rule about not
adding work to the hot navigation path (`memory/tui_perf.md`).

This single choke point already covers initial load, refilter, kill/dismiss, grouping changes, the incremental diff
path, and tab-switch-into-Agents (all of which funnel through `_apply_agent_detail_immediate` /
`_apply_agent_detail_update` / the deferred path in `_display.py`). The layout toggle therefore inherits the same
coverage the panel toggle already has.

### 3. Keep the onboarding beautiful at full width

At full tab width (~120 cols) a single column of `width: 100%` bordered cards would stretch edge-to-edge and look sparse
next to the short copy. To keep it polished, we constrain the onboarding content to a centered, readable max-width
column:

- On `#agent-onboarding-panel` (the `VerticalScroll` root): `align-horizontal: center` so its children center.
- On `.agent-onboarding-card` and the hero/footer: a `max-width` (≈ 90) so cards form a centered column instead of
  spanning the whole width. The hero and footer remain centered text.

This makes the full-tab onboarding read like an intentional centered landing page at wide widths, while still degrading
gracefully on narrow terminals (cards fall back to full width when the terminal is narrower than the max-width; the
`VerticalScroll` keeps content reachable on short terminals). Exact max-width is finalized against the regenerated PNG
snapshot.

### 4. Info-strip update while hidden — no code change needed

`_update_agents_info_panel()` still runs and updates `#agent-info-panel` even when it is `display: none` (the widget
remains in the DOM). With zero agents this update is cheap and harmless, so we leave that path alone rather than adding
a conditional skip — fewer moving parts, no behavior risk.

## Files to change

**Edited**

- `src/sase/ace/tui/styles.tcss` — add the two `#agents-view.-onboarding-active …` collapse rules; add
  `align-horizontal: center` to `#agent-onboarding-panel` and `max-width` to `.agent-onboarding-card` / hero / footer.
- `src/sase/ace/tui/actions/agents/_display_detail.py` — add `_set_agents_onboarding_layout(active)` and call it from
  `_sync_agents_onboarding()` at the existing commit point (both the show and hide branches).

**Tests (edited / added)**

- `tests/ace/tui/test_agents_onboarding.py` — extend the pilot/integration tests:
  - When onboarding is visible (empty load → Agents tab): assert `#agent-list-container` is **not visible**
    (`#agents-view` carries `-onboarding-active`) **and** `#agent-info-panel` is **not visible**, in addition to the
    existing onboarding-visible / detail-hidden assertions.
  - When agents exist: assert `-onboarding-active` is **absent** and the list container + info strip are visible.
  - The "first agent arrives" transition test: assert the list container + info strip come **back** (class removed)
    alongside the existing onboarding-hidden / detail-visible assertions.
- `tests/ace/tui/visual/test_ace_png_snapshots_agents_onboarding.py` + golden
  `tests/ace/tui/visual/snapshots/png/agents_onboarding_120x40.png` — the layout fundamentally changes (full-width, no
  left list, no info strip), so the existing golden must be **regenerated** and re-accepted via
  `--sase-update-visual-snapshots` (`just test-visual`). The SVG-text assertions (`Welcome to sase ace`,
  `https://sase.sh`) remain.

No change to `agent_onboarding.py`'s content/`render_content` API, so the existing widget content unit tests
(`tests/ace/tui/widgets/test_agent_onboarding.py`) stay green unchanged.

## Testing strategy

- **Integration (pilot via `AcePage` + `patch_startup_loaders`)** — the highest-value coverage here, since the change is
  about layout state:
  - empty load → Agents tab → onboarding visible, detail hidden, **list container hidden, info strip hidden**,
    `#agents-view` has `-onboarding-active`.
  - agents present → onboarding hidden, detail visible, **list container + info strip visible**, no
    `-onboarding-active`.
  - empty → inject first agent + `_refilter_agents()` → layout reverts (class removed, list + strip back).
- **Visual PNG snapshot** — regenerate `agents_onboarding_120x40.png`; this is the regression guard for "beautiful and
  full-bleed" and pins the new full-width layout. Inspect the regenerated PNG to confirm no stretched/sparse cards and
  the centered column looks intentional; tune `max-width` if needed before accepting.
- **Predicate / widget-content unit tests** — unchanged; they still pass (the predicate and the widget's rendered text
  are untouched).
- Run `just check` before completion (note: `just install` first, per the ephemeral-workspace rule, then
  `just test-visual` for the visual suite).

## Risks & mitigations

- **Stale layout class after transition** → the toggle is driven by the same predicate at the same single choke point
  that already toggles panel visibility; the "leaving onboarding" branch runs because `AgentDetail` still carries
  `hidden`, so the hot-path early-return is skipped and the class is removed. Covered by the "first agent arrives"
  integration test.
- **Hot-path cost on j/k with agents present** → none: the existing early-return short-circuits before the layout helper
  runs whenever agents exist and the detail pane is already visible.
- **Hiding the focused list breaks input** → the artifact-viewer path already hides `#agent-list-container` the same way
  and is proven safe; with zero agents the list has no rows to navigate, and app-level keybindings (Tab, Space, ?, `:`)
  are handled above the list. The onboarding `VerticalScroll` can take scroll focus on short terminals. Verified by the
  integration tests + manual snapshot inspection.
- **Sparse/stretched look at wide widths** → centered max-width column; pinned by the regenerated PNG snapshot.
- **Interaction with artifact-viewer collapse** → orthogonal class on a different host element; the two states don't
  co-occur (artifact viewer requires a live agent pane, onboarding requires zero agents).

## Open question for review

1. **Hide the top info strip too?** The request is "the onboarding page takes up the **entire** agents tab," which I
   read as also hiding the 1-row `#agent-info-panel` (it would otherwise show a "0/0 … refresh countdown" strip above
   the welcome screen). I **recommend hiding it** for a clean full-bleed takeover. If you'd rather keep the status strip
   visible (e.g. to preserve the refresh countdown), it's a one-line change: drop the second CSS rule and the info-strip
   assertions. The left agent-list pane is hidden either way. **Flag for review.**
