---
create_time: 2026-04-25 18:55:08
status: done
bead_id: sase-s
prompt: sdd/prompts/202604/dynamic_tag_panels.md
---
# Plan: Dynamic Tag Panels on the Agents Tab

## Problem & motivation

The Agents tab today uses a fixed two-pane split: a main tree on the right and a "pinned" side panel on the left.
Pinning is a manual, persisted user action (`~/.sase/pinned_agents.json`) and the layout is hardcoded to exactly one
side panel.

Separately, agents already carry tags (multiple, primary tag = first). Tags currently form the **outer** banner level of
the three-level group tree (tag → project → name-root) inside the main panel.

We want to **fuse these two ideas**: each tag becomes its own side panel on the left, and the main panel becomes the
untagged-or-residual view. This unifies "important agents that should stand out" (formerly pinning) with the existing
tagging system, eliminates a redundant concept, and makes the side-panel count adapt to the agents that exist instead of
being a fixed `1`.

Concretely the user wants:

1. Agent tags drive a dynamic number of left-side panels — one panel per tag in the currently loaded agent set, plus the
   main panel for untagged agents.
2. **Two**, not three, levels of nested grouping inside any panel — tag is now panel-level, so the in-panel tree reduces
   to project → name-root.
3. An agent has **at most one** tag. (Always the intent; the existing list-of-tags shape was a vestige.)
4. The "pinned agent" concept is removed entirely, including persistence file, CLI/UI affordances, tests, and docs.
5. `J`/`K` (formerly: move agent up/down within a group) become side-panel navigation. The old reorder feature is
   dropped (`~/.sase/agent_order.json`, `agent_order.py`, related actions/tests). `o` (formerly: toggle to/from pinned
   panel) is freed; we may keep it as an alias of `J` or remove it entirely (decided in Phase 3).
6. A new `%tag` (alias `%t`) prompt directive lets a user set the tag of an agent at launch time, sibling to existing
   `%name`, `%model`, `%plan`, etc.

## Out of scope

- Multiple tags per agent (explicitly removed).
- Reorganizing the right-pane main tree beyond removing the tag level (project → name-root grouping behavior is
  retained).
- Editing tags from the TUI is already supported via the tag modal; we will update it for the single-tag shape but not
  redesign it.
- New persistence beyond migrating the existing `~/.sase/agent_tags.json`.

## Architectural shape after the refactor

### Storage

`~/.sase/agent_tags.json`: each entry is `{"id": [...], "tag": "<tag>" | null}`. Loader returns
`dict[AgentIdentity, str | None]` (or simply omits untagged). Migration: any pre-existing list-shaped entry is reduced
to its first element on first load and rewritten.

`~/.sase/pinned_agents.json`: file is no longer read or written. We do not delete user files automatically; we simply
ignore them. (Note in the migration docstring that the file can be safely removed.)

`~/.sase/agent_order.json`: same — no longer read or written. The custom-order feature is gone.

### Data model (`Agent`)

`Agent.tags: tuple[str, ...]` → `Agent.tag: str | None`. Every read site collapses to a single nullable scalar.
`Agent.tag = None` ⇔ untagged.

### Grouping (`agent_groups.py`)

Reduced from 3 levels to 2. `_GroupingKeys` drops `tag`. `build_agent_tree` takes only project + name_root keys. Banners
for level 0 (project) and level 1 (name-root) are rendered. Fold levels become 0/1/2 instead of 0/1/2/3 — `0` is
"projects only", `1` is "projects and name-roots", `2` is "fully expanded". The recent fix-walk-visible-grouping-order
behavior must be re-derived against the smaller level set.

### Panel layout (`AgentList` and friends)

Today: two `AgentList`s side-by-side, `panel="main"` and `panel="pinned"`.

Tomorrow: a list of `AgentList`s of length `1 + |tags_in_loaded_set|`. The first is the "untagged" main; each subsequent
one is keyed by a tag value. Tag panels are sorted alphabetically by tag (case-insensitive), matching the existing
`_tag_sort_key` order, so the order is stable and matches the order the user has been seeing as level-0 banners.

A panel collection abstraction (`AgentPanelGroup` or similar) owns:

- the ordered list of panel keys (`None` for untagged main, then tag strings)
- the index of the focused panel
- helpers `focus_next() / focus_prev()` for `J`/`K`
- `agents_for_panel(key) -> list[Agent]` that filters by tag and feeds a `build_agent_tree` for that panel

The widget tree still mounts `AgentList` instances, but mounts/unmounts them dynamically on refresh as the tag set
changes.

### Navigation

