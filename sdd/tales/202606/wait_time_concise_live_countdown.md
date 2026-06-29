---
create_time: 2026-06-29 10:30:07
status: done
prompt: sdd/prompts/202606/wait_time_concise_live_countdown.md
---
# Concise, live countdown for time-floored `%wait` agents

## Problem & product context

When an agent is launched with the `%wait` directive using the `time` keyword argument (e.g. `%wait(time=1430)` for an
absolute-time floor, or `%wait(time=5m)` for a duration floor), it sits in the `WAITING` status until both (a) every
agent it is waiting on has finished and (b) the time floor has passed.

Today the root agent row for such an agent renders a verbose, **static** status, e.g.:

```
actstat (WAITING (until 14:15, 1m29s)) 09y.f1
```

This has two shortcomings:

1. **Too verbose once dependencies are done.** Once the agents being waited on have all completed (or there were none),
   the only remaining thing the agent is blocked on is the time floor. At that point the `(until 14:15, …)` framing is
   noise — the user just wants to know how long is left.
2. **Not live.** The `1m29s` figure is frozen at whatever it was when the row was last fully rebuilt; it does not tick
   down second-by-second.

### Desired behavior

When an agent is `WAITING` on a `time=` floor **and all agents it is waiting for (if any) are done**, the row should
show a concise, live countdown:

```
actstat (WAITING 1m29s) 09y.f1
```

- No `until 14:15`, no nested parens around the duration — just `WAITING <remaining>`.
- The `<remaining>` value counts **down live, every 1 second**.
- "if any" means: an agent with a `time=` floor and **no** `%wait` agent dependencies also qualifies for the concise
  form immediately.

When dependencies are **not** all done yet, the row keeps the current verbose form (`WAITING (until 14:15, 1m29s)`) so
the user still sees the absolute time floor while the agent is blocked on its peers.

The richer **detail panel** field (`Wait: 09y ✓ + until 14:15 (1m19s left)`) is intentionally **out of scope** and left
unchanged — it is the authoritative, fully-expanded view. This change only affects the compact agent-row status string
on the Agents tab.

## Background: how the relevant pieces work today

This is a **presentation-only TUI change** (Textual rendering + render cache). It does not cross the Rust-core backend
boundary: the launch-gating logic that actually decides when a waited agent starts is untouched. We only change how an
already-`WAITING` row is _displayed_, reusing status information the TUI already has.

Key existing mechanics, all in `src/sase/ace/tui/`:

- **Row status text** is built in `widgets/_agent_list_render_agent.py` (`format_agent_option`). The `WAITING` branch
  currently always renders `(until <label>, <dur>)` when `wait_until` is set, and `(<dur>)` only when `wait_duration` is
  set _and there are no dependencies_. The remaining duration is computed there from `wait_until` / `wait_duration`.

- **Wait data model** lives on `Agent` (`models/agent.py`): `waiting_for: list[str]`, `wait_until: str | None` (ISO 8601
  absolute target), `wait_duration: float | None` (seconds), plus `start_time`. These are populated by the loader from
  `waiting.json` / `agent_meta.json` (`models/_loaders/_meta_enrichment_filesystem.py`). `waiting_for` is **not**
  cleared when dependencies complete — the screenshot's `09y ✓` proves the name stays and is shown as done via a status
  badge.

- **Time helpers** live in `models/agent_time.py`: `wait_until_target_and_reference()` (accepts an optional `now`),
  `format_wait_until()`, `format_compact_duration()`, and `runtime_suffix_ticks()` — the predicate that decides whether
  a row's right-side runtime suffix changes each second.

- **The per-second "live" mechanism** is already fully wired:
  - A 1s `set_interval` timer (`actions/_startup_mount.py`) fires `_on_countdown_tick` (`actions/_event_activity.py`),
    which on the Agents tab calls `_patch_agent_runtime_rows()` (`actions/agents/_display_panel_patches.py`).
  - That calls `AgentList.patch_active_runtime_rows(now)` (`widgets/agent_list.py`), which patches each row where
    `runtime_suffix_ticks(agent)` is `True`, via the selective `patch_row` fast path (`widgets/_agent_list_build.py`) —
    **not** a full rebuild.
  - The render cache (`widgets/_agent_list_render_cache.py`) only folds the quantized `now` into a row's cache key when
    that row is "time-sensitive" (`runtime_suffix_ticks(agent)` is `True`). Otherwise the cached render is reused and
    the displayed value is frozen.

