---
create_time: 2026-04-26 01:12:12
status: done
bead_id: sase-t
prompt: sdd/prompts/202604/agents_tab_grouping_modes.md
---
# Agents Tab — Cyclable Grouping/Sorting Modes

## Goal

Add a new keymap to the agents tab that cycles through grouping/sorting modes for each agent group/tag panel. Today the
agents tab groups exclusively by `project → ChangeSpec → name_root` (with per-panel 2-level fallback when no agent has a
`cl_name`). After this work, the user can press a single key to cycle the agents tab through:

1. **Standard** (existing) — `project → ChangeSpec → name_root`
2. **By date** — date buckets (Today / Yesterday / This Week / Earlier), sorted within bucket by `start_time` descending
3. **By priority/status** — status buckets (Needs Attention / Running / Failed / Done), sorted within bucket by recency

The cycle is global across all panels on the agents tab (one key, all panels switch). Mode is session-only (resets to
Standard on TUI restart), matching the existing fold-state precedent.

## Design Decisions

- **Mode scope: global (not per-panel).** Cycling is a user-initiated toggle and predictable UX wants every panel to
  flip at once. Per-panel mode would also explode the fold-state-key surface area.
- **Cycle order:** `STANDARD → BY_DATE → BY_STATUS → STANDARD`. Including STANDARD in the cycle is important: users need
  a one-key path back to the default after exploring the alternates.
- **Fold state on mode change:** Mode change clears the per-mode fold registry slice (group keys differ across modes, so
  reusing them is meaningless). Maintain a small `dict[GroupingMode, GroupFoldRegistry]` so cycling back restores prior
  fold state within the session.
- **"Needs Attention" definition:** `WAITING` (with `wait_until` unset — i.e. paused on user input, not on a timer),
  `PLAN DONE`, `EPIC CREATED`, and `FAILED` that has no `retried_as_timestamp` (terminal failures the user hasn't yet
  retried). This is a judgment call worth confirming during Phase 1; document the mapping in code so it's discoverable.
- **Date buckets:** `Today`, `Yesterday`, `This Week`, `Earlier`. Computed from `start_time` in the user's local
  timezone. Empty buckets are omitted from rendering.
- **Bucket vs. ChangeSpec:** In BY_DATE / BY_STATUS modes, the inner level is still `name_root` (so multiple agents with
  the same prompt collapse cleanly); the outer level is the bucket. ChangeSpec disappears from the hierarchy in these
  modes. Project also disappears — the bucket is the L0 banner.
- **Keymap binding:** `g` (mnemonic for "grouping"). Currently unbound on the agents tab. If conflicts arise, fall back
  to `G` or `s`.

## Phasing

Three phases, each landed by a distinct agent instance. Phases are sequential — each builds on the prior.

### Phase 1 — Foundation: grouping mode model & key functions

**Scope:** Pure-data layer. No TUI/keymap/rendering changes.

- Introduce `GroupingMode` enum (`STANDARD`, `BY_DATE`, `BY_STATUS`) in `src/sase/ace/tui/models/agent_groups.py`.
- Add helpers:
  - `_date_bucket_for(agent, now)` → `"Today"` / `"Yesterday"` / `"This Week"` / `"Earlier"`.
  - `_status_bucket_for(agent)` → `"Needs Attention"` / `"Running"` / `"Failed"` / `"Done"`.
  - Status-bucket priority ordering for sort.
- Generalize `_grouping_keys_for` and `_panel_uses_changespec_level` to accept a `GroupingMode` and dispatch:
  - `STANDARD` → existing logic.
  - `BY_DATE` → `(bucket, name_root)`.
  - `BY_STATUS` → `(bucket, name_root)`.
- Generalize `build_agent_tree` to accept `mode: GroupingMode = STANDARD`. Default-arg keeps existing call sites
  compiling.
- Sort order: in `BY_DATE` / `BY_STATUS`, agents within a name_root subtree are still ordered by their existing per-name
  ordering, but bucket order is fixed (date: newest-first, status: priority-first).
- Unit tests covering:
  - Date bucketing edge cases (midnight rollover, timezone, missing `start_time`).
  - Status mapping for every known status string including retry variants.
  - Tree shape for each mode against a fixture agent list.

**Out of scope for Phase 1:** any changes under `widgets/`, `actions/`, `keymaps/`, or `default_config.yml`.

