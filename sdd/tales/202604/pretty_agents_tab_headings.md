---
create_time: 2026-04-27 09:03:28
status: done
prompt: sdd/prompts/202604/pretty_agents_tab_headings.md
---
# Pretty Agents-Tab Headings — Design & Plan

## Problem

The "Agents" tab of `sase ace` groups entries under banner headings (project, ChangeSpec, name-root, or status/date
bucket depending on grouping mode). Today the banners look fine in isolation, but two problems make the panel feel
disjointed:

1. **Banners and entries don't read as a hierarchy.** Each banner uses its own bar/branch glyph and indent, but agent
   rows under the banner anchor at column 0 with no continuation line, no indent, and no other connector. There's
   nothing visually tying an entry to the heading it lives under.
2. **The banners themselves are loud but uneven.** L0 (project) and L1 (ChangeSpec) both use the heavy `━` rule, so the
   visual hierarchy between tiers comes only from glyph and color — easy to miss at a glance. L2 name-root banners use
   the rounded `╭─` "subtree begins" glyph, which connects to nothing above it (no parent guide line is drawn).

The user asked for a redesign that (a) makes the headings _look_ nicer and (b) makes the nesting unmistakable.

## Goals

- Banners should read as proper section dividers, with clear weight differentiation across tiers (project > ChangeSpec >
  name-root).
- Every entry — banner or agent row — should carry a left-edge tier guide that visually threads it back up to its
  ancestor banners. The tree shape should be obvious without reading any text.
- Preserve the existing right-aligned chip / suffix column alignment.
- Preserve `OptionList` selection semantics (banners stay disabled / selectable per fold level; agent rows remain
  selectable). No new vertical whitespace — the panel must stay dense.
- Work uniformly across STANDARD (2- and 3-level), BY_DATE, and BY_STATUS grouping modes.
- Keep horizontal cost modest: the deepest depth (project → ChangeSpec → name-root → agent) should add at most ~6 cells
  of left margin compared to today.

## Design

### Tier guides (the big idea)

Every row carries a fixed-width left-margin gutter built from one segment per ancestor banner tier. A segment is a
vertical bar in that tier's accent color, padded to a uniform width:

```
│  │  ▸ coder ───────────  2 agents       ← name-root banner under project + changespec
│  │   coder.claude  (RUNNING)            ← agent row under the same chain
```

Each segment is rendered as `"│  "` (3 cells: bar + 2 spaces) in the parent tier's **dim** accent color. Banner rows
then append their own prefix; agent rows append no prefix beyond the gutter (the gutter is the nesting signal).

Segment colors mirror the tier they descend from:

- Below an L0 project banner: `dim #5FAFFF` (project blue).
- Below an L0 status/date bucket banner: same `dim #5FAFFF` (the bucket plays the same role in non-STANDARD modes).
- Below an L1 ChangeSpec banner: `dim #87D7FF` (ChangeSpec cooler accent).
- Below an L1/L2 name-root banner: `dim #AFAFAF` (gray) — but agents under a name-root tier do **not** get a dedicated
  guide segment, since the name-root is the immediate parent of the agent rows and the indent already groups them.
  (Adding one more segment here would push agents 9+ cells to the right at depth 3 with no readability gain.)

So in concrete terms, the gutter depth for a row equals the number of _strictly ancestor_ L0/L1 banners — not counting
the row's own banner level, and not counting name-root tiers.

Worked examples (3-level STANDARD mode, full depth):

```
▌ sase_100  ─────────────────────────────────────  4 agents · 2 running
│  ▎ ❑ fix-bug-id  ──────────────────────────────  2 agents · 1 running
│  │  ▸ coder  ────────────────────────  2 agents
│  │   coder.claude  (RUNNING)                          1m23s
│  │   coder.codex   (DONE)                             2m11s
│  │  ▸ planner  ───────────────────────  1 agent
│  │   planner.claude  (PLAN APPROVED)                   45s
│  ▎ ❑ another-cl  ──────────────────────────────  1 agent · 1 running
│  │   solo-runner  (RUNNING)                            12s
```

2-level STANDARD (no ChangeSpec tier in this panel):

```
▌ sase_99  ──────────────────────────────────────  3 agents
│  ▸ coder  ───────────────────────────  2 agents
│   coder.claude  (RUNNING)
│   coder.codex   (DONE)
│   ad-hoc.claude  (DONE)
```

BY_STATUS (status bucket in place of project):

