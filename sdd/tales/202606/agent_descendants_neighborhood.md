---
create_time: 2026-06-28 16:28:26
status: done
prompt: sdd/prompts/202606/agent_descendants_neighborhood.md
---
# Agent Descendants Neighborhood — Pinned Descendant Group with Inline Revive

## Objective

Extend the `~` (neighbors) navigation on the Agents tab so that, in addition to the current same-hood neighbor list, it
surfaces the **descendants** of the selected agent — the agents nested under its dotted namespace — as a distinct group
**pinned at the top** of the chooser. Descendants are the closest kin of an agent, so they should be the most prominent
and the easiest to reach.

Unlike ordinary neighbors, the descendants group also surfaces **dismissed** descendants (members hidden via dismiss
that are normally absent from the tree) and lets the user **revive them inline** — selecting a dismissed descendant
restores it and focuses it, with no trip to the `R` "Agent Restore" panel.

The headline relatedness rule, by example: for the selected agent `foo.bar`, `foo.bar.baz` and `foo.bar.buz` are its
descendants (top group), while `foo.pig` is only a same-hood neighbor (lower group). `foo.bar.baz` is more closely
related to `foo.bar` than `foo.pig` is, so it sorts above.

## Background & Current Behavior

The just-shipped hood-neighbor model lives in:

- `src/sase/ace/tui/models/agent_hoods.py` — `agent_hood()`, `AgentNeighborRow`, `AgentNeighborIndex` (`neighbors_for`,
  `neighbor_count`, `panel_idx_for`). `AgentNeighborIndex` is built from currently **rendered** rows and groups them by
  exact case-folded hood.
- `src/sase/ace/tui/actions/agents/_neighbors.py` — `AgentNeighborMixin`: cached index (`_agent_neighbor_index` /
  `_agent_neighbor_index_cache`), the `~` entry point `_start_agent_neighbor_navigation()`, the jump path
  `_focus_agent_neighbor_by_global_index()`, and the chooser builders.
- `src/sase/ace/tui/modals/agent_neighbor_modal.py` — `AgentNeighborModal` / `AgentNeighborChoice`, a flat keyboard
  chooser returning a global agent index.
- `src/sase/ace/tui/widgets/agent_info_panel.py` — the `neighbors: N (~)` info-panel badge.
- `src/sase/ace/tui/widgets/_keybinding_bindings.py` — the footer `neighbor` / `neighbors (N)` label.
- `src/sase/ace/tui/modals/help_modal/agents_bindings.py` — "Jump to neighbor agent" help line.
- `src/sase/ace/tui/styles.tcss` — `#agent-neighbor-*` CSS.

Today, pressing `~` finds **visible** agents in the **exact same hood** and either jumps directly (one neighbor) or
opens the chooser (multiple). Dismissed agents are removed from `self._agents` and never appear.

The dismiss/revive subsystem (mapped for this plan):

- **Dismissed state**: `self._dismissed_agents: set[identity]` (on-disk-backed, cross-session source of truth) and
  `self._dismissed_agent_objects: list[Agent]` — an **in-memory, same-session** cache of dismissed `Agent` objects,
  capped at 500 (`src/sase/ace/tui/actions/agents/_dismiss_memory.py`, `DISMISSED_AGENT_OBJECTS_MAX`).
- **Inline revive primitive**: `_do_revive_agent(agent)` in `src/sase/ace/tui/actions/agents/_revive_execution.py`. It
  restores artifacts, removes the identity from `_dismissed_agents`, persists, refilters, and — crucially — **focuses
  the revived agent automatically** once the async reload completes (`_select_revived_agent` + display refresh). The `R`
  panel is just one UI on top of this primitive; we will call it directly.
- **Rendered predicate**: `agent_is_rendered_in_agents_panel()` in `src/sase/ace/tui/models/agent_panels.py`.

## Key Semantic Decisions (I am leading the design — flagging the load-bearing choices)

These are the choices that shape the implementation. Each states my decision and rationale; redirect any at review.

1. **Descendants are defined by dotted-name prefix, not workflow plan-chain.** A descendant of selected agent `N` is any
   agent `M` whose `agent_name`, case-folded, satisfies `m.startswith(n + ".")`. This is the namespace relationship the
   user's example is about (`foo.bar.baz`, `foo.bar.buz`), and it is consistent with the hood model. It is deliberately
   **not** `is_child_of()` (which matches workflow steps / follow-ups / retries by timestamp). The boundary `"."`
   matters for correctness: `foo.bar` must not match `foo.barbaz`.

2. **The group is descendants of the selected agent, not of the agent's code-hood.** For `foo.bar` the group is
   `foo.bar.*`. (Interpreting it as the code-hood `foo` would wrongly pull `foo.pig` into the group, contradicting the
   example.) This also means descendants and same-hood neighbors are always disjoint (a sibling can never be nested
   under you).