**Deliverable:** PR that's invisible to the user but exercised by tests.

### Phase 2 — Rendering & banner integration

**Scope:** Wire the mode through the rendering pipeline and style the new banner levels.

- Thread an `active_grouping_mode` parameter from the agents-tab render path (`agent_list.py` and friends) down into
  `build_agent_tree` calls. The mode lives on the agents-tab widget; default reads as `STANDARD` for now.
- Update `_agent_list_styling.py` to add banner styles for date buckets and status buckets. Reuse the existing two-level
  palette (L0 = bucket, L1 = name_root) — no new colors needed; the bucket banner takes the L0 sky-blue, name_root takes
  its current teal.
- Update `_agent_list_rendering.py` so banner labels render the bucket name plainly (no project glyph). Status mode may
  want a leading status glyph in the banner (e.g. `▲` for Needs Attention) — call this out for the implementing agent to
  decide.
- Verify `_banner_at_row` sparse-map and focus-snap logic still hold — the tuple-based key shape is unchanged, so this
  should be free.
- Snapshot or rendering tests showing each of the three modes for a representative agent fixture.

**Out of scope for Phase 2:** the keymap itself, mode persistence, or any way to actually trigger a mode change. Phase 2
ships with mode hardcoded at `STANDARD` at the call site.

**Deliverable:** Mode is fully renderable end-to-end but not yet user-toggleable.

### Phase 3 — Keymap, cycle action, per-mode fold state

**Scope:** User-facing interactivity.

- Add `cycle_grouping_mode: "g"` to `src/sase/default_config.yml` under `ace.keymaps.app`. Update keymap registry/loader
  if it has a closed allowlist of action names.
- Add `action_cycle_grouping_mode` on the agents-tab actions mixin (likely a new file
  `src/sase/ace/tui/actions/agents/_grouping.py` to keep `_folding.py` focused). The action:
  1. Advances `self._grouping_mode` in cycle order.
  2. Swaps in the per-mode fold registry from a `dict[GroupingMode, GroupFoldRegistry]` (lazily created on first use).
  3. Triggers `self._refilter_agents()` to re-render.
  4. Re-anchors banner focus to the closest equivalent group in the new mode (or to the top if no mapping exists).
- Initialize `self._grouping_mode = GroupingMode.STANDARD` and the per-mode registry dict in `actions/startup.py` near
  the existing `_group_fold_registry` setup.
- Update `actions/agents/_loading.py` so `clear_unknown(...)` operates on the _current_ mode's registry.
- Update `_folding.py` callers that read `self._group_fold_registry` to read from the mode-keyed dict.
- Optional polish: a transient toast/status-line message (`"Grouping: by date"`) on cycle so the change is discoverable.
- Tests:
  - Cycle action advances mode in the expected order and wraps.
  - Fold state in mode A is preserved when cycling A → B → A.
  - Re-render produces the right tree shape after each cycle step.

**Out of scope for Phase 3:** persisting mode across TUI restarts (matches existing fold-state precedent —
session-only), per-panel mode, or any change to the axe tab.

**Deliverable:** Feature complete and user-visible.

## Notable Risks / Open Questions

- **Status mapping ambiguity.** "Needs Attention" is the only subjective bucket; the Phase 1 agent should leave a
  `# TODO` comment with the chosen mapping and tag me for review before we commit it as canon.
- **Keymap collisions.** `g` is currently free on the agents tab but is a common vim mnemonic; if the user
  override-validation in the keymap loader objects, fall back to `G`.
- **Fold-key migration.** When the user cycles modes, the new mode's group keys are different tuples. A naive
  implementation would lose the _intent_ of "I had project X collapsed" because project no longer appears in the BY_DATE
  hierarchy. This is acceptable — collapse intent doesn't translate across grouping axes — but the implementing agent
  should not try to be clever about translating fold state across modes.
- **Empty buckets.** A panel with only `DONE` agents in BY_STATUS mode will render a single bucket. Make sure that's
  still legible (don't hide the bucket banner just because there's only one).
- **Performance.** Mode change re-runs `build_agent_tree` for every panel. Given the existing virtualization and the
  fact that fold/refresh already does this, no extra optimization is expected — but the Phase 3 agent should
  sanity-check on a large agent list.