```
▶ Running  ──────────────────────────────────────  4 agents · 4 running
│  ▸ coder  ───────────────────────────  2 agents
│   coder.claude  (RUNNING)
│   coder.codex   (RUNNING)
│   ad-hoc-runner  (RUNNING)
✓ Done  ─────────────────────────────────────────  1 agent
│   leftovers.claude  (DONE)
```

### Banner glyph & rule refinements

| Tier                | Today                  | Proposed                              |
| ------------------- | ---------------------- | ------------------------------------- |
| L0 project / bucket | `▌ ` + heavy `━` rule  | `▌ ` + heavy `━` rule (kept — anchor) |
| L1 ChangeSpec       | `▎ ` + heavy `━` rule  | `▎ ` + **light `─` rule**             |
| L2 / L1 name-root   | `╭─ ` + light `─` rule | **`▸ `** + light `─` rule             |

Why:

- **Heavy rule only for L0** establishes a clear weight gradient: project banner reads as "section header", ChangeSpec
  reads as "subsection", name-root reads as "label group". Today L0 and L1 share the heavy rule, so the only
  differentiator is the bar glyph and color.
- **`▸` instead of `╭─`** for name-root reads as "this is a labeled group; entries follow". The rounded branch glyph
  `╭─` was an attempt to suggest a tree, but it doesn't connect upward to the ChangeSpec/project banner above (no guide
  line was ever drawn to meet it), so it always looked orphaned. The triangle is cleaner and semantically signals
  "expanded group".
- Bar/label colors and chip styles are unchanged — those already work.

### Agent-row gutter integration

Today `format_agent_option` emits hint chars (`[c] `), mark indicators (`[✓] `), the approve icon (`⚡`), retry-attempt
indents (` ↳`), and the workflow-child indent (` └─`) before the type glyph and name. After this change:

- Tier gutter segments are emitted **first**, at the very start of the row.
- All existing prefixes follow in their current order.
- Hint chars / mark / approve will visually shift right by the gutter width, but stay in their current relative order.
  Hint chars then read as labelling an indented entry, which is fine for the transient hint overlay and matches how
  file-tree navigators behave.
- Workflow-child rows already carry a ` └─` indent that signals their child-of-an- agent status. That stays — it's a
  _fourth_ tier inside the gutter, not a replacement. Workflow children of an agent that lives inside a project /
  ChangeSpec group will get gutter + `└─`, which reads correctly:

  ```
  │  │   parent-workflow  (RUNNING)
  │  │     └─ 1/3 plan.claude   (RUNNING)
  ```

### Banner-row gutter integration

- L0 banner rows: 0 gutter segments (they ARE the top tier).
- L1 ChangeSpec banner rows: 1 gutter segment (project blue).
- L2 name-root banner rows: 1 or 2 gutter segments depending on whether the panel has a ChangeSpec tier:
  - 3-level mode: project segment + ChangeSpec segment.
  - 2-level mode under project (no ChangeSpec): project segment only.
  - BY_DATE/BY_STATUS mode: bucket segment only.

The existing `_NAME_ROOT_INDENT` / `_NAME_ROOT_DEEP_INDENT` distinction goes away — the gutter handles depth uniformly,
so name-root banners always render with `▸ ` immediately after the gutter regardless of mode.

The existing `_CHANGESPEC_INDENT` similarly goes away in favor of the gutter.

### Width math

Each gutter segment is exactly 3 cells (`│` + 2 spaces). Max depth is 2 segments (= 6 cells). The existing
`combine_left_and_suffix` helper already falls back to a 2-cell gap when the row is wider than the panel — no new logic
needed there. The banner rule calculation in `format_banner_option` uses `len(prefix) + len(label) + …` to compute
`pad_len`; we just need to include the gutter in the prefix length so the rule shrinks appropriately on narrow panels.

### What is _not_ changing

- Chip text (`N agents · M running`) and chip alignment.
- Agent row content beyond the leading gutter (status colors, retry badges, fold annotations, tag/name annotations all
  stay).
- Fold/collapse semantics. The fold level still controls whether a banner is selectable; this design only affects
  rendering.
- Cache structure. Cache keys grow by one field (gutter depth + mode flag) but the `AgentRenderCache` LRU stays.

## Implementation Plan

### Files touched

