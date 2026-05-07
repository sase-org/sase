---
create_time: 2026-04-27 09:43:27
status: done
prompt: sdd/prompts/202604/ace_startup_perf.md
---
# Plan: Improve `sase ace` TUI Startup Performance

## Context

The user profiled `sase ace --profile` and the resulting trace (`.sase/home/tmp/sase/ace_profile_20260427_092858.txt`)
was reviewed end-to-end. Total recorded duration is 16.778s, but most of that is the asyncio event loop idling on
`epoll.poll` (8.66s) and `Runner.close` cleanup (3.10s). The _startup-relevant_ CPU work — what the user actually feels
as "the TUI is slow to come up" — is concentrated in two phases plus a recurring polling tick that fires while the user
is still waiting for the first paint to settle:

- `AceApp._on_compose`: ~115ms
- `AceApp.on_mount`: ~289ms
- First few `_on_auto_refresh` ticks: ~107ms each, on the main thread

A few additional inefficiencies exist deeper in the query evaluator that amplify per-changespec costs as the user's
project list grows. They aren't dominant today but compound with everything else.

The plan below is **phased by tier** so the highest-leverage / lowest-risk fixes can ship first and be measured
independently.

## Goals & Non-goals

**Goals**

- Cut at least 200–300ms off the combined `compose` + `on_mount` path on a representative run.
- Eliminate the 107ms-per-tick `load_notifications` cost on the main thread so the first 1–2 polling cycles after mount
  don't bleed into the startup feel.
- Make subsequent profiling actionable by extending the capture window to cover `AceApp.__init__` (currently the
  profiler starts after construction).

**Non-goals**

- Lazy-loading or restructuring the textual layout (compose).
- Touching the inotify-based artifact watcher, which already makes most refreshes event-driven.
- Touching disk I/O off the main thread that's already correctly wrapped in `asyncio.to_thread` — the on_mount author
  intentionally yields to keep the startup stopwatch ticking, and we must preserve that.
- Changing the public CLI surface (no new flags required for this work).

## Constraints (must preserve)

- `on_mount` keeps the event loop free between awaits so the `KeybindingFooter` startup stopwatch ticks at ~10Hz (see
  comment at `src/sase/ace/tui/actions/startup.py:382`). Optimizations must not move work _back_ onto the main thread.
- Runtime-uniform behavior across Claude/Gemini/Codex/external provider — no runtime-specific branches.
- New CLI args (if any) need short options. None expected here.
- Code-comment policy: only WHYs that aren't obvious from identifiers.

## Tier 1 — High impact, very low risk

These are pure waste: redundant work the code accidentally does twice.

### 1.1 Skip the saved-query fallback when the initial query already has results

**Where:** `src/sase/ace/tui/actions/startup.py:413` (the `if not self.changespecs:` guard) and
`src/sase/ace/tui/actions/changespec.py:300` (the `_try_startup_fallback_async` implementation).

**Observation:** The profile shows `_try_startup_fallback_async` accounting for 113ms of `on_mount`, dominated by
`_filter_changespecs` → `evaluate_query`. The on*mount handler already gates fallback behind `if not self.changespecs:`,
so the _path* is right — but inside `_try_startup_fallback_async` we still iterate slot order 1..9, 0, parse each saved
query, run `_filter_changespecs(self._all_changespecs)` per slot. With the default startup query `"!!!"` (matches CLs
with error suffixes), the gate usually short-circuits and 113ms isn't paid. The 113ms in this profile suggests the
user's startup query produced zero results that session.

**Action:** Confirm the gate is correct. The 113ms cost is "expected when fallback fires" rather than waste — but two
real wins exist inside `_try_startup_fallback_async`:

1. After a successful slot match, the function does `await asyncio.to_thread(self._read_changespecs_from_disk)`
   (changespec.py:340) even though `self._all_changespecs` is already populated and the slot was just matched against
   it. The disk re-read is unnecessary; pass the already-loaded list straight into `_apply_changespecs`.
2. Each slot iteration calls `_filter_changespecs(self._all_changespecs)` which itself calls
   `query_explicitly_targets_terminal/_submitted` — both of which rebuild a `name → status` map every call (see Tier 3
   below). Caching that map on `self._all_changespecs` for the duration of the fallback loop removes most of the 113ms.

