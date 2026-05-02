---
create_time: 2026-04-26 03:22:52
status: done
bead_id: sase-u
prompt: sdd/prompts/202604/instant_jk_navigation.md
---
# Plan — Instant `j`/`k` Navigation in the TUI

## Goal

Make `j`/`k` cursor movement in the sase TUI feel **instantaneous at all times**, including immediately after a
state-changing action (approve plan, kill agent, dismiss, accept proposal, sync, etc.). The user's perception target: no
detectable lag between keypress and cursor highlight motion, on any tab, regardless of what just happened.

## Problem statement

The TUI is a Textual app. j/k itself is cheap — the lag the user feels is **collateral damage from work the UI thread is
doing immediately before, after, or between keypresses**. Specifically:

1. **State-mutating actions block the event loop with disk I/O.** `action_toggle_approve` writes `agent_meta.json`
   synchronously on the main thread (`src/sase/ace/tui/actions/agents/_approve.py:54-70`). Similar patterns exist for
   dismiss/persistence elsewhere.
2. **Single-row state changes trigger full list rebuilds.** `_refresh_agents_display(list_changed=True)` after a
   kill/approve/dismiss rebuilds the entire grouping tree and re-renders every row, even though only one row's status
   actually changed (`src/sase/ace/tui/actions/agents/_killing.py:118-120`, `_approve.py:76`).
3. **Debouncing is non-uniform.** The Agents tab debounces detail-panel updates at 150 ms
   (`actions/agents/_display.py:121-154`); the ChangeSpecs and Axe tabs do **not** — every j/k synchronously refreshes
   their detail panes.
4. **Background polling competes with input.** A 10 s auto-refresh (`event_handlers.py:74-110`) calls
   `_load_agents_async`, `_poll_agent_completions`, etc. The disk reads run in `asyncio.to_thread`, but the post-load
   reconciliation and re-render run on the UI thread and can land mid-burst.
5. **Per-row render work is recomputed every frame.** `format_agent_option` and `format_banner_option` rebuild Rich
   `Text` objects from scratch on every list rebuild; nothing memoizes by stable inputs.
6. **No measurement.** There is no key-to-paint telemetry, so regressions today are invisible until a user feels them.

The plan addresses each of these in a phase. Phases are ordered so each one is shippable on its own and each later phase
benefits from (but does not require) earlier ones.

## Out of scope

- Rewriting the TUI in another framework. We stay on Textual.
- Visual/UX changes to j/k behavior beyond latency (no changes to navigation semantics, grouping, or selection model).
- Daemon/server-side changes (axe, agent runtime). All work is in `src/sase/ace/tui/`.
- Optimizing first-paint / cold-start time. Scope is steady-state navigation responsiveness only.

## Phasing

Five phases, each completed by a fresh agent instance. Each phase ends with:

- a working, mergeable change,
- a measurable latency improvement on the harness from Phase 1, and
- no regressions in `just check`.

---

### Phase 1 — Instrumentation & baseline harness

**Goal**: Make j/k latency measurable so subsequent phases can prove they helped.

**Deliverables**

- A lightweight key-to-paint timer wired into the TUI behind an env flag (e.g. `SASE_TUI_PERF=1`). On each j/k action,
  capture: `t_keypress` (action handler entry), `t_model_updated` (after `current_idx` mutation), `t_painted` (next
  Textual paint after the watch hook fires). Log p50/p95/max over a rolling window to a JSONL file at
  `~/.sase/perf/tui_jk.jsonl`.
- A scripted benchmark (`scripts/bench_tui_jk.py` or under `tests/`) that drives the TUI through Textual's `Pilot`: open
  Agents tab → press `a` (approve) → press `j` 20× → record latencies. Repeat for: kill, dismiss, ChangeSpecs
  accept-proposal, ChangeSpecs sync, Axe tab navigation.
- A short markdown report under `memory/long/` (or wherever benchmarks live) capturing the **baseline** numbers so later
  phases have something to compare against.

**Definition of done**: Running the bench prints a table of p50/p95/max key-to-paint latency for each scenario. Baseline
committed.

**Why first**: Every later phase claims an improvement. Without numbers, those claims are folklore.

---

### Phase 2 — Move all state-mutating I/O off the UI thread

**Goal**: No action handler does synchronous file I/O on the event loop. The UI thread mutates only the in-memory model
and schedules persistence asynchronously.

**Scope**

- `_approve.py`: move the `agent_meta.json` read-modify-write into an `asyncio.to_thread` (or Textual `Worker`).
  In-memory state and the optimistic UI update happen first; persistence reconciles errors via a toast/log.
- Audit and convert any other handler that touches disk on the main thread: dismiss, kill-persistence (already partially
  async — verify the rollback path), ChangeSpec accept-proposal, sync, hooks management, etc.
- Establish a small helper (e.g. `tui/util/io_async.py`) that wraps "optimistic mutate + background persist + error
  reconcile" so handlers stop reinventing the pattern.
- Ensure error paths (disk full, permission denied, race with another process) surface to the user without re-blocking
  the UI.

**Definition of done**: No synchronous `open(...)` / `json.dump` / `Path.write_text` in any TUI action handler. Bench
shows post-approve and post-dismiss j/k latency drops to baseline-no-action levels.

**Why early**: Eliminates the loudest single source of post-action lag and provides the helper that Phase 3 uses.

---

### Phase 3 — Selective row updates + render-result caching

**Goal**: A single-row state change (kill, approve, dismiss, status flip) updates only that row and any affected banner
— never rebuilds the entire OptionList.

**Scope**

- Introduce a `patch_agent_row(agent_id, ...)` API in the agents-display layer that replaces a single `OptionList`
  entry's prompt without invoking the grouping rebuild path. Use Textual's `OptionList.replace_option_at` (or
  equivalent), preserving cursor position and scroll offset.
