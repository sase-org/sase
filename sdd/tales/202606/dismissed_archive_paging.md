---
create_time: 2026-06-25 18:46:50
status: done
prompt: sdd/prompts/202606/dismissed_archive_paging.md
---
# Plan: Page the "Custom revival search" dismissed-agent archive (Ctrl+K loads 250 more)

## Summary

When a user picks **"Custom revival search…"** from the **Agent Restore** panel (`R` on the Agents tab) and chooses a
scope (all / a project / a ChangeSpec / home), the `DismissedAgentSelectModal` currently loads the **entire**
dismissed-agent archive from disk in one background pass before the full list appears. On archives with thousands of
dismissed bundles this is slow and janky — every bundle JSON file is parsed up front.

This plan makes that flow incremental, mirroring the recently-shipped prompt-history paging:

- **Quickly load the most recent 250** dismissed agents for the chosen scope.
- Pressing **`Ctrl+K`** loads **250 more** each time, appending to the list, until the scope is exhausted.

The page size (250) and the `Ctrl+K` keymap intentionally match the prompt-history modal so the two paging experiences
feel identical.

## Background: how it works today

User-facing flow (Agents tab):

1. `R` → `AgentReviveFlowMixin._revive_agent` shows the `SavedAgentGroupRevivalModal` ("Agent Restore"). Saved groups
   there already page via `PageDown` — that is a _separate_ feature and is **out of scope** here.
2. Selecting **"Custom revival search…"** → `_open_custom_revival_search` opens a `ProjectSelectModal` (scope picker:
   all / project / cl / home).
3. Scope chosen → `AgentReviveArchiveMixin._show_dismissed_agents_for_scope(selection)`
   (`src/sase/ace/tui/actions/agents/_revive_archive.py`):
   - Immediately shows `DismissedAgentSelectModal` seeded with the **in-memory** dismissed agents
     (`self._dismissed_agent_objects`) filtered to the scope, with `loading_archive=True`.
   - Kicks off one background worker that calls `_load_dismissed_archive()` → `load_dismissed_bundles()` which **loads
     every bundle on disk**, merges, re-filters, and replaces the modal contents via `modal.set_agents(...)`.

Key existing building blocks we will reuse:

- **`DismissedAgentSelectModal`** (`src/sase/ace/tui/modals/revive_agent_modal.py`): an `OptionList`-based multi-select
  modal. It already exposes `set_agents(agents, *, all_dismissed=..., loading_archive=...)` to rebuild its contents
  after an async load, plus a `_ReviveFilterInput`, preview pane, and mark/scroll bindings. It has **no** paging today.
- **SQLite dismissed-bundle index** (`src/sase/ace/dismissed_bundle_index/`):
  `query_summaries(root, *, suffixes, cl_name, project_name, top_level_only, limit)` returns lightweight summary rows
  **already ordered most-recent-first** (`ORDER BY COALESCE(start_time, raw_suffix) DESC, filename ASC`) and supports a
  `limit` — but **no offset/cursor** yet. This index is the natural recency-ordered, scope-filterable data source for
  paging.
- **Bundle loaders** (`src/sase/ace/dismissed_agents_bundles.py`): `load_dismissed_bundle_summaries(...)` (index query
  with rebuild-if-missing fallback), `bundle_paths_for_suffixes(ctx, suffixes)` (returns parent **and child** bundle
  paths for a set of raw suffixes), and `load_dismissed_bundles(ctx, suffixes)` (parses bundles into `Agent` objects via
  the shared loader executor).
- **Public facade** (`src/sase/ace/dismissed_agents.py`): thin wrappers that bind the singleton `ctx`, e.g.
  `load_dismissed_bundles()`, `load_dismissed_bundle_summaries(...)`, `load_dismissed_bundle_identities()`.

Useful invariants confirmed during research:

