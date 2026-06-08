# Removing Full Agent Refreshes from the ACE TUI

**Date:** 2026-06-08
**Status:** Research / plan (no code changes yet)
**Area:** `src/sase/ace/tui/` — Agents tab rendering & refresh
**Related memory:** `memory/long/tui_jk_baseline.md` (j/k latency baseline),
`memory/short/rust_core_backend_boundary.md`

---

## 1. Problem statement

Full refreshes of the Agents tab are still slow. The user wants an audit of every
place a *full* refresh is still required — agent launches being the canonical case —
and a plan to make those paths incremental wherever possible.

This document (a) maps the current refresh machinery, (b) inventories every full-refresh
trigger and classifies each as *already incremental / convertible / genuinely necessary*,
(c) identifies the one missing primitive that forces launches to go full, and (d) lays out
a staged plan to eliminate the avoidable full refreshes.

---

## 2. How the refresh system works today

There are **two display refresh tiers** plus an **async reload pipeline** that feeds them.

### 2.1 Display tiers (`actions/agents/_display.py`)

`_refresh_agents_display(list_changed=..., defer_detail=...)` (`_display.py:136`) routes to
`_refresh_agents_display_impl` (`_display.py:157`):

- **`list_changed=True` → FULL.** Calls `_sync_panel_group()` then
  `_refresh_panel_widgets(...)` (`_display_panel_refresh.py:80`). For **every** panel it calls
  `widget.update_list(...)` which unconditionally calls `build_list(...)`
  (`_agent_list_build.py:159`). `build_list` does `widget.clear_options()` then re-formats and
  re-emits **every row** (`_agent_list_build.py:183`, `:343`), rebuilding Textual's line cache
  per panel. This is the expensive "full refresh."
- **`list_changed=False` → highlight only.** Calls `_refresh_panel_highlights()`
  (`_display_panel_refresh.py:322`) → `widget.update_highlight(...)`. No option rebuild.

`_refresh_agents_display_debounced()` (`_display.py:223`) is the j/k path: highlight + info
panel + immediate detail header, then a debounced worker fires the expensive
files/tools/diff detail update only for the final selection.

### 2.2 Async reload pipeline (`actions/agents/_loading_refresh.py`)

Refresh requests are coalesced and run off the UI thread:

```
request_agents_refresh(source, debounce_ms=150)        # _loading_refresh.py:52  (fan-out coalesce)
  └─ _schedule_agents_async_refresh(...)               # :97   (last-request-wins; at most 2 loads)
       └─ _run_agents_async_refresh()                  # :251  (nav-gate defers during j/k burst)
            └─ _load_agents_async(...)                  # disk scan via Rust core
                 └─ compute/finalize on worker threads
                      └─ _apply_loaded_agents_prepared  # _loading_apply.py:222  (UI thread)
                           └─ finalize_agent_list(...)  # _loading_finalize.py:202
                                └─ _refresh_agents_display(list_changed=True, defer_detail=True)  # :196
```

Two independent costs are paid on this path:

1. **Disk reload** — `_load_agents_async` queries the Rust artifact index / scans artifacts
   (`scan_agent_artifacts`, `query_agent_artifact_index`). The Tier-2 *full-history* scan is the
   single largest span (~2.7 s, noted at `_loading_refresh.py:159`) but is already idle-deferred
   (`TIER2_RECONCILE_IDLE_THRESHOLD_S = 30.0`, `_loading_refresh.py:26`; armed via
   `_maybe_trigger_idle_tier2_reconcile`, `:153`). Tier-1 index queries are cheaper but still
   incur disk I/O + the Rust scan + the Python merge/finalize pipeline on every refresh.
2. **Widget rebuild** — `build_list` clears and re-emits every row for every panel.

### 2.3 What already avoids a full refresh

The codebase has invested heavily in incremental primitives — they are the model to extend:

| Primitive | Location | Used for |
|---|---|---|
| `update_highlight` | `agent_list.py:237` | j/k navigation (move cursor, no rebuild) |
| `patch_agent_row` / `_try_patch_agent_row` | `agent_list.py:347`, `_display_panel_patches.py:102` | single-row in-place re-render: mark toggle, unread ack, approve/plan status, notification projection |
| `try_remove_rows` / `_try_remove_agent_rows` | `_agent_list_build.py:358`, `_display_panel_patches.py:30` | optimistic in-place removal: dismiss / kill |
| `patch_active_runtime_rows` | `_display_panel_patches.py:79` | per-tick elapsed-runtime suffix updates |

