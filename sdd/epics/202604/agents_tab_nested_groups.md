---
create_time: 2026-04-25 16:14:26
status: done
bead_id: sase-q
prompt: sdd/prompts/202604/agents_tab_nested_groups.md
---
# Plan: Nested Agent Groups on the Agents Tab

## Goal

Reorganize the Agents tab of `sase ace` so users can navigate large agent rosters by collapsing/expanding three
hierarchical levels of grouping:

1. **Agent Tag** (NEW) — user-managed labels of the form `@foobar`. An agent has zero or more tags.
2. **Project / ChangeSpec** — already a stable property of every agent (`Agent.project_file`, `Agent.cl_name`).
3. **Name root** — the part of an agent's name before the first `.` (so `foo.claude`, `foo.codex`, `foo.gpt55-high` all
   share the root `foo`). Recently-introduced multi-model fanout (`shared_base_name_for_multi_model`) makes this a
   natural grouping.

Group rows render as flat-width section banners (no indentation). When a group is collapsed, its banner becomes
selectable in the side panel and `x` dismisses/kills every agent inside it.

The existing workflow fold (per-workflow attempt visibility) remains a fourth axis nested inside name-root groups; this
plan layers the three new levels above it without disturbing that behavior.

## User experience sketch

Default state (everything expanded — equivalent to today's flat list, just with banners):

```
══ @release-blockers ══════════════════════════════════════════
── sase_100 / fix-bug-id ──────────────────────────────────────
· coder ·
  ▸ coder.claude            DONE  (3m ago)
  ▸ coder.codex             RUNNING
· planner ·
  ▸ planner.claude          PLAN DONE
══ @experiments ═══════════════════════════════════════════════
── chezmoi / refactor-color-scheme ────────────────────────────
· lumberjack ·
  ▸ lumberjack.claude       FAILED
══ (untagged) ═════════════════════════════════════════════════
...
```

Collapsed at the tag level (level 0):

```
▸ ══ @release-blockers ═══ 7 agents · 1 failed ════════════════
  ══ @experiments ════════ 3 agents ════════════════════════════
  ══ (untagged) ═════════ 18 agents · 2 running ═══════════════
```

Each banner is a selectable side-panel row, the focused row is marked with `▸`, and `x` on it triggers the existing
bulk-confirm modal (`Kill/dismiss N agents in this group?`).

Visual conventions (no indentation, distinguished by rule weight + color):

- Tag header: heavy double rule `══` plus the literal `@tag` text and a per-group summary chip.
- Project header: single rule `──` with `<project> / <changespec>`.
- Name-root header: dim center-dot rule `· root ·`.
- Untagged agents and project-less agents fall into synthetic groups labeled `(untagged)` and `(no project)`.

## Tag semantics

- Persistent: stored in `~/.sase/agent_tags.json` as `{ "<agent identity>": ["tagA", "tagB"] }`. Identity matches the
  existing `(AgentType, cl_name, raw_suffix)` triple already used for marks/dismissals/pins.
- Plural: an agent may carry multiple tags. The **first** tag in the list is the agent's _primary_ tag and decides which
  tag-group it appears under (an agent shows up exactly once in the tree). The order is editable so a user can promote
  any tag to primary.
- Zero tags = synthetic `(untagged)` group.
- Tag names match `^[A-Za-z0-9_-]+$` and are stored without the `@`. The `@` is purely display.
- Tags survive an agent's lifecycle including dismissal and revival; cleanup happens lazily when the registry no longer
  knows about the agent (a periodic prune driven by the existing dismissed-bundle scan).

## Phases

Each phase ships independently and leaves `master` green. Tests live under `tests/ace/...` for TUI work and
`tests/agents/...` for the CLI/data-model work.

### Phase 1 — Tag data model, persistent store, and CLI surface

**Scope**

- Add `~/.sase/agent_tags.json` reader/writer (`src/sase/ace/agent_tags.py`, mirroring the layout of `pinned_agents.py`
  and `dismissed_agents.py`).
- Extend the in-memory `Agent` dataclass with a `tags: tuple[str, ...]` field, populated during `Agent` construction
  from the new store.
- New CLI subcommands under the existing `sase agents` group (`src/sase/main/parser_commands.py` +
  `src/sase/agents/cli_tag.py`):
  - `sase agents tag add -n NAME -t TAG` (allow `-t` repeated to add many in one shot).
  - `sase agents tag remove -n NAME -t TAG`.
  - `sase agents tag list [-n NAME]` — JSON output for editor plugins.
- Always define short options (`-n`, `-t`) per the project gotcha.
- Validation: reject `@`-prefixed `--tag` values with a clear error directing the user to omit the prefix; reject
  characters outside `^[A-Za-z0-9_-]+$`.

**Out of scope**: any TUI behavior. Phase 1 ships invisibly behind the scenes; verifiable via CLI and JSON.

**Definition of done**: `just check` green; new CLI commands round-trip tags through the JSON file; unit tests cover the
store (atomic writes, missing file, malformed file) and the new CLI subcommands.

### Phase 2 — Agents-tab tag add/remove keymap (no grouping yet)

**Scope**

- New keymap `t` on the Agents tab opens a small modal (analogous to existing query/bug-tag modals) that lets the user
  add or remove tags on the focused agent — or, if marked agents exist, on every marked agent (mirrors the marked-agents
  bulk pattern in `_marking.py`).
- Modal supports tab-completion against existing tag names already in the store.
- Render a compact `@tag` badge after the agent row's status column. Multiple tags collapse to `@first +N`.
- Footer keybinding entry per `src/sase/ace/AGENTS.md` rules: `<t>` is conditional (only meaningful on Agents tab while
  an agent is focused), so it appears in the footer.
- Update `?` help modal box (57-wide constraint) to document `t`.

**Out of scope**: visual grouping or fold behavior. Tags display only as badges.

**Definition of done**: `just check` green; user can add/remove tags interactively and they persist across `sase ace`
restarts; tests cover the modal action and the marked-agents bulk path.

### Phase 3 — Three-level group rendering (always-expanded, no fold yet)

**Scope**

- Introduce a `GroupRow` model alongside `Agent` and the existing attempt sub-row in `AgentList`'s `_row_entries`. Group
  rows carry `(level, group_key, agent_indices, is_collapsed)`.
- New module `src/sase/ace/tui/models/agent_groups.py` builds the grouped tree from a flat agent list: primary-tag →
  project → name-root → agents. Stable ordering: each group inherits the most-recent activity timestamp of its members
  so the most-active groups float to the top, matching today's overall ordering.
- Refactor `AgentList.render_agents()` to walk the tree and emit banner rows between agents. Banners use the rule styles
  described above. No indentation on agent rows.
- Pinned panel **stays flat** in this phase — no grouping there. Document this limitation in the panel header.
- Update navigation (`j`/`k`, mouse) to skip group rows for now (selection still lands on agents).

**Out of scope**: collapsing, group selection, `x`-on-group, name-root grouping when an agent name has no `.` (such
agents go under a single "" name-root that we render with no header — i.e. the project banner is followed directly by
the agent rows).

**Definition of done**: `just check` green; visual snapshot test of the new layout; existing Agents-tab tests adapt to
the new row indices; manual verification in a workspace with multi-model fanout.

### Phase 4 — Fold state, `l`/`L`/`h`/`H`, and selectable group rows

**Scope**

- New `AgentGroupFoldState` (in `agent_groups.py` or a sibling module) tracking a single global expansion level for the
  panel: `L0` (tag headers only) → `L1` (+ project) → `L2` (+ name-root) → `L3` (+ agents). Existing per-workflow
  `FoldStateManager` continues to govern attempt visibility _inside_ `L3`, preserving today's `EXPANDED` →
  `FULLY_EXPANDED` step.
- Combined effective stepping (so `l` always feels like "show me one more level"):
  `L0 → L1 → L2 → L3-with-workflows-collapsed → L3-with-workflows-expanded → L3-with-workflows-fully-expanded`, and the
  inverse for `h`. `L`/`H` jump to the endpoints.
- Wire the new behavior into `action_expand_or_layout` / `action_hooks_or_collapse` / `action_expand_all_folds` /
  `action_hooks_or_collapse_all` in `src/sase/ace/tui/actions/agents/_folding.py`. Workflow-key fold logic stays
  untouched but now only fires once we are past the new group levels.
- When a group is collapsed, its banner becomes a selectable row. `current_idx` model gains a parallel
  `current_group_key` (similar to how `current_attempt_number` is layered today), and `j`/`k` traverse banners and agent
  rows uniformly.
- Banner summaries: agent count, plus colored chips for `running`, `failed`, `awaiting approval` counts.
- `current_idx` persistence: when a fold change hides the previously focused agent, focus snaps to the nearest visible
  ancestor banner (so the user never loses their place).

**Out of scope**: `x` on group rows.

**Definition of done**: `just check` green; tests cover (a) the level transition table including the boundary between
group-fold and workflow-fold, (b) selection snap-to-ancestor behavior, (c) banner summary counts.

### Phase 5 — Bulk kill/dismiss on collapsed group rows (`x`)

**Scope**

- Extend `action_kill_agent` (`_kill_pin.py`) so that when the focused row is a `GroupRow`, it gathers every agent
  identity in the group and routes through the existing `_bulk_kill_marked_agents()` machinery — same confirmation modal
  text, same termination/dismissal split between live PIDs and completed agents.
- The marked-agents bulk path stays as-is and continues to take priority when marks exist (matches today's behavior).
- Add a footer entry so `<x>` reads "kill/dismiss group" when a group is focused, matching the conditional-keymap rules
  in `src/sase/ace/AGENTS.md`.
- Update `?` help modal documentation.

**Out of scope**: any other group-level keymaps (`m`/`p`/etc. on groups can come in a follow-up if the UX warrants it).

**Definition of done**: `just check` green; integration test exercises the dismiss-all path on a synthetic group; manual
smoke test confirms the confirmation modal counts match the banner summary.

## Risks & open questions to flag during implementation

- **Multi-tag UX clarity**. We chose primary-tag-decides-bucket so each agent appears once. If users push back wanting
  to see the same agent under each of its tags, revisit in a follow-up — implementing it as a configuration toggle is
  straightforward once the rendering layer exists.
- **Pinned panel parity**. Phase 3 deliberately leaves the pinned panel flat. If the pinned panel ever exceeds a screen,
  a follow-up plan should mirror the grouping there.
- **Tag name collisions with `@`-mention syntax elsewhere**. The CLI rejects the `@` prefix on input to keep storage
  clean; rendering always re-adds it. Confirm there's no existing semantic for `@foo` in agent names that would surprise
  users.
- **Workflow-fold + group-fold layering**. Phase 4 is the trickiest: the combined level table must not regress the
  existing per-workflow fold tests. Add explicit tests for the boundary transition before refactoring the action
  handlers.
- **Performance**. The grouping rebuild runs on every `_refilter_agents()` call. For large rosters (>500 agents) this
  could become noticeable; if it does, memoize the tree by `(agent identities tuple, tag-store version, fold-level)`.