- Update `_killing.py`, `_approve.py`, and any other caller currently using `_refresh_agents_display(list_changed=True)`
  for a **single** agent change to use the new patch path. Reserve full rebuild for true list-shape changes (agent
  added, group fold toggled, group-mode changed).
- Memoize `format_agent_option(agent)` and `format_banner_option(group)` keyed on a stable tuple (`agent_id`, `status`,
  `mtime`, `approved`, `runtime`, ...). The cache is invalidated only by patch operations that change those inputs. Cap
  with `functools.lru_cache(maxsize=...)` or a small custom dict keyed by agent id.
- Apply the same single-row patch idea to ChangeSpecs (status change) and Axe (job state change) where those tabs
  rebuild on single-row mutations.

**Definition of done**: After a kill/approve/dismiss, the list never re-renders rows whose model didn't change. Bench
shows post-kill p95 drops by ≥50 % versus Phase-2 baseline.

**Risk to watch**: Grouping/banner counts can desync if a patch changes group membership (e.g. status moves an agent
between groups). The patch helper must detect that case and fall back to a full rebuild.

---

### Phase 4 — j/k input coalescing & universal detail-panel debounce

**Goal**: Holding `j` or hammering it never queues up renders. The cursor highlight is always immediate; expensive
follow-up work (detail panel, footer, syntax highlighting) only runs once when input quiesces.

**Scope**

- Generalize the 150 ms debouncer in `actions/agents/_display.py` into a tab-agnostic `DetailPanelDebouncer`
  (`tui/util/debounce.py`) and apply to ChangeSpecs and Axe tabs.
- Coalesce j/k bursts at the action layer: if a j/k action fires while a previous detail-panel update is still pending,
  the cursor moves immediately but the detail update timer is reset, not stacked. Use a single shared timer per tab.
- Ensure the cheap path (cursor highlight, position counter) stays inline and cannot be starved by background work.
- For long holds, skip every detail-panel render except the final one. The user sees smooth cursor motion and exactly
  one detail-panel paint when they release the key.

**Definition of done**: Holding `j` for 1 s on any tab produces one detail-panel paint, not N. Bench shows
key-to-highlight p95 < 16 ms (one frame at 60 Hz) on all tabs.

---

### Phase 5 — Event-driven background refresh, pausable during input bursts

**Goal**: Background data refresh never blocks j/k. Refreshes are triggered by file-system events when possible, and
yield to active navigation when polling is unavoidable.

**Scope**

- Replace the 10 s `_on_auto_refresh` polling for agent state with an inotify-based watcher (Linux; gracefully degrade
  to polling on other platforms) on `~/.sase/agents/` or wherever artifacts live. On change, schedule reconciliation.
- Add a "user is navigating" gate: if a j/k event has fired within the last N ms (e.g. 250 ms), defer reconciliation
  until idle. This prevents background work from landing in the middle of a key burst.
- Keep all reconciliation work off the UI thread; only the final selective `patch_agent_row` (from Phase 3) touches the
  event loop.
- Audit the ChangeSpecs and Axe pollers similarly. Where inotify isn't appropriate (HTTP polling, etc.), at minimum
  ensure work is fully async and gated.

**Definition of done**: Bench scenario "press `j` continuously for 5 s while a background refresh would normally fire"
shows no latency spike. inotify watcher detects external file changes within ~50 ms.

**Risk to watch**: inotify on shared/network filesystems can miss events. Keep a slow polling fallback (e.g. once per
minute) as a safety net, gated by the same idle check.

---

## Sequencing & dependencies

- **P1 must land before any later phase.** Without the harness, the rest is unmeasured.
- **P2 → P3**: P3's selective patch path is much cleaner if persistence is already async (P2). Doable in either order
  but P2-first is much less merge pain.
- **P3 → P4**: P4 assumes the cheap path is genuinely cheap. If P3 hasn't landed, a stuck full-rebuild can still starve
  the cursor highlight.
- **P5 last**: it benefits most from the rest being in place. inotify before async I/O means inotify wakes a UI that's
  about to block on disk anyway.

Each phase is self-contained enough to hand to a fresh agent with: this plan, Phase-N's section, the harness numbers to
beat, and the scope file list. No phase requires holding the others' diff in context.

## Non-goals & explicit decisions

- **Don't rewrite the OptionList.** Textual's widget is fine; we use its `replace_option_at` API.
- **Don't introduce a new state-management library.** Stay on Textual reactives + the existing in-memory model.
- **Don't change keymaps or grouping behavior.** This is purely a latency project.
- **Don't add config knobs the user has to tune.** All thresholds (debounce ms, idle gate ms, lru sizes) are hard-coded
  with sensible defaults; revisit only if perf data shows it.

## Risks

- **Optimistic UI + async persist** can briefly show stale state if the persist fails. Phase 2 must surface failures as
  toasts and reconcile the model, not silently swallow.
- **Selective patches** can desync banner/group counts if a status change crosses groups. Phase 3 must detect and fall
  back.
- **inotify** is Linux-specific and quirky on networked FS. Phase 5 keeps a polling safety net.
- **Behavior under macOS/WSL** for inotify equivalents is the user's primary dev environment concern; verify both.

## Acceptance criteria (whole project)

- Bench p95 key-to-highlight latency: **< 16 ms** on every tab, in every scenario (post-approve, post-kill,
  post-dismiss, mid-poll, idle).
- No synchronous disk I/O on the UI thread in any TUI action handler.
- Single-row mutations never trigger full-list rebuilds.
- Background refreshes never spike j/k latency above the idle baseline.
- `just check` passes; no behavioral regressions in keymap, grouping, or selection.