- **Why the countdown is static today:** for a _pre-run_ `WAITING` agent (`run_start_time is None`, the normal case for
  a deferred `%wait` launch), `runtime_suffix_ticks()` returns `False`. So the row is neither folded with `now` in its
  cache key nor patched each second → the duration string never advances.

- **Dependency "done" status** is already computed for the detail panel via `_collect_agent_status_buckets()` /
  `agent_status_buckets_for_app()` (`agent_completion.py`), which maps each prompt-referenceable agent name to a status
  _bucket_ (`Running` / `Starting` / `Waiting` / `Done` / `Stopped` / `Failed`), using family-aware precedence. The
  detail panel shows the `Done` bucket as a `✓` badge. We reuse the same source of truth for "all dependencies done".

## High-level design

Three coordinated pieces: (1) decide when to render the concise form, (2) render it, and (3) make it tick live.

### 1. Determine "all waited-for dependencies are done"

Add a small helper (next to the existing bucket logic in `agent_completion.py`), e.g.
`wait_dependencies_satisfied(agent, status_buckets) -> bool`:

- Returns `True` when `agent.waiting_for` is empty ("if any").
- Otherwise returns `True` only when **every** name in `waiting_for` maps to the `Done` bucket in the supplied
  `status_buckets` map.
- Conservative on missing info: an unknown/absent name (or a `None` map) is treated as _not_ done → verbose form. This
  mirrors the detail panel's `?`/non-`✓` semantics and avoids ever claiming "done" when we can't confirm it.