- `j`/`k`: cursor within focused panel (unchanged behavior, but tree depth = 2).
- `J`/`K`: focus next/previous panel. Wraps. Untagged main is one stop in the cycle.
- `o`: removed (no behavior). Help text updated.
- Old `_pinned_panel_focused: Literal["main","pinned"]` is replaced with a `_focused_panel_idx: int` plus a getter for
  the panel key.

### Prompt directive `%tag` / `%t`

Added to `_KNOWN_DIRECTIVES` and `_DIRECTIVE_ALIASES` in `src/sase/xprompt/directives.py`.
`PromptDirectives.tag: str | None` is parsed from `%tag:<value>` (e.g. `%tag:review`) and validated with the existing
`validate_tag_name` rules from `agent_tags.py`. At agent launch time, if a parsed tag is present, the launcher writes it
through `agent_tags.set_tag()`.

### CLI `sase agents tag`

`add` and `remove` collapse to `set` and `unset` (with backwards-compatible deprecation only if cheap; otherwise just
rename — sase has no external API contract). `list` keeps working. `-t` becomes a single-value flag. The CLI docstrings,
`init` skill output, and any `parser_agents.py` help strings get updated.

## Phasing

The work is split into **three phases**, each completable by a single agent instance. Each phase ends in a green
`just check` and a logically self-contained commit. Phase 2 leaves the UI in a consistent — if temporarily simpler —
state so that Phase 3 can be reviewed independently.

---

### Phase 1 — Single-tag data model and `%tag` directive

**Goal**: establish the one-tag-per-agent invariant in storage, code, CLI, and prompts. The Agents-tab UI continues to
show its existing 3-level tree (tag → project → name-root) using `tag` instead of `tags[0]`. No layout or keymap changes
yet. The pinned panel is still present.

**Scope**:

1. `src/sase/ace/agent_tags.py`
   - Storage shape: `dict[AgentIdentity, str]` (untagged simply absent).
   - Replace `add_tags` / `remove_tags` with `set_tag` / `unset_tag`.
   - Loader migrates pre-existing list entries by taking the first element.
   - Keep `validate_tag_name` and `~/.sase/agent_tags.json` path.
2. `Agent` model and every reader — switch `tags: tuple[str, ...]` to `tag: str | None`. Update all call-sites
   (`agent_groups.py`, tag modal, detail panel, etc.) to read the scalar.
3. `src/sase/agents/cli_tag.py` — `set` / `unset` / `list` subcommands. Update `parser_agents.py` flags and short
   options (`-t` is single-value).
4. `src/sase/xprompt/directives.py` — add `%tag` / `%t` to known directives and aliases; extend `PromptDirectives` with
   `tag: str | None`; parse value with `validate_tag_name`. Surface validation errors using the existing directive error
   path.
5. Wire `PromptDirectives.tag` into the agent launch flow so the new agent's tag is persisted via `set_tag()` before/at
   launch. (Site: `agent/launcher.py` or wherever `name`/`model` directives are applied today.)
6. Update tag modal (`agent_tag_modal.py`) for single-tag input.
7. Tests: rewrite `tests/test_agent_tags.py` for the scalar shape; add a migration test (legacy file with multi-tag
   entries → first-tag-wins); directive parser tests for `%tag` valid/invalid; CLI tests for set/unset.
8. Help/skill docs: update `init` help text, README snippets, any `xprompts/` snippet that demonstrates tag usage.

**Done when**: `just check` passes; an agent launched with `%tag:foo` shows `foo` as its tag in the existing UI;
`sase agents tag set -n agent -t foo` works; `sase agents tag list` shows scalar tags; legacy multi-tag files are
silently migrated on read.

---

### Phase 2 — Remove pinned-agent concept and remove agent reordering

**Goal**: delete pinning and J/K-as-reorder. The Agents tab continues to render in a single panel (the main tree), with
a 3-level grouping unchanged from Phase 1. This intentionally leaves a layout regression (no side panels at all) that
Phase 3 fixes by introducing tag panels.

**Scope**:

1. Delete `src/sase/ace/pinned_agents.py` and any imports of it. Delete `tests/test_pinned_agents.py`.
2. Delete `src/sase/ace/agent_order.py`, `src/sase/ace/tui/actions/agents/_ordering.py`, and
   `tests/test_agent_ordering.py`. Remove their references from `actions/startup.py` and any registries.
3. Strip pin-related state from `event_handlers.py` and `_core.py`: `_pinned_panel_focused`, `_pinned_panel_indices`,
   `_pinned_panel_idx_map`, `_pinned_agents`, etc. Replace `_main_panel_indices` with a single index list owned by the
   only remaining panel. `_build_panel_indices` becomes a single-list builder (or is inlined and removed).