**Expected savings:** 60–90ms on sessions where fallback fires; 0ms otherwise. **Risk:** very low — the change is a
memoization, not a behavior change.

### 1.2 Don't reload notifications in `_initialize_agent_tracking`

**Where:** `src/sase/ace/tui/actions/lifecycle.py:44` (`_initialize_agent_tracking`).

**Observation:** `on_mount` does:

```python
unread_ids = await asyncio.to_thread(self._read_unread_notification_ids)
self._initialize_agent_tracking(unread_ids)
```

`_read_unread_notification_ids` calls `load_notifications()`. Then `_initialize_agent_tracking` _also_ calls
`load_notifications()` on the main thread (lifecycle.py:61) just to compute priority/rest/muted counts — re-parsing the
same JSONL we just loaded off-thread. That's the 97ms in the profile, paid synchronously on the event loop.

**Action:** Refactor `_read_unread_notification_ids` (or introduce a sibling helper) to return the _full_
`list[Notification]` it already loaded, and have `_initialize_agent_tracking` accept that list. Compute the unread-id
set, priority/rest/muted counts in a single pass.

Concretely:

- Add `_read_notifications_for_startup()` that returns `(unread_ids, priority_count, rest_count, muted_count)` — runs
  off-thread.
- `_initialize_agent_tracking(state)` becomes a pure widget update.

**Expected savings:** ~95ms shaved off `on_mount`'s main-thread work. **Risk:** very low — the data flow is
straightforward and the function is called from exactly one place at startup.

### 1.3 Drop the redundant `load_keymap_registry({})` in `KeybindingFooter.__init__`

**Where:** `src/sase/ace/tui/widgets/keybinding_footer.py:53`.

**Observation:** Footer construction loads `default_config.yml` from `importlib.resources`, runs `yaml.safe_load`,
builds a registry — 35ms of `compose` time. Moments later in `on_mount`,
`footer.set_keymap_registry(self._keymap_registry)` overwrites it with the real registry built during `_init_app_state`.
Pure throwaway.

**Action:** Make the footer's registry attribute optional (`None` until `set_keymap_registry` is called). The `__init__`
line becomes `self._registry: KeymapRegistry | None = None`. Any read sites in `KeybindingFooter` already happen
post-mount, so the contract is "always set before render"; if any read site can fire pre-mount, gate it with an
`if self._registry is None: return` early-out.

**Expected savings:** ~35ms off `compose`, eliminates one yaml parse. **Risk:** low — confined to one widget; needs a
quick audit of read sites in `keybinding_footer.py` to confirm none fire before `set_keymap_registry`.

### 1.4 Cache the parsed `default_config.yml` at module level

**Where:** `src/sase/ace/tui/keymaps/loader.py:36` (`load_builtin_app_defaults`).

**Observation:** Even after fix 1.3, `load_keymap_registry` is called _once_ per process from `_init_app_state`. The
yaml parse itself is also called from test paths and possibly from agent runtimes via separate processes — but within a
single process, the file's contents never change.

**Action:** Memoize `load_builtin_app_defaults()` with `functools.cache`. Cheap insurance against future second-call
regressions and shaves the cost to zero on subsequent calls.

**Expected savings:** Defensive — 0ms today after 1.3, but locks in the win. **Risk:** negligible.

## Tier 2 — Medium impact, moderate scope

These touch hot paths used both at startup and during steady-state. Each should be measured before/after via
`--profile`.

### 2.1 Off-thread the periodic `_poll_agent_completions` reload

**Where:** `src/sase/ace/tui/actions/agents/_notifications.py:34` (`_poll_agent_completions`), invoked from
`src/sase/ace/tui/actions/event_handlers.py:104` (`_on_auto_refresh`).

**Observation:** Every `refresh_interval` seconds (default 10s) the polling tick spends ~107ms on the main thread
parsing the JSONL notifications file, running four list comprehensions over the result. With the inotify watcher already
wired up via `_start_artifact_watcher`, this poll is _backup_ work — but it currently blocks the event loop during the
same window the user is still settling into the TUI.

