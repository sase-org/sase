---
create_time: 2026-07-03 06:53:37
status: wip
prompt: sdd/prompts/202607/timezone_runtime_consistency.md
---
# Plan: Fix running-agent runtime (and all other timezone bugs) on machines whose system tz differs from the configured tz

## Background

A screenshot of `sase ace` (2026-07-03) shows an agent that started at `06:24:06` local wall clock displaying a runtime
of **4h02m** two minutes later, and its reply divider showing **10:24:49** instead of `06:24:49`. The host's system
timezone is `Etc/UTC` while `~/.config/sase/sase.yml` sets `timezone: "America/New_York"` — a 4-hour offset (EDT),
matching both symptoms exactly.

**Root cause:** the codebase has two competing notions of "local time":

1. **Configured tz** — `sase.core.time.get_timezone()` (config key `timezone`, default `America/New_York`).
   `generate_timestamp()` (`src/sase/core/time.py:25-31`) and `create_artifacts_directory` (`src/sase/artifacts.py:66`)
   mint naive `YYmmdd_HHMMSS`/`YYYYmmddHHMMSS` wall-clock strings in this tz (agent name suffixes, artifacts dir names).
   Agent meta timestamps (`run_started_at`, `stopped_at`, plan/feedback/retry times) are _written_ as aware-UTC ISO
   (`src/sase/axe/run_agent_markers.py:36,143`) and _normalized_ to naive configured-tz wall time for the Agents model
   by `parse_utc_to_eastern` (`src/sase/ace/tui/models/_loaders/_meta_enrichment_common.py:36-39`, used by
   `_meta_enrichment_wire.py` and `_meta_enrichment_filesystem.py`). So every naive datetime in the Agents model is a
   **configured-tz wall time**.
2. **System tz** — bare `datetime.now()`, argument-less `.astimezone()`, and tz-less `datetime.fromtimestamp()`.

Any arithmetic or comparison mixing the two is wrong by the offset between the timezones. The headline bug is
`compute_row_runtime` (`src/sase/ace/tui/models/agent_time.py:388`): `reference = datetime.now()` (system) minus
`agent.run_start_time` (naive configured-tz) → `4h02m` for a 2-minute-old agent. The reply divider bug is
`render_timestamp_divider` (`src/sase/ace/tui/widgets/prompt_panel/_agent_display_content.py:41`): `dt.astimezone()`
with no argument converts the aware-UTC transcript timestamp to the **system** tz.

Most of the repo already follows the correct pattern — naive wall time interpreted via `.replace(tzinfo=get_timezone())`
and referenced against `datetime.now(get_timezone())` (`src/sase/ace/hooks/ timestamps.py:42-97`,
`src/sase/ace/tui/widgets/_axe_dashboard_render.py`, `src/sase/axe/run_agent_runtime.py:36-66`,
`src/sase/logs/daterange.py`, notifications, etc.). This plan brings the divergent sites onto that convention.

A prior tale (`sdd/tales/202605/datetime_timezone_crash.md`) documented the mixed conventions and set non-goals we keep
honoring: the Agents model stays **naive local**; stored timestamp formats are not overhauled. This plan's change is to
pin "local" to mean _the configured timezone, everywhere_ — never the system clock.

**Rust core boundary note:** `sase-core` treats all of these timestamps as opaque strings. The agent scanner passes
`run_started_at`/`stopped_at` through verbatim (`crates/sase_core/src/agent_scan/scanner.rs:758-759`) and the launch
planner parses `YYmmdd_HHMMSS` only for relative batch-offset math
(`crates/sase_core/src/agent_launch/mod.rs: 247-258`). Timezone interpretation lives entirely in this repo's Python;
**no `sase-core` changes are required**.

## Goals

1. Runtime suffixes, duration displays, wait countdowns, `age>`-query filtering, and BY_DATE grouping are correct on any
   machine, regardless of the relationship between system tz and configured tz.
2. Exactly one definition of "local": the configured timezone. Every wall-clock _generation_ site and every
   _reference-now_ comparison uses it; every aware→display conversion targets it.
3. Portable default: when `timezone` is not configured, SASE uses the **system** timezone instead of assuming
   `America/New_York` — machines that don't share our timezone assumptions get sensible behavior out of the box.
   (Explicit configs, like the one on the affected host, are unaffected.)
4. A test fixture that pins system tz ≠ configured tz, so this bug class can never pass the suite silently again.

## Non-goals

- Converting the Agents model (or any model) to aware datetimes, or changing stored timestamp formats (agent meta stays
  aware-UTC ISO; name/dir timestamps stay naive configured-tz strings) — per the 202605 tale.