The status-bucket map is computed **once per full row build** (the build already has the full agent set available via
the widget's app — the same source the detail panel uses), so it stays O(n) per rebuild and adds nothing to the
per-second tick path.

### 2. Render the concise vs. verbose form

In `format_agent_option` (`_agent_list_render_agent.py`):

- Add a keyword-only parameter `wait_deps_satisfied: bool | None = None`. When `None` (ad-hoc callers / tests with no
  bucket info), derive a safe default from the agent itself: satisfied iff `not agent.waiting_for`. The real value is
  threaded in from the build.
- Factor the "seconds remaining on the time floor" computation into a reusable
  `agent_time.wait_remaining_seconds(agent, now)` helper that handles both `wait_until` (absolute) and
  `wait_duration + start_time` (relative), threading the caller's `now` so the value is deterministic and consistent
  with the cache key (today the row ignores the passed `now` and calls `datetime.now()` directly).
- New `WAITING` rendering logic:
  - If there is a positive remaining time floor **and** `wait_deps_satisfied`: render the concise
    `WAITING <format_compact_duration(remaining)>` (no `until`, no extra parens), in the existing amethyst style. This
    single branch covers both the absolute and the relative time-floor cases uniformly.
  - Else if `wait_until` is set (deps still pending): keep the current verbose `WAITING (until <label>, <dur>)` /
    `WAITING (until <label>)` form.
  - Else (relative wait with pending deps): unchanged from today (no extra text).

Thread the new parameter through the memoized wrapper `cached_format_agent_option` as well.

Note: a deliberate, minor consistency change falls out of this — a _no-dependency_ `wait_duration` agent currently
renders `WAITING (1m29s)`; it will now render the unified `WAITING 1m29s`. This matches the requested format and is
intended.

### 3. Make the countdown tick live

- Add `agent_time.wait_countdown_ticks(agent) -> bool`: `True` when the agent is `WAITING` and has a time floor
  (`wait_until`, or `wait_duration` with a `start_time`). This is intentionally scoped to _time-floored_ waits, so a
  plain `WAITING` agent with no time floor still does **not** tick (preserving
  `test_patch_active_runtime_rows_skips_waiting_without_run_start`).
- Introduce a combined "row repaints each second" predicate (e.g.
  `row_runtime_or_wait_ticks(agent) = runtime_suffix_ticks(agent) or wait_countdown_ticks(agent)`) and use it in the two
  places that currently gate on `runtime_suffix_ticks`:
  - **Cache key** (`_agent_list_render_cache._runtime_signature`): use it as the `time_sensitive` gate so a time-floored
    `WAITING` row folds the quantized `now` into its key and re-renders each second.
  - **Patch loop** (`agent_list.patch_active_runtime_rows` / `AgentList._runtime_suffix_ticks`): so these rows are
    included in the per-second patch pass.
- Keep `runtime_suffix_ticks` itself unchanged in meaning (it governs the right-aligned runtime suffix and the
  unread/paused marker logic in `_agent_list_render_layout.py`). Using a _separate_ predicate avoids side effects there
  (e.g. unread markers) and keeps the right-side suffix empty for pre-run waits, exactly as today (`compute_row_runtime`
  still returns nothing for a pre-run `WAITING` agent).

A welcome side effect: the **verbose** form's trailing duration will now also tick live for deps-pending time-floored
waits — consistent and strictly better than the current frozen value.

### Cache & patch wiring details

- Add `wait_deps_satisfied` to the explicit `agent_render_key` tuple so a deps-done transition (recomputed on the next
  full build) busts the row's cached render and flips it from verbose to concise.
- Store the per-row `wait_deps_satisfied` in the build's `_row_render_ctx` so the single-row `patch_row` path reuses the
  same value when patching each second. (The deps-done value is refreshed on full rebuilds, which already happen on
  status changes; the per-second tick only needs to advance the clock, so reusing the last-built value is correct and
  cheap.)

## Files to change (approximate)

- `src/sase/ace/tui/models/agent_time.py` — add `wait_remaining_seconds`, `wait_countdown_ticks`, and the combined
  per-second predicate.
- `src/sase/ace/tui/models/agent.py` — re-export the new helpers alongside the existing `agent_time` re-exports.
- `src/sase/ace/tui/agent_completion.py` — add `wait_dependencies_satisfied` (and expose the bucket-collection it
  needs).
- `src/sase/ace/tui/widgets/_agent_list_render_agent.py` — new `WAITING` rendering branch; `wait_deps_satisfied`
  parameter on `format_agent_option` / `cached_format_agent_option`; use `wait_remaining_seconds(agent, now)`.
- `src/sase/ace/tui/widgets/_agent_list_render_cache.py` — fold `now` for time-floored `WAITING` rows; add
  `wait_deps_satisfied` to the render key.
- `src/sase/ace/tui/widgets/_agent_list_build.py` — compute the status-bucket map once; derive per-row
  `wait_deps_satisfied`; pass it into the renderer; store it in `_row_render_ctx`; forward it from ctx in the
  `patch_row` path.
- `src/sase/ace/tui/widgets/agent_list.py` — include time-floored waits in `patch_active_runtime_rows`.

## Edge cases

- **No dependencies, only a time floor** → concise form immediately ("if any").
- **Dependency failed / stopped (no successful done member)** → bucket is not `Done` → verbose form retained (it is not
  "done" per the requirement).
- **Unknown / not-yet-loaded dependency name** → treated as not done → verbose form.
- **Time floor already elapsed** (`remaining <= 0`) → no countdown rendered (bare `WAITING`); this is a sub-second
  transient before the backend launches the agent and triggers a full rebuild.
- **Family waits** → handled by the existing family-aware bucket precedence; a family counts as done only when it has a
  successful terminal member and no active member.

## Testing strategy

Unit tests (no full TUI app needed; drive the pure render/predicate functions with a fixed `now` for determinism):

- `format_agent_option` rendering:
  - `wait_until` + deps satisfied (or no deps) → `WAITING <dur>`, asserts no `until` / no double parens.
  - `wait_until` + deps pending → verbose `WAITING (until HH:MM, <dur>)` retained.
  - `wait_duration` + no deps → concise `WAITING <dur>`.
- `wait_dependencies_satisfied`: empty `waiting_for` → True; all-`Done` deps → True; any non-`Done`/unknown dep → False.
- `wait_countdown_ticks`: True for `WAITING` with `wait_until` and for `WAITING` with `wait_duration + start_time`;
  False for plain `WAITING` with no floor and for non-`WAITING` statuses.
- Tick/patch behavior (extend `tests/ace/tui/widgets/test_agent_list_runtime_patching.py`): a `WAITING` agent with a
  time floor **is** patched by `patch_active_runtime_rows`; the existing "skips waiting without run start (and no
  floor)" test still passes.
- Render-cache behavior (extend `tests/ace/tui/widgets/test_agent_render_cache.py` / `test_agent_render_key_core.py`):
  the key changes across consecutive seconds for a time-floored `WAITING` row (live tick), and changes when
  `wait_deps_satisfied` flips (verbose → concise).
- Update any existing assertions that expect the old `(until …)` / `(1m29s)` text for the now-concise no-dependency
  cases.

Then run `just check` (`just install` first, per repo workflow) to confirm lint, types, and tests — including the PNG
snapshot suite — pass.

## Out of scope

- The agent detail-panel `Wait:` field rendering and its countdown.
- Any change to backend launch-gating / when a waited agent actually starts.
- Changing `%wait` parsing, `waiting.json`, or the wait data model.