All of these are **gated and fall back to a full `list_changed=True` rebuild** when the change
isn't structurally safe (non-STANDARD grouping, active search query, multi-panel spillover,
missing per-row context, alignment width growth).

---

## 3. Audit: every full-refresh trigger, classified

### 3.1 Already incremental (patch/remove/highlight first; full refresh only as fallback)

- **j/k navigation** → `update_highlight` (`_display.py:232`). ✅
- **Mark toggle** → `_try_patch_agent_row` first (`_marking.py:100`), full rebuild only on
  fallback (`_marking.py:110`). ✅ (mostly)
- **Unread acknowledge / projection** → patch first (`_unread.py:328,359`,
  `_event_widgets.py:129`, `_notification_unread_projection.py:32`). ✅
- **Approve / plan status** → patch first (`_approve.py:112,121`). ✅
- **Dismiss / kill removal** → `try_remove_rows` fast path. ✅
- **Runtime-suffix tick** → `patch_active_runtime_rows`. ✅

### 3.2 Genuinely-necessary full refreshes (keep, or unavoidable)

- **Initial startup load** — nothing to diff against; must build from scratch. One-time.
- **Tier-2 full-history reconcile** — already idle-deferred; acceptable.
- **Periodic 60 s sanity reconcile** — safety net against missed inotify events; keep, but it
  can be made a *diff-and-patch* reconcile (see §5.3) instead of an unconditional rebuild.
- **Grouping-mode switch / fold toggle / search-query change** — structural reshuffle of the
  whole tree; full rebuild (or re-filter + rebuild) is justified.
- **Tag change in merged-panel mode** — `_tagging.py:156`; can move an agent across panels →
  structural. Justified when `_agent_panels_grouped`.

### 3.3 Convertible — currently full, *should* be incremental (the opportunity)

| Trigger | Site(s) | Today | Target |
|---|---|---|---|
| **Agent launch (single)** | `_launch_body.py:552` | `_schedule_agents_async_refresh` → full reload + rebuild | optimistic insert + in-place STARTING→RUNNING patch |
| **Workflow launch** | `_launch_body.py:404` | full reload + rebuild | same |
| **Multi-model fan-out** | `_launch_multi_model.py:64,110` | `request_agents_refresh("launch")` → full | batched insert |
| **Multi-prompt fan-out** | `_launch_multi_prompt.py:46,81,89` | full | batched insert |
| **Repeat launch** | `_launch_repeat.py:153` | full | insert |
| **Bulk CL launch** | `_launch_bulk.py:127` | full | batched insert |
| **Revive (un-archive)** | `_revive_execution.py:149,360` | `list_changed=True` | insert path |
| **Any new agent seen via inotify / poll** | reconcile pipeline | full reload + rebuild | diff-based apply (§5.3) |

**Root cause for all of §3.3:** every one of these makes a row *appear*, and there is **no
incremental insert primitive**. `_agent_list_build.py` exports `build_list` (full),
`try_remove_rows` (remove), and `patch_row` (mutate existing) — but nothing to **add** a row
without a full rebuild. So additions can only be expressed as "rebuild the panel."

---

## 4. The core gap

> Launches are slow because (a) they wait on a full async disk reload before the new row can
> appear, and (b) the apply step can only express "new agent" as a full `build_list` of the
> panel — there is no insert primitive and no diff step in the apply pipeline.

Everything else (removal, mutation, navigation) already has a fast path. Closing the **insert**
gap is the highest-leverage change and directly answers the user's ask.

---

## 5. Plan

Four stages, ordered by leverage and independence. Stages P0–P1 deliver the launch win; P2
generalizes it to *all* agent appearances; P3 mops up the remaining convertible callers.

### P0 — Add an incremental insert primitive (`insert_agent_rows`)

**Goal:** a widget-level counterpart to `try_remove_rows` that splices new Option(s) into an
existing `AgentList` without `clear_options()`.

**Where:** `widgets/_agent_list_build.py` (new `insert_agent_rows(widget, new_agents, ...)`),
exposed via a thin `AgentList.insert_agent_rows(...)` shell in `agent_list.py`, and an
app-level `_try_insert_agent_rows(...)` in `_display_panel_patches.py` mirroring
`_try_remove_agent_rows`.

