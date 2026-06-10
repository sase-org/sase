---
create_time: 2026-06-10 09:02:39
status: wip
prompt: sdd/prompts/202606/atomic_starting_count_and_row.md
---
# Make the "starting" count decrement and the new agent row appear atomically

## Product context

When launching agents in the `sase ace` TUI, the Agents tab surfaces two coupled signals:

- The info-panel **"starting" chip**, computed from `AgentPanelIndex.hidden_starting_indices` (top-level agents whose
  `status == "STARTING"`). It is recomputed at the end of every applied refresh **and** on every 1-second countdown tick
  (`_on_countdown_tick` → `_update_agents_info_panel`).
- The **agent row**, which only exists once the agent leaves `STARTING` (rows filter through
  `agent_is_rendered_in_agents_panel()` in `agent_panels.py`, which hides STARTING agents by design — see
  `sdd/tales/202605/hide_starting_agent_rows.md`).

The bug: there is a window where the "starting" count has already decremented but no corresponding `RUNNING`/`WAITING`
row is visible. The two surfaces are supposed to be projections of the same `self._agents` snapshot, so the user
correctly expects them to move together.

## Root cause analysis

Both surfaces derive from `self._agents`, and every apply path (`_apply_loaded_agents_prepared_inner` →
`finalize_agent_list` → `_refresh_agents_display[_after_finalize]`) repaints rows and the info panel in one synchronous
UI pass. So within a single _honestly diffed_ apply they are atomic. The desync comes from the row-side change detection
being defeasible while the count side is not:

1. **The display diff compares live objects.** `_refresh_agents_display_after_finalize` decides which panels to rebuild
   from `build_agent_display_diff(previous_agents, self._agents)` (`_display_diff.py`), where
   `previous_agents = list(self._agents)` is captured just before the swap and rows change only when
   `previous != next_agent` (dataclass equality).

2. **The Tier-1 patch merge reuses and mutates cached objects.** Post-reconcile Tier-1 loads and all artifact-delta
   loads run `merge_incomplete_load_after_complete_history` (`_loading_compute_merge.py`), which carries **cached Agent
   objects** forward (`replacement = incoming_by_key.get(key, cached)`), then runs
   `_normalize_relationships_after_merge` → `apply_status_overrides` (`_agent_status_overrides.py`), which **mutates
   `agent.status` in place** — e.g. family-root mirroring (`parent.status = newest.status`), DONE→QUESTION/PLAN
   normalization, handoff statuses. `_apply_finalize_plan` also applies status overrides in place on the new list.

   When a carried-forward object that is shared with `previous_agents` (and with the live `AgentList._agents` widget
   state) has its status flipped in place, the diff compares the object against itself and sees **no change**. No panel
   rebuild is scheduled, so no row is added — but `_update_agents_info_panel()` recomputes the metrics from the _new_
   panel index at the end of the same pass (and again every countdown tick), so the "starting" count decrements
   immediately. The row only appears once a later broad refresh produces fresh objects and an honest diff — bounded by
   the auto-refresh interval / Tier-1 floor, i.e. the user-visible "short period of time".

   This bites hardest in the flows this user runs constantly: agent families and `%wait` chains, where the visible
   transition is exactly an in-place mirrored status on a cached root/child during a poll-triggered artifact-delta
   refresh (`_poll_starting_agent_transitions` → `_schedule_agent_artifact_delta_refresh`).

3. **Contributing windows (same symptom class, secondary):**
   - `_agent_info_metrics_cache` is keyed on `id(self._agents)` _without holding a reference to the list_
     (`_display_detail.py`), so a GC'd list whose id is reused can serve stale/fresh counts inconsistently with rows.
   - For claim-backed project agents (no `running.json`/`workflow_state.json`/`done.json`), the artifact-delta loader
     (`load_artifact_delta_agents`) produces **no agent at all**, so the 1 s starting-poll refresh is an effective no-op
     for them and their promotion waits for the next broad refresh — stretching the window during which any count-side
     leak is visible.

## Goal

Enforce the invariant: **an agent identity may only leave the "starting" count in the same paint that either renders its
row or positively removes it (killed/dismissed/dead)**. Equivalently: counts shown in the info panel must always be
derivable from the rows actually painted plus the hidden-starting set of the same snapshot — on every path (broad load,
delta load, in-place mutation actions, countdown tick).

## Non-goals

- Rendering STARTING rows directly (deliberately rejected in `hide_starting_agent_rows.md`; would reintroduce row churn
  and widen selection semantics).
- Replacing the inotify watcher, the Tier-1/Tier-2 split, or the debounced refresh machinery.
- Changing how the agent runner records markers (`run_started_at`, `waiting.json`).

## Design

### Phase 0 — Invariant instrumentation (confirm + guard)

Add a cheap consistency probe to the apply/paint path (behind the existing `SASE_TUI_TRACE` flag plus a test-only
assertion helper): after every Agents-tab paint, record `(starting_identities, rendered_identities)` and flag any
identity that left the starting set without appearing in rendered rows in the same paint. Wire the same check into the
existing launch/refresh test fixtures (`test_starting_agent_poll.py`, `test_launch_fan_out_unified.py`) so the invariant
is continuously enforced. This confirms the diagnosis live and catches regressions from any future refresh path.

### Phase 1 — Mutation-proof display diffing (core fix)

Make row-change detection independent of live-object identity/equality:

- At the end of every paint, the display layer snapshots a **rendered-row signature** — per panel, the ordered tuple of
  `(identity, render-relevant fields)` actually painted (status, marked/unread, tag, fold counts; the same inputs
  `patch_agent_row` uses). Store plain tuples, never Agent references.