1. **`src/sase/ace/tui/widgets/_agent_list_styling.py`**
   - Add `_TIER_GUIDE_GLYPH = "│"`, `_TIER_GUIDE_PADDING = "  "`, and width constant.
   - Add `_TIER_GUIDE_PROJECT_STYLE`, `_TIER_GUIDE_CHANGESPEC_STYLE` (reuse the existing `dim` color constants).
   - Replace `_NAME_ROOT_BRANCH_GLYPH = "╭─"` → `"▸"` (and adjust comment).
   - Drop `_NAME_ROOT_INDENT` / `_NAME_ROOT_DEEP_INDENT` / `_CHANGESPEC_INDENT` — the gutter handles depth.

2. **`src/sase/ace/tui/widgets/_agent_list_rendering.py`**
   - New helper `_render_tier_gutter(depth_styles: list[str]) -> Text` that emits one `│  ` segment per supplied tier
     color, in order from outermost to innermost.
   - `format_banner_option`: prepend the gutter; use light `─` rule for L1; drop `_CHANGESPEC_INDENT`; pass new prefix
     length into the rule-padding computation.
   - `format_agent_option` / `cached_format_agent_option`: accept a `tier_styles: tuple[str, ...]` parameter, prepend
     the gutter at the very start of the row.
   - `AgentRenderCache` agent key: extend with `tier_styles` so a row re-cached at a different depth doesn't reuse a
     stale render.

3. **`src/sase/ace/tui/widgets/agent_list.py`**
   - Wherever `format_banner_option` / `cached_format_agent_option` are called, compute the ancestor-tier-style list
     from the current GroupRow context (project tier color above L1; project + ChangeSpec colors above L2/agents in
     3-level mode; bucket color above L1 in BY_DATE/BY_STATUS).
   - Centralize the depth computation in a small helper next to the existing grouping traversal so
     STANDARD/2-level/3-level/BY_DATE/BY_STATUS share one code path.

4. **Tests in `tests/ace/tui/widgets/`** (notably `test_agent_list_grouping.py` and `test_agent_render_cache.py`)
   - Update existing assertions:
     - `assert "╭─ coder " in plain` → `assert "▸ coder " in plain`.
     - `assert proj_plain.startswith("▌ ")` → still true, but no longer the only spans expected (gutter spans appear on
       L1/L2/agent rows).
     - Heavy-rule expectations on ChangeSpec banner → light-rule.
   - Add new tests:
     - Gutter depth = number of L0/L1 ancestor banners across all four panel shapes (3-level STANDARD, 2-level STANDARD
       with name-root, 2-level STANDARD without name-root, BY_DATE, BY_STATUS).
     - Gutter colors thread correctly: agent rows under a ChangeSpec carry the project segment then the ChangeSpec
       segment, in that order.
     - Workflow-child rows under a deep group carry both gutter segments AND the existing `└─` step prefix.
     - Cache invalidates correctly when an agent's tier depth changes (e.g. the user switches from STANDARD to BY_STATUS
       mode and back).
   - Snapshot golden tests that compare full panel `.plain` output for one canonical fixture per grouping mode, to lock
     in the new visual layout.

### Roll-out order

1. Land the styling-constant changes and the rendering helpers behind feature-flag-free refactors that produce identical
   output (gutter depth = 0 for all cases). Run tests — should be green.
2. Wire the gutter through banner rendering. Update banner tests.
3. Wire the gutter through agent row rendering. Update agent-row tests.
4. Switch the L1 rule to `─` and the name-root glyph to `▸`. Update those tests.
5. Drop the `_*_INDENT` constants once nothing references them.
6. Manual visual smoke test in `sase ace` across all three grouping modes and at narrow panel widths (40-cell minimum).

### Risks & mitigations

- **Horizontal crowding at small panel widths**: gutter eats up to 6 cells. The `_MIN_BANNER_WIDTH = 40` already gives
  the rule a sane fallback. Verify by snapshot test at width = 40 and width = 30.
- **Cache staleness on mode switches**: handled by extending the cache key; covered by new test.
- **Hint-mode overlay legibility**: hint chars sit after the gutter, so for a tightly nested entry the hint moves right
  by 6 cells. Acceptable — hint overlay is short-lived and the gutter still anchors the row visually.
- **Workflow children look noisier** (gutter + `└─`). Mitigated by keeping the gutter dim and the workflow-child indent
  dim — the eye reads the gutter as background scaffolding, the `└─` as the local branch.

## Out of scope

- Animating fold/unfold transitions (would require Textual reactive layout work).
- Per-bucket palette in BY_STATUS mode (explicitly avoided in current code; staying calm).
- Restyling of agent rows beyond the leading gutter — status colors, retry badges, tag badges, etc. stay as-is.