- **Child (workflow-step) bundles share the parent's `raw_suffix`** (parent file `{suffix}.json`, child files
  `{suffix}__c{n}.json`), and a child's `parent_timestamp` equals the parent's `raw_suffix`. So loading a parent's
  `raw_suffix` via `bundle_paths_for_suffixes` also returns that parent's children — exactly what the modal needs for
  its `(N steps)` counts and child-step previews.
- The modal's display contract splits the loaded set into **top-level rows** (shown in the `OptionList`) and
  **all-in-scope rows** (`_all_dismissed`, used to compute step counts / child previews). `top_level_only` in the index
  query corresponds to the modal's "`not a.is_workflow_child`" filter.

## Goal / acceptance

- Opening Custom revival search for any scope shows the most recent **250** matching dismissed agents quickly, instead
  of blocking on a full-archive parse.
- `Ctrl+K` in `DismissedAgentSelectModal` loads the next 250 for the scope and appends them; repeated presses keep
  loading until exhausted, after which `Ctrl+K` is a no-op.
- The hints bar communicates paging state (more available / loading / all loaded), consistent with the prompt-history
  modal's "`^k +250`" affordance.
- Filtering, marking (`tab`/`ctrl+a`), preview, step counts, and revive selection continue to work across loaded pages.
- No regression to the dismissed-projection self-repair that the old full-archive load performed as a side effect.

## Design overview

Reuse the prompt-history paging shape (page size 250, `Ctrl+K`, append-not-replace, async load off the event loop,
exhaustion tracking) but back it by the **dismissed-bundle SQLite index** rather than prompt shards. The index already
returns recency-ordered, scope-filterable summary rows, so paging is "skip N, take 250" against that index, then
materialize just that page's bundles (parents + their children) into `Agent` objects.

Two responsibilities that the old single full-load conflated are **split apart**:

1. **Paged display load** — incremental, scope-aware, what the user sees.
2. **Dismissed-projection self-repair** — a one-time, cheap reconciliation of the Tier-1 dismissed identity set +
   artifact index. This no longer needs to parse every bundle; it can use the index's identity projection
   (`load_dismissed_bundle_identities()` / `query_summary_identities`) which returns all identities without reading
   bundle JSON.

### Paging unit: top-level parents (scope-aware)

Each page = the next 250 **top-level** parent summaries for the scope, ordered newest-first, plus those parents'
children (loaded by suffix for step counts). Rationale:

- "250 dismissed agents" maps to **250 visible rows**, which is what the user perceives.
- Step counts/child previews stay complete per page (a parent and its children always load together), avoiding
  cross-page lag.
- Scope is pushed into the SQL query so each page yields up to 250 _in-scope_ rows — critical for narrow scopes (a
  single CL/project), where paging the global archive then filtering in Python would return mostly-empty pages.

Scope → index query mapping (`SelectionItem.item_type`):

| Scope     | Index query args                      |
| --------- | ------------------------------------- |
| `all`     | (no `cl_name`, no `project_name`)     |
| `home`    | `cl_name="~"`                         |
| `project` | `project_name=selection.project_name` |
| `cl`      | `cl_name=selection.cl_name`           |

The modal's existing Python `_filter_dismissed_agents_for_scope` continues to run on the accumulated set (it re-sorts:
project agents first, then by CL, then recency, and splits top-level vs. all-in-scope). Because the query already scoped
the rows, the Python re-filter is an idempotent safety pass; it preserves the modal's current sort semantics. "Load
more" grows the in-scope set and the list keeps its stable sort (it does not strictly append at the bottom — acceptable
and consistent with how this modal already orders rows).

## Changes by layer

### 1. SQLite index — add offset to `query_summaries`

`src/sase/ace/dismissed_bundle_index/_api.py`

- Add `offset: int | None = None` to `query_summaries(...)`.
- Emit `LIMIT ? OFFSET ?` when paging. SQLite requires a `LIMIT` before `OFFSET`; when an offset is requested without a
  limit, emit `LIMIT -1 OFFSET ?`. Keep the existing `ORDER BY COALESCE(start_time, raw_suffix) DESC, filename ASC` so
  paging is stable and newest-first.