**Approach:**
1. Given the panel's already-built tree state and the new agents, compute each new agent's
   target row index in tree order (reuse `build_agent_tree` ordering — see boundary note §6).
2. Format each new row via `cached_format_agent_option` and `assemble_padded_option` (same as
   `build_list`), then `insert_option_at_index` at the computed row.
3. Remap the per-row trackers exactly as `try_remove_rows` does in reverse:
   `_row_entries`, `_row_by_agent_idx`, `_row_by_agent_attempt`, `_banner_at_row`,
   `_banner_row_by_key`, `_row_render_ctx`, `_row_tier_styles`, and `_agents`.
4. Update the affected banner's chip count + `border_title` (or accept "heal on next full
   refresh" like `try_remove_rows` does for banner counts — `_agent_list_build.py:373`).

**Conservative gates → fall back to full rebuild when:**
- grouping mode ≠ `STANDARD` (matches `try_remove_rows` gate, `_agent_list_build.py:376`);
- an active search query is set (matches `_try_remove_agent_rows`, `_display_panel_patches.py:43`);
- the new agent needs a **new banner / new panel** to exist (new ChangeSpec, new project, new
  tag panel) — that's a structural change; rebuild is correct there;
- alignment width would grow past the cached `_target_width` (same guard as `patch_row`,
  `_agent_list_build.py:533`) — a wider row means every row must re-pad → rebuild;
- new agent is a workflow parent/child whose fold state changes sibling visibility.

**Tests:** unit-test the tracker remap (insert at head / middle / tail / into a banner group),
plus a property-style check that `insert_agent_rows` followed by a full `build_list` produce
identical `_row_entries`/`_row_by_agent_idx`. Add a PNG snapshot for an inserted STARTING row.

### P1 — Optimistic STARTING placeholder on launch (zero-IO row appearance)

**Goal:** the launched agent's row appears **immediately**, with no disk reload on the hot path.

**Approach:**
1. At each launch site (`_launch_body.py:404,552` and the fan-out sites), synthesize a
   STARTING `Agent` placeholder from data already in hand (project, workflow, cl_name, prompt,
   start time) and call `_try_insert_agent_rows([placeholder])`.
2. Still schedule the existing async reload as the **correctness backstop** — but it now runs
   off the hot path and, once P2 lands, reconciles via diff rather than rebuild. The existing
   STARTING→RUNNING transition already heals in place: `_poll_starting_agent_transitions`
   (`_loading_refresh.py:186`) + inotify nudge a refresh when `agent_meta.json` lands, and
   `patch_agent_row` updates status in place.
3. **Critical correctness requirement:** the placeholder's `identity` must equal the identity
   the loader will later produce, so the reconcile **dedupes** instead of duplicating the row.
   Identity = `(agent_type, cl_name/name, attempt-or-suffix)`. The placeholder must be built
   from the **same identity/ordering logic the agent runner + scan facade use** — see §6.

**Fallback:** if `_try_insert_agent_rows` returns `False` (structural gate hit — e.g. a
brand-new ChangeSpec panel), do exactly what we do today (`_schedule_agents_async_refresh`).
No regression; we only *add* a fast path.

### P2 — Diff-based apply in the reconcile pipeline

**Goal:** make *every* agent-list change that lands via reload — inotify-driven appearances of
agents launched from the CLI or other windows, the 60 s sanity reconcile, etc. — go incremental,
not just TUI launches.