3. **All depths are included.** `foo.bar.baz` and `foo.bar.baz.deep` are both descendants of `foo.bar`. Deeper kin are
   still closer than a same-hood neighbor, so the whole subtree belongs in the pinned group.

4. **`~` now works on dotless root agents.** Today `~` is inert when the selected agent has no hood (e.g. `foo`). But
   `foo` can have descendants (`foo.bar`, `foo.baz`, …). The new rule: `~` is available whenever there is **at least one
   descendant or one neighbor**. For a dotless agent the chooser shows only the Descendants group (no neighbors group).

5. **Dismissed-descendant sourcing is same-session (in-memory).** Dismissed descendants come from
   `self._dismissed_agent_objects` (this session, capped 500). Agents dismissed in a _previous_ session that exist only
   on disk are out of scope for V1 inline revive; the `R` panel still covers them. This squarely covers the primary use
   case — reviving descendants (e.g. workflow children) you dismissed this session — without the heavyweight panel.

6. **Folded (collapsed-but-not-dismissed) descendants are out of scope for V1.** The chooser includes **rendered
   visible** descendants and **dismissed** descendants. A descendant currently hidden only because its group is folded
   is reachable by expanding the fold; surfacing/auto-expanding it from the chooser is a possible follow-up, not V1.
   This keeps jump targeting reliable (we only ever jump to rows the neighbor index can locate).

7. **Umbrella term stays "neighbors".** The user themselves calls the descendants "siblings … still shown" — i.e. part
   of the neighbor view. So the `~` entry, badge, footer, and modal remain the "neighbor" surface; descendants are a
   pinned sub-group inside it. This avoids re-churning user-facing terminology so soon after the hood-neighbor rename.
   The badge/footer count becomes the **combined** reachable total (descendants + neighbors); the modal labels the two
   groups explicitly. (Reviewable: if you'd prefer a split count like `2 kin · 3 neighbors` in the badge, that's a small
   change.)

## UX & Visual Design

The chooser becomes a two-section, keyboard-first list. Sketch for selected agent `foo.bar.7` (hood `foo.bar`), with a
dismissed descendant:

```
                  Neighbors of foo.bar.7
              [2 descendants · 3 neighbors]
  ── Descendants ─────────────────────────────────
 a  foo.bar.7.plan    DONE      #api   12:30   ⊘ dismissed
 b  foo.bar.7.code    RUNNING   #api   12:31
  ── Neighbors · foo.bar hood ────────────────────
 c  foo.bar.3         DONE      #api   12:10
 d  foo.bar.9         FAILED    #api   12:05
  enter jump · revive dismissed   a–z select   j/k move   q/esc
```

Design points:

- **Pinned Descendants group on top**, then the same-hood **Neighbors** group. The neighbors header names the hood for
  orientation.
- **Section headers are non-selectable** rows (dim, rule-style). Quick-select letters (`a–z`) are assigned only to real
  choices and skip headers and the reserved `j/k/q` keys, exactly as today.
- **Descendants ordering**: case-insensitive by `agent_name` so subtrees read top-down predictably regardless of
  dismissed/visible origin. **Neighbors ordering**: render order (unchanged).
- **Dismissed descendants** are visually distinct: dimmed row plus a `⊘ dismissed` tag in a warning accent. They render
  in the Descendants group inline with their visible siblings (sorted by name), so the subtree reads as a whole.
- **Selecting** a row:
  - visible descendant or neighbor → **jump** (existing focus path);
  - dismissed descendant → **revive + focus** (call `_do_revive_agent`; the revive flow focuses it on reload).
- **Title**: `Neighbors of <selected agent name>` with a compact `[d descendants · n neighbors]` summary (a side with
  zero count is omitted).
- **Hint line** mentions that selecting a dismissed row revives it.
- **Badge** (`agent_info_panel.py`): same `[neighbors: N (~)]` shape, where `N` is the combined reachable count.
- **Footer** (`_keybinding_bindings.py`): same `neighbor` / `neighbors (N)` label, gated on the combined count `> 0`.

The chooser also appears in a new situation: when the selected agent has descendants but a single (or zero) same-hood
neighbor, we still open the chooser rather than fast-jumping, so the descendants — especially dismissed ones — are
visible and revivable (see fast-path rule below).

## Implementation Plan

### 1. Descendant model (in `agent_hoods.py`)

- Add a pure helper `is_agent_descendant(name, ancestor) -> bool` using case-folded `"."`-boundary prefix matching, plus
  a small `agent_name_key(agent)` normalizer that rejects empty/malformed names.