**Action:** Convert `_poll_agent_completions` into an async function that does
`notifications = await asyncio.to_thread(load_notifications)` and only returns to the main thread for the widget update
(`indicator.set_counts`, toast notifications). `_on_auto_refresh` already awaits its callbacks — verify it does,
otherwise schedule via `run_worker(thread=False)`.

**Expected savings:** 107ms off the main thread per tick. First tick after mount fires within seconds of startup in the
default config, so this directly improves "does the TUI feel alive after I launch it?". **Risk:** moderate —
`expire_due_snoozes` writes to disk inside the helper and the bell side-effect must remain ordered with the main-thread
widget update. Both naturally land on the main thread after the await; no extra synchronization needed. Worth a manual
smoke test with a real `~/.sase/notifications/notifications.jsonl`.

### 2.2 In-memory notification cache keyed by file mtime

**Where:** `src/sase/notifications/store.py` (new helper) and the two callers (`_initialize_agent_tracking`,
`_poll_agent_completions`, `_refresh_notification_count`).

**Observation:** `load_notifications` re-parses the entire JSONL file every call. The file is updated rarely
(notification arrival, dismiss, mark-read) but read often (every poll tick + every dismiss/mark-read flow). With ~100
notifications, this is a 50ms JSON parse + 20ms dataclass construction per call.

**Action:** Add a process-local cache that stat()s the file and returns the cached list when `mtime_ns` and `size` are
unchanged. Invalidate on any write via the existing rewrite/append paths (`append_notification`,
`_rewrite_notifications`). Keep the file lock semantics.

**Expected savings:** ~95ms per cache hit. Most importantly: makes `_refresh_notification_count` (called from many UI
flows) effectively free. **Risk:** moderate — concurrent writers in _other_ processes (e.g., a Telegram callback
updating a notification) need to invalidate too. The mtime check handles cross-process invalidation, but the granularity
of `mtime_ns` on some filesystems can be 1ms; a (size, mtime, inode) tuple is a safer key.

### 2.3 Skip the second `_filter_changespecs` in the saved-query fallback path

**Where:** `src/sase/ace/tui/actions/changespec.py:340`.

**Observation:** Inside `_try_startup_fallback_async`, after a slot wins, the code re-reads from disk and calls
`_apply_changespecs` which calls `_filter_changespecs` again — a second 37ms filter on top of the 113ms already spent
finding the winning slot. This duplicates fix 1.1's pass-through opportunity.

**Action:** Have the fallback path call `_apply_changespecs` directly with `self._all_changespecs` (already loaded),
skipping the disk re-read. The filter runs once, against the same data.

**Expected savings:** ~37ms on the fallback path. **Risk:** low — semantically equivalent.

## Tier 3 — Lower impact, cumulative

Per-changespec micro-costs that compound as project size grows. Smaller in this profile but cheap to fix and worth doing
while we're in this code.

### 3.1 Precompile regex patterns in `_get_base_status`

**Where:** `src/sase/ace/query/evaluator.py:148`.

**Observation:** Two `re.sub(...)` calls per status read, with the patterns recompiled (cached internally by `re`, but
with lookup overhead). Called for every changespec in two places per filter pass.

**Action:** Hoist patterns to module level: `_WORKSPACE_SUFFIX_RE` and `_LEGACY_READY_TO_MAIL_RE`, use `.sub` on the
compiled objects.

**Expected savings:** Small — measurable in microseconds per call but adds up across hundreds of changespecs and
multiple filter passes. **Risk:** none.

### 3.2 Cache `name → base_status` once per filter pass

**Where:** `src/sase/ace/query/evaluator.py:370` (`query_explicitly_targets_terminal`) and `:420`
(`query_explicitly_targets_submitted`).

**Observation:** Both functions iterate `all_changespecs` and call `_get_base_status` on each row to build a status_map.
The caller (`_filter_changespecs`) already iterates the same list to count reverted/submitted rows. Three full
iterations per filter where one would do.

**Action:** Compute the `name → base_status` map once in `_filter_changespecs` and pass it through to the two
`query_explicitly_targets_*` helpers as an optional argument. Falls back to building it locally when the helpers are
called from elsewhere (preserve their current API).