- `_refresh_agents_display_after_finalize` (and the `_try_refresh_agents_display_incremental` family) computes the diff
  between the _new panel index_ and this snapshot instead of `previous_agents` object comparisons. An in-place `status`
  mutation on a shared object now always surfaces as a signature mismatch → the affected panel rebuilds in the same pass
  that updates the info panel.
- Fix `_agent_info_metrics_cache` to hold the agents-list reference (like `_agent_panel_index_cache`) instead of a raw
  `id()`, eliminating the id-reuse hazard.

### Phase 2 — Copy-on-write in the patch merge (defense in depth)

In `merge_incomplete_load_after_complete_history` / `_normalize_relationships_after_merge`, stop mutating cached agents
that are shared with the live projection: when `apply_status_overrides` (or the merge itself) would change a
carried-forward agent's render-relevant fields, replace it with a copy first. This restores soundness for _every_
consumer of object diffs (widgets, nav-stop caches, sibling index), not just the row refresh. Copies are bounded by the
number of agents whose derived status actually changes per apply (typically 0–2).

### Phase 3 — Single-pass count/row coupling

Pin the info-panel metrics to the painted projection:

- The countdown tick keeps using the cached metrics (`update_countdown_only` already avoids rebuilding stable text);
  with Phases 1–2 the cache key (the agents-list ref) only changes through paints that also reconcile rows, making
  "counts change ⇒ rows reconciled in the same pass" structurally true.
- Audit the explicit in-place mutation actions (kill, dismiss, wait-resume, tagging) to confirm each repaints rows and
  info panel in the same call (today they do via `_try_patch_agent_row` → `_update_agents_info_panel`); add the Phase 0
  assertion to their tests.

### Phase 4 (optional, shrinks the visible window) — Claim-aware artifact-delta loads

Teach `load_artifact_delta_agents` to surface claim-backed project agents: for delta artifact dirs that match a
RUNNING-field claim (`<project>/artifacts/<workflow>/<timestamp>` ↔ claim `artifacts_timestamp`), run the existing claim
loader scoped to those project files and enrich from the already-scanned records. Today the 1 s
`_poll_starting_agent_transitions` fires for these agents but the delta load returns nothing, so their
STARTING→RUNNING/WAITING promotion waits for the next broad refresh. With this change the existing poll delivers the
promotion (count decrement + row, atomically per Phases 1–3) within ~1 s of `run_started_at`/`waiting.json` landing.
Cost: reading a handful of small project spec files, only when a delta refresh fires for a dir with a live claim.

### Phase 5 (optional hardening, separate flow) — Atomic deferred-workspace claim handoff

`claim_deferred_workspace` (`run_agent_phases.py`) releases the placeholder workspace-0 claim _before_ claiming the real
workspace; a refresh in that gap sees no claim and drops the agent entirely (row + counts flap). Convert the handoff to
a single locked rewrite (transfer-style, like `transfer_workspace_claim`). Note: claim semantics partially live in the
Rust core (`sase.core.agent_launch_claims`) — apply the core-boundary litmus test and route the atomic operation through
`sase-core` if it changes shared claim behavior.

## Performance constraints

- **j/k latency is the guarded metric** (target p95 < 16 ms; baseline in `memory/long/tui_jk_baseline.md`). The
  signature snapshot is built from data already in hand at paint time (panel slices) — O(visible rows) tuple
  construction per paint, no extra disk I/O, no per-keystroke work (j/k highlight paths don't rebuild rows and are
  untouched). Verify with `pytest -s -m slow tests/ace/tui/bench_tui_jk.py` before/after.
- **Steady-state tick cost unchanged**: no STARTING agents ⇒ Phase 0 probe and starting-poll stay no-ops; the tick
  continues to hit the metrics cache.
- **Copy-on-write** allocates only for transitioning agents (typically 0–2 per apply, bounded by launch fan-out).
- **Phase 4** adds project-spec reads only during delta refreshes that target claimed dirs (launch windows), never in
  steady state.

## Test plan

- Unit test reproducing the desync: cached agents list + artifact-delta merge that flips a carried-forward agent's
  status in place (family-root mirror); assert pre-fix the diff misses it and post-fix the row paints in the same apply
  as the count decrement (Phase 0 invariant helper).
- Signature-diff coverage: hidden→rendered (STARTING→RUNNING), rendered→hidden, tag/panel moves, fold interactions
  (`BY_STATUS` grouping fallback unchanged).
- Merge copy-on-write: carried-forward agents whose status changes are new objects; untouched agents keep identity (so
  the diff stays narrow and incremental paths still patch rather than rebuild).
- Phase 4: delta refresh of a claim-backed dir with fresh `run_started_at` promotes the row within one poll tick;
  fan-out of N launches still coalesces to one debounced refresh.
- Existing suites: `test_starting_agent_poll.py`, `test_launch_fan_out_unified.py`, panel index/patch tests, PNG visual
  suite (`just test-visual`) — no intended pixel changes.
- `just install` + `just check` after code changes.

## Risks / open questions

- The rendered-row signature must include every render-relevant input or the incremental path could under-rebuild;
  mitigate by deriving the signature from the same inputs `patch_agent_row`/`update_list` consume, and by keeping the
  existing conservative full-rebuild fallbacks.
- Copy-on-write changes object-identity assumptions in any code holding direct Agent references across refreshes (detail
  panel, marks use identity tuples — safe; audit `widget._agents` sharing in `_try_patch_agent_row`).
- Phase 4 widens the delta loader's contract (claims are not artifact-backed); keep it scoped to dirs with live claims
  so Tier-1/Tier-2 completeness semantics are unaffected.