### 2. Bundle loaders — offset passthrough + a paged loader

`src/sase/ace/dismissed_agents_bundles.py`

- Thread `offset` through `load_dismissed_bundle_summaries(...)` to `query_summaries` (both the initial call and the
  post-rebuild retry).
- Add
  `load_dismissed_bundles_page(ctx, *, cl_name=None, project_name=None, limit=250, offset=0) -> tuple[list[Agent], bool]`
  that:
  1. On the first page (`offset == 0`) ensures the archive is ready (`ctx.ensure_dismissed_archive_ready()` —
     maintenance + build index if missing) so cold starts work; later pages skip this.
  2. Queries **top-level** parent summaries for the scope with `limit=limit + 1` and `offset` (the `+1` is the has-more
     probe).
  3. Computes `exhausted = len(summaries) <= limit`; trims to `limit`.
  4. Collects the page's parent `raw_suffix`es and resolves parent + child bundle paths via
     `bundle_paths_for_suffixes(ctx, suffixes)`.
  5. Loads those bundles into `Agent` objects through the shared loader executor (same pattern as
     `load_dismissed_bundles`), marking each `agent._loaded_from_dismissed_bundle = True`.
  6. Returns `(agents, exhausted)`.
- Defensive fallback (optional): if the very first page is empty but bundles exist on disk (`ctx._iter_bundle_paths()`
  non-empty), fall back to the legacy full `load_dismissed_bundles` so an index failure never makes the archive look
  empty.

### 3. Public facade

`src/sase/ace/dismissed_agents.py`

- Add `offset` to the public `load_dismissed_bundle_summaries(...)` wrapper.
- Export `load_dismissed_bundles_page(*, cl_name=None, project_name=None, limit=250, offset=0)` bound to `_ctx()`.

### 4. Revive-archive flow — drive paging + decouple projection repair

`src/sase/ace/tui/actions/agents/_revive_archive.py`

- Rewrite `_show_dismissed_agents_for_scope(selection)`:
  - Derive the index scope args from `selection` (table above).
  - Still seed the modal instantly with in-memory dismissed agents filtered to scope.
  - Build a **stateful page-loader closure** (owns an `offset`) that, per call:
    1. `agents, exhausted = load_dismissed_bundles_page(scope args, limit=250, offset)`, advance `offset`.
    2. `merged = merge_dismissed_agents(self._dismissed_agent_objects, agents)` (dedups by identity), store back to
       `self._dismissed_agent_objects`.
    3. Re-filter via `_filter_dismissed_agents_for_scope(selection, merged)`.
    4. Return the scope-filtered `(filtered, all_in_scope, exhausted)` for the modal to render.
  - Pass that loader (and the page size, for hint text) to `DismissedAgentSelectModal`. The modal triggers the first
    page on mount and subsequent pages on `Ctrl+K`.
- **Projection repair**: replace `_load_dismissed_archive`'s full-bundle parse with an identity-based repair (e.g.
  `_repair_dismissed_projection`) that uses `load_dismissed_bundle_identities()` to get all dismissed-bundle identities
  cheaply, then runs the same prune/save/`sync_dismissed_agent_artifact_index` logic the old method did. Kick it off
  once (a lightweight one-shot worker) when the modal opens. This keeps the Tier-1 projection healthy without coupling
  repair to what the user has paged in.

### 5. Modal — add `Ctrl+K` paging

`src/sase/ace/tui/modals/revive_agent_modal.py`

- Accept a `page_loader` callback (and optional `page_size` for display) plus paging state (`_page_loading`,
  `_page_exhausted`).
- Add `Binding("ctrl+k", "load_more", "Load More", priority=True)` and an `action_load_more` that no-ops while
  loading/exhausted and otherwise runs an async worker.
- `action_load_more` / first-page-on-mount runs the loader via `asyncio.to_thread` (the loader is sync, does I/O +
  bundle parsing, and must not touch widgets), then applies results on the main thread by calling the existing
  `set_agents(...)` with the new filtered/all-in-scope lists and the page's exhausted state.