- Exact durations across a DST transition hour: naive wall-clock subtraction can skew by ±1h during the transition
  itself, same as today. `format_compact_duration` already clamps negatives to 0. Accepted.
- Same-process cache-age/task-elapsed arithmetic where both sides are bare `datetime.now()` from the same process
  (file-panel fetch ages, TUI task queue, quit-confirm elapsed): correct as-is, left untouched.
- Multi-host artifact sharing semantics (a `~/.sase` state dir is per-host; naive wall times are interpreted in that
  host's configured tz).

---

## Part A — `sase.core.time` becomes the single source of "local"

### A1. New helpers in `src/sase/core/time.py`

- `local_now() -> datetime` — `datetime.now(get_timezone()).replace(tzinfo=None)`: the naive configured-tz "now" every
  mixed-domain site below switches to.
- `to_local(dt: datetime) -> datetime` — aware → convert to configured tz and strip tzinfo; naive → return as-is
  (already local by convention). This becomes the shared normalizer; `parse_utc_to_eastern` is renamed
  `parse_utc_to_local` and implemented on top of it (keeping its `lru_cache`d tz lookup for the hot enrichment path, see
  A3).
- `local_timezone_name() -> str | None` — the IANA key of the configured tz (for injecting `TZ=` into generated shell,
  Part E); `None` when the resolved tz has no IANA key (fixed-offset fallback), in which case callers omit the `TZ=`
  override and inherit the system tz.

### A2. Default timezone = system timezone

`get_timezone()` (`src/sase/core/time.py:20`) currently falls back to `America/New_York`. Change resolution order to:

1. `timezone` key from merged config (unchanged).
2. System timezone: `TZ` env var when it names a valid IANA zone, else the `/etc/localtime` symlink target
   (`.../zoneinfo/<Area>/<City>` → `ZoneInfo`), else `datetime.now().astimezone().tzinfo` as a fixed-offset last resort
   (no new dependency). Widen the return annotation from `ZoneInfo` to `tzinfo` if the last-resort branch requires it;
   all call sites only use it as a `tzinfo`.

Update the schema default/description (`src/sase/config/sase.schema.json:876-880`) and `docs/configuration.md`
(~line 874) to say "defaults to the system timezone". No existing test hard-codes Eastern-default behavior (the
`logs/daterange` and `run_agent_runtime` tests recompute via `get_timezone()`), so this is safe.

### A3. Cache handling

Two caches memoize the tz: the module global `_cached_timezone` in `core/time.py:6` and the `@lru_cache` wrapper in
`_meta_enrichment_common.py:31-33`. Add a `reset_timezone_cache_for_tests()` in `core/time.py` that clears both (the
enrichment module registers its cache-clear with core/time, or the test fixture clears both explicitly). Runtime
behavior (cache-once-per-process) is unchanged.

## Part B — Fix every mixed-domain "now" reference (the screenshot bug)

Replace bare `datetime.now()` defaults/references with `local_now()` at the sites that compare against naive
configured-tz model datetimes:

**Runtime / duration / countdown:**

- `src/sase/ace/tui/models/agent_time.py:67,107,141,388` — wait target reference, `_reference_for_target`,
  `_format_finish_timestamp`, `compute_row_runtime`. Also the no-arg `reference.astimezone()` at `:60` and `:110`
  (aware-target/naive-reference reconciliation) → `astimezone(get_timezone())`.
- `src/sase/ace/tui/models/agent.py:490` — `duration_display`.
- `src/sase/ace/tui/models/workflow.py:73` — `duration_display` (workflow `start_time` primarily comes from the
  artifacts dir name = configured tz, so this is live-wrong today, not just cosmetic).
- `src/sase/ace/tui/actions/agents/_display_panel_patches.py:166` — live RUNNING-row runtime patching.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py:312` — wait-floor countdown.
- `src/sase/ace/tui/modals/runners_modal.py:113` — runner elapsed (start parsed from `YYmmdd_HHMMSS` at
  `_runners_data.py:64`).
- `src/sase/ace/tui/modals/agent_run_log_modal.py:122-137` — Today/Yesterday bucketing of `agent.start_time`.
- `src/sase/ace/tui/modals/wait_modal.py:111` — naive-target branch of `_format_wait_until_token`.

**`age>` agent-query filtering:**

- `src/sase/ace/tui/actions/agents/_loading_finalize.py:284` and `_loading_compute_finalize.py:110` — the `now` passed
  into `evaluate_agent_query` (feeds `_match_duration`'s `now - agent.start_time`).

**BY_DATE group bucketing (default references feeding `date_bucket_for` / `date_bucket_for_changespec`):**

- `src/sase/ace/tui/models/agent_groups/_tree.py:92,201`
- `src/sase/ace/tui/models/agent_groups/_keys.py:198,228`
- `src/sase/ace/tui/models/changespec_groups/_tree.py:55,134`

Tests that inject explicit `now=` values keep working unchanged (the parameter semantics become "naive configured-tz
now", which is what their fixed naive datetimes already model).

## Part C — Fix display conversions that target the system tz

Convert aware/epoch values to the configured tz for display, matching the existing `format_local_hhmmss` pattern
(`src/sase/ace/tui/widgets/prompt_panel/_agent_context_common.py:61-76`):

- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_content.py:41` — `render_timestamp_divider`:
  `astimezone(get_timezone())` (fixes the `10:24:49` reply divider). Same at `:132`.
- `src/sase/ace/tui/models/agent_attempt.py:81,85` — `start_datetime`/`end_datetime`:
  `datetime.fromtimestamp(epoch, get_timezone())` (strip tzinfo to preserve the naive-model convention for any
  comparisons), which also fixes `start_hhmmss`.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_attempts.py:158` — attempt end-time rendering, same change.
- `src/sase/telemetry/charts.py:56` — chart x-axis labels from epochs.

`src/sase/ace/tui/modals/logs_pane.py:70` stays as-is (explicitly labeled UTC).

## Part D — Generate wall-clock values in the configured tz

- **`%wait(time=...)` targets** (`src/sase/xprompt/_directive_time.py:53-73`): build targets and the past-check against
  `local_now()` so `%wait(time=1430)` means 14:30 on the user's configured clock, not the server's system clock. Stored
  `wait_until` stays a naive ISO string (format unchanged); readers' naive branches switch to the configured-tz
  reference: `remaining_until` (`src/sase/axe/run_agent_wait.py:26`), `wait_modal.py:111` and the `agent_time.py` sites
  already covered in Part B. The aware-UTC `wait_until` written at `run_agent_wait.py:162-164` already round-trips
  correctly through every reader's aware branch — unchanged.
- **TUI-launched workflow artifacts dirs** (`src/sase/ace/tui/actions/agent_workflow/_workflow_exec.py:211,325`):
  `datetime.now().strftime("%Y%m%d%H%M%S")` → configured tz, matching `artifacts.py:66`. (These dir names are later
  parsed as configured-tz by `parse_timestamp_14_digit` — today they're minted in system tz, skewing
  `Workflow.start_time`.)
- **Workflow state `start_time` writers** (`src/sase/xprompt/workflow_executor.py:104`,
  `src/sase/xprompt/workflow_runner.py:325`, `src/sase/axe/run_workflow_runner.py:60`): `local_now().isoformat()` —
  still a naive ISO string (no format change), now in the same domain as the dir-name primary source and the fixed
  `duration_display`.
- **Shard-fallback and filename timestamps** (consistency): `src/sase/core/paths.py:218`,
  `src/sase/ace/dismissed_agents_paths.py:21`, `src/sase/main/ace_handler.py:27`, `src/sase/xprompt/models.py:251`,
  `src/sase/integrations/chat_install.py:345`, `src/sase/status_state_machine/transitions.py:124` (log line),
  `src/sase/integrations/_chat_install_worker.py:103` (log line), `src/sase/ace/revert_agent_marker.py:60` (write-only
  marker) → `local_now()` / `generate_timestamp()`.

## Part E — Hook wrapper script: drop the hardcoded Eastern

`src/sase/ace/hooks/execution.py:111` bakes `TZ="America/New_York"` into the generated bash wrapper; its `END_TIMESTAMP`
is later diffed against the hook's start timestamp minted via `get_current_timestamp()` (configured tz) by
`calculate_duration_from_timestamps` (`src/sase/ace/hooks/timestamps.py:78-97`) — wrong duration whenever the configured
tz isn't Eastern. Interpolate `local_timezone_name()` into the script instead; when it returns `None` (fixed-offset
fallback ⇒ configured == system), emit plain `date` with no `TZ=` override.

## Part F — Latent naive/aware crash + hardening

- `src/sase/logs/run_log.py:178-182`: `_parse_event_timestamp` returns naive (strptime at `:125`) but `--since` from
  `parse_daterange` is aware configured-tz → `ts < since` raises `TypeError`. Attach `get_timezone()` to the parsed
  value (the write side `:76,110` already mints it in configured tz).
- `src/sase/ace/tui/thinking/session_resolver.py:104`: `since.timestamp()` interprets a naive `since` in system tz
  before comparing to file mtimes. No production caller passes `since` today; harden anyway by interpreting naive input
  as configured tz (`replace(tzinfo=get_timezone()).timestamp()`).

## Part G — Naming and stale-comment cleanup

- Rename `parse_utc_to_eastern` → `parse_utc_to_local` (callers in `_meta_enrichment_wire.py`,
  `_meta_enrichment_filesystem.py`, `_meta_enrichment_common.py`).
- Fix stale tz references: `src/sase/artifacts.py:51` docstring ("NYC Eastern timezone"),
  `src/sase/logs/ daterange.py:4-5` module docstring and format comments ("resolve to Eastern" → "resolve to the
  configured timezone"), `src/sase/ace/hooks/execution.py:110` comment.

---

## Testing

**New tz-divergence fixture** (e.g. `tests/conftest.py` or a dedicated helper): monkeypatches the configured tz to a
fixed zone (`America/New_York`) while forcing the system tz to a different one (`monkeypatch.setenv("TZ", "UTC")` +
`time.tzset()`, restored afterward), clearing both tz caches via `reset_timezone_cache_for_tests()`. This is the fixture
that makes the bug class visible: today no test pins system ≠ configured tz.

**Regression tests (fail before the fix, pass after):**

- The screenshot bug: an agent enriched with an aware-UTC `run_started_at` of "2 minutes ago" shows `2m` (not `4h02m`)
  from `compute_row_runtime` under the divergence fixture; same via the live-row patching path
  (`_display_panel_patches`).
- `render_timestamp_divider` renders the configured-tz clock for an aware-UTC transcript timestamp.
- `Workflow.duration_display` with a dir-name-derived start under divergence.
- `%wait(time=HHMM)` produces a target on the configured clock; `remaining_until` agrees.
- BY_DATE bucketing: an agent started "today" in the configured tz but "yesterday"/"tomorrow" in system tz lands in
  Today.
- `age>` query filtering under divergence.
- Attempt-record `start_hhmmss` renders configured-tz wall time from an epoch.
- Hook wrapper script embeds the configured tz name (string assertion on the generated script), and
  `calculate_duration_from_timestamps` round-trips with `get_current_timestamp()`.
- `get_timezone()` default resolution: with no `timezone` config and `TZ=Europe/Berlin`, returns Berlin; config still
  wins when set.
- `logs/run_log.py` `--since` filtering no longer raises on naive event timestamps.

**Existing suites:** the `now=`-parameterized tests (agent-list runtime, group-mode date, changespec buckets) keep their
fixed naive datetimes; `tests/logs/test_daterange.py` and `tests/test_agent_runtime.py` recompute via `get_timezone()`
and stay green.

Run `just install`, then `just check` (and `just test-visual` is unaffected — no rendering-geometry changes).

## Docs

- `docs/configuration.md` `timezone` entry: new default ("system timezone"), plus a sentence on what the setting governs
  (all SASE wall-clock display and timestamp generation).
- `src/sase/config/sase.schema.json` `timezone` description/default updated to match.

## Risks & edge cases

- **In-flight values at upgrade:** naive `wait_until` targets and workflow-state `start_time` ISO strings written before
  the fix were minted in the _system_ tz; after the fix they're interpreted as configured-tz. Only pending wait floors
  and currently-running workflows at upgrade time are affected (bounded, self-healing); accepted.
- **Default change visibility:** hosts with no `timezone` config and a non-Eastern system tz stop seeing Eastern wall
  clocks — that is the intended portability fix. Hosts with explicit config (including the affected one) see no
  default-related change.
- **Fixed-offset fallback:** when the system tz can't be resolved to an IANA zone, `get_timezone()` returns a
  fixed-offset `tzinfo`; `local_timezone_name()` returns `None` and the hook script omits `TZ=`. All arithmetic still
  works; only DST-awareness degrades in that corner.
- **`lru_cache`/global tz caches:** cleared via the new test hook; runtime semantics (config read once per process)
  unchanged.
- **DST transition hour:** naive wall-clock deltas can be off by ±1h during the transition itself (pre-existing;
  negatives clamp to `0s`). Documented, not fixed here.

## Acceptance criteria

1. On a host with system tz UTC and `timezone: "America/New_York"`, a RUNNING agent launched ~2 minutes ago shows a
   `2m`-ish runtime suffix in the Agents tab (not `4h02m`), and it ticks correctly under auto-refresh.
2. Reply-panel timestamp dividers show the configured-tz clock (`06:24:49`, not `10:24:49`) on the same host.
3. `%wait(time=1430)` waits until 14:30 on the configured clock; the WAITING row countdown matches.
4. BY_DATE agent/CL grouping and `age>` queries bucket/filter by the configured-tz calendar.
5. Hook durations are correct with any configured tz (no Eastern hardcode in the generated wrapper).
6. With `timezone` unset, SASE uses the system timezone everywhere (verified by the default-resolution tests).
7. `just check` passes; the new divergence-fixture regression tests fail when run against pre-fix code.