**Expected savings:** Small per-call (~5–10ms in this profile) but doubles when fallback fires. Real win is for users
with hundreds of changespecs. **Risk:** low — additive parameter with sensible default.

### 3.3 Cache project basename on `ChangeSpec` (or in `_get_searchable_text`)

**Where:** `src/sase/ace/query/evaluator.py:18`, `src/sase/ace/query/evaluator.py:178`.

**Observation:** `Path(changespec.file_path).parent.name` is built per changespec in `_get_searchable_text` and again
per row in `_match_project` when project filters are present. PosixPath construction is surprisingly expensive — 36ms in
the profile is pure pathlib churn.

**Action:** Two options, both reasonable:

- **Option A (preferred):** Add a cached property `project_name` on `ChangeSpec` that does the path split once. Reuses
  across the codebase (any other callsite that maps file_path to project gets the speedup).
- **Option B:** Memoize via a `functools.cache` on `_get_project_name(file_path: str)` in evaluator.py.

Either works; Option A is the better long-term home because file_path is immutable on a `ChangeSpec` instance, and other
code paths (display, hooks, etc.) likely repeat the same computation.

**Expected savings:** ~30ms in startup, more on filter-heavy workloads. **Risk:** low — `ChangeSpec` is a frozen-ish
dataclass; `cached_property` requires it not be `frozen=True`. Verify the dataclass kind before picking the storage. If
frozen, use Option B.

## Phase 4 — Measurement infrastructure

The profile starts at `ace_handler.py:59`, _after_ `AceApp(...)` is constructed. Anything done in `__init__` (notably
`_init_app_state`, which loads keymap registry, query_history, query_selections, snippets/xprompts, inactive_seconds
config, etc.) is invisible to the current profile.

**Action:** Move `profiler.start()` to immediately after the `pyinstrument` import and before `AceApp(...)` (around
`ace_handler.py:48`), so subsequent profiling runs capture the full picture. This is a small edit but it unblocks the
next round of optimization without guesswork.

This is independent of the code changes above and can ship in any commit; it should ship as part of this work so the
user can re-profile and verify.

**Risk:** none — pure observability change.

## Suggested ordering

A reasonable execution order, designed to keep each commit independently verifiable:

1. **Phase 4 first** (1 small commit). Re-profile to capture pre-change baseline including `__init__`.
2. **Tier 1 fixes** (1.2, 1.3, 1.4 in one commit; 1.1 separately because it changes flow inside
   `_try_startup_fallback_async`). Re-profile after each.
3. **Tier 2.1 + 2.3** (notification poll off-thread + skip duplicate filter).
4. **Tier 2.2** (notification cache) — optional if 2.1 already feels good.
5. **Tier 3** as a single follow-up commit, ideally with a new profile to confirm the cumulative savings.

## Estimated cumulative savings

- Compose: -35ms (1.3) → ~80ms total
- on_mount steady path (no fallback): -95ms (1.2) → ~190ms total
- on_mount fallback path: -95ms (1.2) -60ms (1.1) -37ms (2.3) → mid-90ms
- First poll tick after mount: -107ms off main thread (2.1)
- Deep filtering (large changespec lists): -30 to -50ms (3.x)

Total realistic shave on the user's profiled session: **~230–280ms** from startup, plus the more impactful "the TUI
feels alive immediately" win from moving the polling reload off-thread.

## Open questions / things to verify before coding

- Is `_on_auto_refresh` (`event_handlers.py:104`) already async, and does it `await` its callbacks? If yes, fix 2.1 is a
  one-liner; if no, the worker pattern from `_run_changespecs_async_refresh` is the template.
- Confirm `ChangeSpec` is not `frozen=True` before picking 3.3 Option A.
- Confirm `KeybindingFooter` has no read of `self._registry` between `__init__` and `set_keymap_registry()` (a quick
  grep should suffice).
- Re-profile after Phase 4 to see whether `AceApp.__init__` (specifically `_init_app_state`) is itself a hot spot worth
  a separate Tier-1.5 phase. Likely candidates inside it: `load_query_history`, `load_query_selections`,
  `load_dismissed_agents`, `get_xprompt_snippets`, `load_keymap_registry` — none of which are async and all of which run
  before the first paint can begin.