4. Remove the `o` action (`action_focus_pinned_panel`) and the `J`/`K` reorder actions
   (`action_move_agent_up`/`action_move_agent_down`) along with their bindings. Strip the bindings from the binding
   registry, footer (`keybinding_footer.py`), and help modal.
5. `AgentList` simplifies: drop the `panel` parameter (or keep it as a no-op flag for Phase 3 to repurpose — decided
   during implementation).
6. Tag modal "pin" affordances (if any) are removed.
7. Update `src/sase/default_config.yml` to remove any keymap entries for pin / move-agent. Update help modal.
8. Search-and-destroy: `rg -i 'pinn|pin\\b|is_pinned|pin_agent'` and `rg -i 'move_agent|agent_order|reorder'` until
   clean.

**Done when**: `just check` passes; `~/.sase/pinned_agents.json` and `~/.sase/agent_order.json` are no longer read or
written; the Agents tab shows a single tree in a single pane; `o`, `J`, `K` are unbound; help modal is consistent.

---

### Phase 3 — Dynamic tag panels and `J`/`K` panel navigation

**Goal**: introduce one left-side panel per distinct tag in the loaded agent set, with the main pane reserved for
untagged agents. `J`/`K` cycle focus between panels. The in-panel tree drops the tag level.

**Scope**:

1. `agent_groups.py`: reduce `build_agent_tree` to two levels (project → name-root). `_GroupingKeys` drops `tag`. Fold
   levels become 0/1/2. Update `find_visible_ancestor_banner`, `_walk_order`, `banner_label`, and the level-3-walk fix
   from commit 8a7f34be (it should now apply at level 2). Tests in `tests/ace/tui/models/test_agent_groups.py` are
   updated wholesale.
2. `AgentGroupFoldState` — clamp range to 0..2; update default level; update `expand`/`collapse` behavior; tests.
3. New panel-collection model (e.g. `src/sase/ace/tui/models/agent_panels.py`): given a list of agents, returns the
   ordered panel keys (`[None, "<tag1>", "<tag2>", ...]` sorted) and a slice of agents per panel. Workflow children
   inherit their parent's tag for panel assignment.
4. `AgentList` rendering: the widget mounts dynamically — main pane on the right, plus N tag panes on the left. As the
   tag set changes (agents load, tags edited, agents complete), panels are added/removed. Each pane's title shows `@tag`
   (or "untagged" for the main pane) and an aggregate badge.
5. New focus model: `_focused_panel_idx: int` plus a key getter. `j`/`k` move the cursor inside the focused panel;
   `J`/`K` move focus between panels with wrap. The detail pane reads from the focused panel's selection.
6. Footer + help modal updated to document `J`/`K` as panel navigation. `o` is left unbound (or aliased to `J` — decide
   in implementation; default is unbound to avoid surprising users who learned the new keys).
7. Persistence of focused panel across refreshes — keyed by tag value, not index, so panel additions don't shift focus.
   If the focused tag's panel disappears (last agent of that tag completes and is dismissed), focus falls back to the
   main untagged pane.
8. Tests:
   - `agent_panels` model unit tests: empty agent list, only-untagged, only-tagged, mixed, tag set changing across
     refresh.
   - Pilot tests for `AgentList` with multiple panels.
   - `J`/`K` navigation tests including wrap and panel-disappears.
   - Updated `test_agent_groups.py` for two-level tree.
   - Snapshot/footer/help tests for the new keymap.

**Done when**: `just check` passes; opening the Agents tab on a project with tagged and untagged agents shows the
expected dynamic side panels; `J`/`K` cycle focus; `j`/`k` move within a panel; folding behaves with two levels; manual
smoke covers tag-set changes during a session.

## Risks / things to watch

- **Migration safety**: `~/.sase/agent_tags.json` migration must be tolerant of partially-written or empty files. Use
  the same atomic-tempfile pattern the file already uses for writes.
- **Workflow children + panels**: a workflow child whose parent has a tag must appear in the parent's panel even if the
  child itself has no tag entry of its own. The Phase 3 panel-assignment helper must apply the same parent inheritance
  the current `_grouping_keys_for` does.
- **Empty tag panel flicker**: when the last agent of a tag finishes and is dismissed, the panel must unmount cleanly
  without crashing the focus tracker. Cover with a test.
- **Footer/help drift**: the AGENTS.md guide for `src/sase/ace/` calls out that we MUST keep the footer + help modal in
  sync with bindings; both phases 2 and 3 must update those files.
- **Dynamic memory keywords**: any `.sase/memory/` entries referencing "pinned" or "move agent" should be deleted as
  part of Phase 2.

## Phase hand-offs

Each phase produces a clean `master` (or branch) state. The hand-off artifact between phases is the codebase itself plus
this plan — agents starting Phase 2 or Phase 3 should re-read this plan to recover context.