- **Intercept `Ctrl+K` in `on_key`** with `prevent_default()` + `stop()` before delegating to `action_load_more`. This
  is required because Textual's `Input` binds `ctrl+k` to delete-to-end-of-line; the prompt-history modal solves the
  same problem the same way. Mount must still focus the filter input.
- Preserve the user's position across a load-more (capture the highlighted agent before reload, restore the option
  highlight afterward) rather than jumping the preview to the top — mirroring the prompt-history modal's
  `preserve_highlight` behavior.
- Update `_hints_text()` (and the loading placeholder) to surface paging state: show `^k: +250 more` when more is
  available, a loading indicator while a page loads, and nothing paging-related once exhausted. Keep this within the
  modal's existing hint formatting.

### 6. Help / docs sync

Per `src/sase/ace/AGENTS.md`, keep the `?` help popup and any footer/hint documentation in sync with the new `Ctrl+K`
affordance in this modal.

## Edge cases

- **Empty scope**: index returns nothing → modal shows the existing "No dismissed agents in this scope" placeholder;
  `Ctrl+K` is a no-op (exhausted).
- **Cold start / missing index**: first page ensures the archive is ready and rebuilds the index if absent (via the
  existing rebuild-on-`None` path), so the first page still populates.
- **Fewer than 250 in scope**: first page returns `exhausted=True`; no `^k` affordance shown.
- **Overlap with in-memory / saved-group agents**: `merge_dismissed_agents` dedups by identity, so seeded in-memory rows
  and paged rows never double up; offsets are index-relative and stay consistent regardless of the in-memory set.
- **Marks across pages**: marks are keyed by original index into the accumulated `agents` list; `set_agents` already
  prunes out-of-range marks. Verify marks survive a load-more (they should, since the accumulated list only grows).

## Testing

- **Index**: `query_summaries` with `limit`+`offset` returns disjoint, recency-ordered pages (extend
  `tests/test_dismissed_bundle_index.py`).
- **Paged loader**: `load_dismissed_bundles_page` returns ≤ `limit` parents with their children, reports `exhausted`
  correctly at the tail, and honors scope filters (`tests/test_dismissed_bundle_persistence.py` or a focused new test).
- **Modal**: `Ctrl+K` is bound to `load_more`; a fake `page_loader` yields page 1 then page 2; pressing `Ctrl+K` appends
  page 2 without clearing filter text or losing marks; the filter Input does not eat `Ctrl+K`; hints reflect
  more/loading/exhausted (`tests/ace/tui/modals/test_revive_agent_modal.py`). Note: the existing
  `test_modal_exposes_legacy_filter_placeholder_and_bindings` asserts `"load_more" not in bindings` and must be updated
  to expect the new binding.
- **Projection repair**: update `test_load_dismissed_archive_repairs_projection_after_save`
  (`tests/test_agent_revive.py`) to drive the identity-based repair (patching `load_dismissed_bundle_identities` instead
  of `load_dismissed_bundles`) while asserting the same prune/save/`sync_dismissed_agent_artifact_index` outcome.
- Run `just check` (lint + mypy + tests) before completion.

## Out of scope / non-goals

- The saved-groups `PageDown` paging in `SavedAgentGroupRevivalModal` (already paged; untouched).
- Changing the page size away from 250 or making it configurable.
- The prompt-history modal itself (reference only).
- Reworking scope filtering semantics beyond pushing the existing scopes into the index query.

## Backend boundary note

No `sase-core` (Rust) change is required. The dismissed-bundle SQLite index and bundle loaders already live in this repo
as a Python subsystem (`src/sase/ace/dismissed_bundle_index/`, `dismissed_agents_bundles.py`), and the analogous
prompt-history paging was likewise implemented in Python here. This change extends that existing Python infrastructure
(adds an `offset` and a paged loader) rather than introducing new cross-frontend domain logic, so it stays on the Python
side consistent with both precedents.