- Extend `AgentNeighborIndex` so a single cached build also yields, per visible row, a **descendant count** and the
  **visible descendant global indices**. Build approach: collect all visible row names (already walked) plus the
  dismissed-object names into one case-folded, sorted list; each row's descendants are the contiguous `name + "."` range
  (sorted prefix range / bisect) — `O(n log n)` once per build. Store:
  - `descendants_for(global_idx) -> tuple[int, ...]` (visible descendant global indices, name-sorted), and
  - `descendant_count(global_idx) -> int` (visible **plus** dismissed descendants — the number the badge/footer
    advertises).
- Keep `neighbors_for` / `neighbor_count` / `panel_idx_for` unchanged. `panel_idx_for` already covers every visible row,
  so it can locate descendant jump targets with no change.
- The dismissed `Agent` objects themselves (needed to render and revive dismissed descendants) are passed into the build
  so counts are accurate; the action recovers the concrete dismissed `Agent` objects for the selected row on demand (see
  step 3) to avoid storing object references for every row.

### 2. Cache invalidation for dismiss/revive (in `_neighbors.py` + dismiss/revive mixins)

- The neighbor index now depends on the dismissed set, which is **not** in the current cache key
  `(_agents, panel_keys, merge_tag_panels, grouping_mode, fold_version)`. Add a monotonic **dismiss/revive epoch**: a
  counter on the app bumped on every dismissal (`_apply_dismissal_in_memory`, `_persist_dismissed_agent`) and every
  revival (`_do_revive_agent`, `_do_revive_agents`). Include it as a sixth discriminator in
  `_agent_neighbor_index_cache`.
- Pass the dismissed objects (`self._dismissed_agent_objects`) into `_build_agent_neighbor_index()` so descendant counts
  reflect dismissed kin. Keep the existing fast selective-refresh path intact.

### 3. Navigation action (`_start_agent_neighbor_navigation` in `_neighbors.py`)

- Replace the `agent_hood(selected) is None` early-return with a combined check: compute neighbors (as today) **and**
  descendants for the selected row; if **both** are empty, no-op. (This enables dotless-root descendants.)
- Gather descendant members for the selected agent on demand:
  - **visible descendants**: `index.descendants_for(current_idx)` → global indices (jump targets);
  - **dismissed descendants**: scan `self._dismissed_agent_objects` for names under the selected name (single-agent
    scan, cheap; only on key press).
- **Fast-path rule**: fast-jump (no modal) **only** when there is exactly one reachable related agent total **and** it
  is a visible (non-dismissed) row. In every other case — multiple related agents, or any dismissed descendant present —
  open the chooser. This preserves today's snappy single-neighbor jump while guaranteeing dismissed kin are always
  visible/revivable.
- Respect existing guards: `current_tab == "agents"`, `_current_group_key is None`, and the artifact-viewer navigation
  guard.

### 4. Inline revive wiring (`_neighbors.py`)

- Build two parallel structures for the chooser:
  - a list of `AgentNeighborChoice` rows (presentational, for the modal), now carrying `group` (`"descendant"` /
    `"neighbor"`) and `dismissed: bool`, plus the existing name/status/panel/time fields; and
  - a parallel **payload** list the action keeps, holding for each row either a visible `global_idx` (jump) or the
    dismissed `Agent` object (revive). This keeps the modal dataclass purely presentational and free of `Agent`
    references.
- The modal returns the **selected row's list index** (`int | None`). On callback:
  - visible row → `_focus_agent_neighbor_by_global_index(global_idx)` (unchanged jump);
  - dismissed row → `_do_revive_agent(agent)`. The existing revive flow handles artifact restore, dismissed-set update,
    refilter, and focusing the revived agent on reload — so the user lands on the just-revived descendant.
- Section headers are represented as non-choice entries so quick-select letters and the return index stay aligned to
  real rows only.

### 5. Chooser modal (`agent_neighbor_modal.py`)

- Render the two labeled, non-selectable section headers (Descendants, then `Neighbors · <hood> hood`), omitting an
  empty section. Distinct dismissed-row styling (`⊘ dismissed`, dimmed). Title `Neighbors of <name>` +
  `[d descendants · n neighbors]` summary. Updated hint line.
- Change the modal's result contract to the selected **choice index** (was global agent index); update the option `id`s
  and the `enter` / selector-key / option-selected paths accordingly. Selector-key assignment continues to skip headers
  and reserved keys.
- Add CSS for the section headers and dismissed-row accent in `styles.tcss` under the existing `#agent-neighbor-*`
  block.

### 6. Badge, footer, help (`agent_info_panel.py`, `_keybinding_bindings.py`, `_keybinding_modes.py`, the agents display

refresh, `agents_bindings.py`)

- Feed the **combined** count (`descendant_count(current_idx) + neighbor_count(current_idx)`) into the info-panel badge
  and the footer binding wherever the current `neighbor_count` is computed (the agents display refresh in
  `src/sase/ace/tui/actions/agents/_display_detail.py` and the info-panel `update_state` / footer plumbing). Keep the
  `neighbors` wording and the `~` key display.