**Approach:** in `_apply_loaded_agents_prepared` / `finalize_agent_list`
(`_loading_apply.py:222`, `_loading_finalize.py:196`), before calling
`_refresh_agents_display(list_changed=True)`, diff the **previous** displayed agents against the
**new** finalized list by identity → `(added, removed, changed, moved/structural)`:
- only **additions** within an existing STANDARD panel → `_try_insert_agent_rows`;
- only **removals** → existing `_try_remove_agent_rows`;
- only in-place field **changes** (status, suffix, marks) → `_try_patch_agent_row` per agent;
- any **move / reorder / new-banner / new-panel** OR a gate failure → fall back to
  `_refresh_agents_display(list_changed=True)` (today's behavior).

This converts the common steady-state reconcile (one agent appears/changes) from an O(all rows
× all panels) rebuild into O(changed rows), while preserving correctness via the full-rebuild
fallback for structural deltas.

### P3 — Convert remaining §3.3 callers

- **Revive** (`_revive_execution.py:149,360`): route through `_try_insert_agent_rows` (revive is
  an insert of known agents); keep `list_changed=True` fallback.
- **Mark-all / clear-all** (`_marking.py:149`): multi-row patch loop via `_try_patch_agent_row`
  instead of one full rebuild.
- Audit the remaining `list_changed=True` sites in `actions/agents/*` (enumerated in §3) and
  attach the patch/insert/remove fast path with full-rebuild fallback where structurally safe.

---

## 6. Rust core boundary considerations

Per `memory/short/rust_core_backend_boundary.md`, the litmus test is "would another frontend
need this behavior to match the TUI?" Splitting the plan accordingly:

- **Belongs in `../sase-core` (`sase_core` / scan facade):**
  - **Agent identity construction** for the optimistic placeholder (P1). The placeholder must
    reproduce exactly what the runner writes and the scan facade reports; this is domain
    behavior shared by any frontend that wants optimistic insert. Expose/reuse the existing
    identity builder rather than re-deriving the tuple in Python.
  - **Tree/panel ordering** — *where* a new agent sorts into the grouped tree
    (`build_agent_tree`, `build_agent_panel_index`) is core ordering behavior. P0 should call
    through the existing ordering rather than re-implementing sort/insert-position logic in the
    widget.
  - The **list diff** (added/removed/changed/moved by identity, P2) is domain-shaped and a good
    candidate to live in core so a future web/editor frontend can reuse it.
- **Stays in this repo (presentation):**
  - OptionList splice mechanics, per-row tracker remap, `Option`/`Text` formatting, banner
    chip-count/`border_title` updates, the gate/fallback policy. These are Textual-specific.

When P0/P1/P2 cross the boundary (identity, ordering, diff), update the Rust wire/API + bindings
+ tests in `../sase-core` first (via `sase workspace open -p sase-core 14`), then wire the Python
callers here.

---

## 7. Risks & correctness concerns

1. **Duplicate rows** — the #1 risk. If the placeholder identity ≠ loader identity, the reconcile
   adds a second row. Mitigation: shared identity construction (§6) + a dedupe assertion in the
   diff step; integration test that launches and then reconciles, asserting exactly one row.
2. **Banner/panel structural changes** — a launch that creates a new ChangeSpec or project panel
   *must* fall back to full rebuild. The gates in P0 must be conservative; bias toward
   `return False` (full rebuild) whenever uncertain, exactly as `try_remove_rows`/`patch_row` do.
3. **Alignment width growth** — a longer agent name/suffix than any existing row forces a re-pad
   of all rows. Gate on `_target_width` (already the `patch_row` guard) and fall back.
4. **Fold / workflow-parent visibility** — inserting a workflow parent with hidden children, or a
   child whose appearance changes a parent's fold annotation, is structural → fall back.
5. **Selection/focus stability** — inserting above the current selection shifts row indices;
   reuse the index-remap discipline from `try_remove_rows` and re-assert `current_idx` mapping.
6. **Coverage honesty** — keep the existing full-rebuild fallback wired everywhere; this plan is
   strictly additive fast paths. A gate miss must degrade to today's behavior, never to a wrong
   render.

---

## 8. Suggested sequencing (bead-sized)

1. **P0** — `insert_agent_rows` primitive + tracker-remap unit tests + snapshot. *(Self-contained;
   no behavior change until wired.)*
2. **core** — expose shared agent-identity construction + tree insert-position from `sase_core`
   bindings (prereq for P1 correctness).
3. **P1** — optimistic STARTING placeholder at launch sites, guarded, with full-rebuild fallback.
4. **P2** — diff-based apply in the reconcile pipeline (generalizes to inotify/CLI launches).
5. **P3** — convert revive + mark-all + residual `list_changed=True` callers.

Each stage is independently shippable and each falls back to current behavior, so the risk
profile is incremental.

---

## 9. Open questions

- Should the optimistic placeholder be **visually distinct** (e.g. a dimmed "starting…" style)
  until the real `agent_meta.json` lands, so a launch that ultimately fails to spawn is obvious?
- For fan-out launches (multi-model/multi-prompt/bulk), do we insert **N placeholders at once**
  (batched `insert_agent_rows`) or one-per-callback? Batched is fewer splices and matches the
  existing 150 ms `request_agents_refresh` coalescing intent.
- Is the 60 s sanity reconcile still needed once P2 makes inotify-driven reconciles cheap, or can
  its interval be lengthened?
- Where should the list-diff live — Python adapter now, or `sase_core` from the start (§6)?