- Update the help line to reflect that `~` reaches descendants too (e.g. "Jump to neighbor / descendant agent").

## Testing Plan

Extend the existing focused suites (mirroring the hood-neighbor tests):

- **`tests/ace/tui/models/test_agent_neighbors.py`** — descendant detection: `"."`-boundary prefix (no `foo.bar` ↔
  `foo.barbaz` false positive), case-insensitive, malformed/empty names excluded, all-depths inclusion, dotless agent
  has descendants, descendants disjoint from same-hood neighbors, per-row descendant counts include dismissed kin.
- **`tests/ace/tui/test_agent_neighbor_navigation.py`** — fast-jump only for a single visible related agent; chooser
  opens when any dismissed descendant exists or when ≥2 related agents exist; selecting a visible descendant jumps;
  selecting a dismissed descendant calls `_do_revive_agent`; dotless root agent with descendants opens the chooser;
  artifact-viewer / group-key guards still hold.
- **`tests/ace/tui/test_agent_neighbor_index_cache.py`** — index rebuilds when the dismiss/revive epoch bumps; cached
  descendant counts; existing invalidation triggers preserved.
- **`tests/ace/tui/modals/test_agent_neighbor_modal.py`** — two-section rendering with non-selectable headers; selector
  letters skip headers; dismissed rows tagged; return value is the chosen row index; empty section omitted.
- **`tests/ace/tui/widgets/test_agent_info_panel.py`** and the footer test — badge/footer show the combined count.
- **Visual** (`tests/ace/tui/visual/`): update the `agents_neighbor_badge` golden (combined count) and the
  `agent_neighbor_modal_60x30` golden (two sections + dismissed tag); add one new golden exercising a selected agent
  with a descendants group that includes a dismissed row. Extend the fixture in `_ace_png_snapshot_helpers.py` with such
  an agent set. Inspect actual/diff artifacts before accepting goldens.

## Validation Plan

Because this touches repo files, run the mandated setup + checks (ephemeral workspace requires install first):

```bash
just install
just check
```

While iterating, run the focused suites:

```bash
pytest tests/ace/tui/models/test_agent_neighbors.py \
  tests/ace/tui/test_agent_neighbor_navigation.py \
  tests/ace/tui/test_agent_neighbor_index_cache.py \
  tests/ace/tui/modals/test_agent_neighbor_modal.py \
  tests/ace/tui/widgets/test_agent_info_panel.py
```

Run the visual suite when rendered text/modal layout changes:

```bash
just test-visual
```

If visual failures are only the intended descendants/section/dismissed-tag changes, accept goldens with
`--sase-update-visual-snapshots` after inspecting artifacts.

Note: `sase validate` / `init --check` reports pre-existing `init memory` drift on a pristine tree, unrelated to this
work; do not try to "fix" it as part of this change.

## Risks & Mitigations

- **Per-keystroke cost.** Descendant counts must be cheap on every selection change. Mitigate by precomputing per-row
  descendant counts inside the already-cached neighbor index; compute the actual descendant member list only on `~`
  press (single-agent scan). Honor the TUI-perf rules (no disk I/O / subprocess in key handlers).
- **Stale dismissed kin.** Reviving/dismissing must invalidate the cached index. Mitigate with the dismiss/revive epoch
  in the cache key.
- **Prefix false positives.** `foo.bar` must not match `foo.barbaz`. Mitigate with strict `"."`-boundary matching,
  tested explicitly.
- **Jumping to non-locatable rows.** Only jump to rows the index can place (`panel_idx_for`). Folded/non-rendered
  descendants are excluded from V1 jump targets (only rendered visible + dismissed kin participate).
- **Async revive UX.** Inline revive is async and heavy. Mitigate by closing the chooser immediately and delegating
  focus to the existing revive flow (`_do_revive_agent` already focuses the revived agent on reload); guard for still
  being on the Agents tab.
- **Modal contract change.** Switching the modal return from global-index to choice-index touches the selector-key,
  `enter`, and option-selected paths plus the caller callback. Mitigate by updating all three paths and the callback in
  the same change, with modal unit tests asserting the index mapping.
- **Terminology continuity.** Keeping "neighbors" as the umbrella avoids a second user-facing rename so soon after the
  hood-neighbor change while still matching the user's own framing of descendants as neighbors.

## Out of Scope / Possible Follow-ups

- Reviving descendants dismissed in a **previous session** (only on disk, not in `_dismissed_agent_objects`); the `R`
  panel remains for those.
- Auto-expanding folded ancestors to jump to a folded (non-dismissed) descendant.
- Multi-select inline revive of several dismissed descendants at once.
- Additional relatedness tiers beyond descendants + same-hood neighbors (e.g. shallower shared-prefix groups).
