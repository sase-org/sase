---
title: Provider usage
description:
  Subscription usage reporting and automatic provider disabling at usage limits.
---

# Provider usage

This page describes provider usage reporting and usage-limit behavior.

## Subscription Usage

Subscription usage is a machine-local view of provider allowance windows — for example,
the remaining share of a session or weekly plan window. It is separate from per-agent
[token usage](../../contribute/llm-invocation.md#token-usage-tracking) and from
[usage-limit auto-disable](#usage-limit-auto-disable): collecting a low observation does
not itself disable routing.

Collection is on by default and controlled by the durable
`llm_provider.usage_metrics.enabled` preference:

```yaml
llm_provider:
  usage_metrics:
    enabled: true
    indicator:
      enabled: true
      default: { below_remaining_percent: 20 }
      weekly_all: always
      providers:
        muse:
          windows:
            session: never
```

Claude, Codex, Grok, Muse Code, and Antigravity currently ship collectors. Claude can
also persist fenced rate-limit events from its normal stream; Codex, Grok, Muse, and agy
are probe-only. Muse's probe is free: it reads the `muse serve` host's usage through an
`echo`-provider session, so it makes no model call and spends no tokens. Antigravity's
probe is likewise free: it runs `agy -p /usage` in plan/sandbox print mode
(`agy >= 1.1.11`), which answers without starting a model turn. Its four windows —
Gemini weekly and 5-hour plus Claude/GPT weekly and 5-hour — are `model_family` scoped
to `gemini` and `3p`. Other provider plugins remain fully usable when they do not
implement usage hooks. Per-provider collection can be disabled with
`llm_provider.usage_metrics.providers.<name>.enabled: false`; routing-disabled providers
still collect when otherwise eligible because their reset information remains useful.

sase's TUI compact usage-window indicator has separate display policy under
`llm_provider.usage_metrics.indicator`. Collection controls whether SASE probes and
records provider usage; indicator policy only chooses which already-observed windows
appear in the application header. The default shows every positively classified weekly
all-model window (including Muse's weekly window) and any other observed window whose
remaining capacity is strictly below 20%. Claude's observed weekly
`weekly:claude-fable-5` window has no bundled entry, so the generic threshold governs it
and the header shows it only when it runs low. Muse's 5-hour `session` window is hidden
from the header by default (`indicator.providers.muse.windows.session: never`) but
remains in `sase usage list` and Providers · Usage. Antigravity's `gemini-weekly` window
is treated as its weekly anchor under `weekly_all` and always shows; its `gemini-5h`,
`3p-weekly`, and `3p-5h` windows follow the generic 20% threshold. Use `always`,
`never`, or `{below_remaining_percent: N}` policies. Exact provider window keys are
stable selectors and can be found in `sase usage list --json` at `windows[].key`;
shortened labels in the header are not configuration selectors. Set the exact Fable key
to `always` to restore always-visible behavior, to `never` to hide it even when low, or
to a threshold of its own. Invalid display overrides are reported and ignored at that
override while unrelated collection settings and valid provider/window policies keep
working. Config changes are picked up by the normal sase's TUI usage refresh path even
when no provider writes a new usage cache file.

Use `sase usage` or `sase usage list` to inspect the cache without provider I/O:

```bash
sase usage
sase usage list -p codex --verbose
sase usage list --json
```

Use `sase usage refresh` to submit or join bounded durable probe work. Foreground mode
waits for the operations and then prints the refreshed cache; `--background` returns the
submission receipt immediately. Provider filters are repeatable. `--plain` provides
stable line-oriented text, while redirected output also becomes plain automatically.

sase's TUI exposes the same cache from Launch Control: press `u`, or choose **Open
Providers · Usage** from the command palette. The modal never probes on first paint.
Press its own `u` to update, close it without cancelling durable work, and reopen to
reattach. The scheduler runs due refreshes inline on its 60-second `usage` routine.
sase's TUI independently requests due work after its first paint and then every 60
seconds while it remains open, but only when the scheduler does not own collection;
user-triggered refreshes still submit visible procs either way. Per-provider coalescing
makes concurrent scheduler, sase's TUI, CLI, and limit-event requests join the same live
probe.

Background refreshes, and `sase usage refresh` without `-p`, only probe eligible
providers: registered providers that are not hidden from model pickers, ship a probe
collector, have a resolvable CLI, and are either referenced by the default model, an
epic-lander model, or a built-in or custom model alias, or explicitly enabled with
`llm_provider.usage_metrics.providers.<name>.enabled: true`. The CLI check resolves the
executable the same way the launcher does, so Codex counts as ready when it is found
through `SASE_CODEX_PATH`, `PATH`, or `$NVM_BIN/codex`.

Each provider summary reports remaining capacity, scope, freshness, and collection
status. Details show every currently retained allowance window with its reset, age,
applicability, state, and source; they are current state, not a history of every sample.
The cache can therefore distinguish no observation, stale data, unsupported collection,
authentication failure, and a real low-capacity window rather than collapsing them into
one percentage.

Provider summaries also include collector health when SASE has attempted a probe for the
provider's current account generation. Collector health describes the probe pipeline,
not the freshness of cached allowance windows: passive observations can keep windows
fresh, but they do not reset a broken probe streak. `ok` means the latest probe attempt
succeeded, `degraded` means one or two consecutive probe failures, and `failing` means
three or more consecutive failures. A failing collector surfaces with the streak count,
the first failure time when known, and the last successful probe time when known.

`vendor_drift` is the reason code used when a provider CLI rejects the request shape
SASE sends, such as an unknown flag, invalid JSON-RPC params, an unsupported method, or
an ACP method-not-found response. A fallback strategy that recovers from drift records
an `ok` observation with a bounded diagnostic naming the failed primary strategy and the
strategy that recovered. Collector health and diagnostics are display and
troubleshooting signals only; they never disable providers, change routing eligibility,
or alter round-robin/provider-priority decisions.

Grok's included-allowance billing response may omit `creditUsagePercent` and the `used`
/ `monthlyLimit` amounts after a weekly or monthly reset, leaving a unified
`currentPeriod` with `isUnifiedBillingUser: true`. SASE treats that verified shape as
zero used. Ambiguous or invalid billing payloads remain collection errors, and the usage
store keeps the previous window until a later successful probe. Recover through the
normal refresh path; do not edit the usage cache by hand:

```bash
sase usage refresh -p grok --json
sase usage list -p grok --json
```

Configuration controls the idle and hot refresh cadences (each at least 60 seconds, with
the hot cadence capped at the idle one; automatic refreshes never run faster than a
provider's polling floor) and warning/critical thresholds as percentages used; UI copy
converts those to percentage left. See
[`llm_provider.usage_metrics`](../config/llm-provider-behavior.md#llmproviderusagemetrics)
and the [`sase usage` flags](../cli/usage.md#sase-usage).

## Usage-Limit Auto-Disable

Usage-limit auto-disable classifies provider errors that mean an account or plan limit
has been exhausted, then writes a temporary provider disable with
`source: "usage_limit"`. It uses the same machine-wide state file and Launch Control
surfaces as manual provider disables, so expiry, self-cleaning, alias routing, direct
provider failures, and early clearing all follow
[Temporary Provider Disables](routing.md#temporary-provider-disables).

Provider plugins supply conservative built-in patterns through
`llm_default_usage_limit_config()`. User configuration lives under
`llm_provider.usage_limit`:

- `enabled` turns classification on or off globally.
- `disable_seconds` is the 24-hour fallback duration used when no reset hint is honored.
- `min_disable_seconds` and `max_disable_seconds` clamp only provider-reported reset
  hints, not the administrator-chosen fallback duration.
- `honor_reset_hint` allows a provider-reported reset time to choose the expiry, with a
  small grace buffer of 60 seconds. See [Reset-hint forms](#reset-hint-forms) for what
  it parses.
- `notify` controls the notification created for a new automatic disable window.
- `relaunch` and `relaunch_limit` control whether a hard disable submits a durable drain
  that relaunches the agents it stranded and how many it moves at most. See
  [Draining a Disabled Provider](#draining-a-disabled-provider).
- `providers.<provider>.patterns` adds positive provider-specific substrings.
- `providers.<provider>.exclude_patterns` adds suppressing substrings for near misses
  such as "approaching your usage limit".
- `providers.<provider>.replace_patterns: true` makes the configured `patterns` list a
  literal replacement for built-ins; `patterns: []` intentionally disables matching for
  that provider.
- `providers.<provider>.disable_seconds` and `.honor_reset_hint` override the global
  duration/reset policy for that provider; `null` inherits the global value. `grok`
  ships a non-null built-in `disable_seconds` of 48h because Grok Build reports no reset
  instant and meters usage against a weekly pool.

Detection is provider-scoped. When the failed execution provider is known, SASE tests
only that provider's usage-limit config; it scans other provider configs only for older
or ambiguous paths that genuinely lack execution-provider provenance. A positive
usage-limit match takes precedence over retry for that provider, so the failing attempt
is not retried against the same disabled provider. A plain transient `429`, transport
failure, or model-capacity error that does not match the provider's usage-limit patterns
continues through [Retry and Fallback](retry-and-fallback.md#retry-and-fallback).

Automatic writes are first-window only. If any active disable already exists for that
provider, the detector leaves its source, creation time, and expiry unchanged and does
not emit another notification. After the record expires or is cleared from Launch
Control, a later matching failure may create a new window. Fallback may proceed only to
a different enabled provider; it cannot silently route back to the disabled provider.

### Reset-Hint Forms

When `honor_reset_hint` is on, SASE tries to read an expiry out of the provider's error
text. Five forms are attempted, in this priority order:

| #   | Form                          | Example                                                                                            |
| --- | ----------------------------- | -------------------------------------------------------------------------------------------------- |
| 1   | ISO-ish absolute timestamp    | `resets at 2026-08-18 09:00`                                                                       |
| 2   | Month-name absolute date      | `resets Aug 18, 2026 9am (America/New_York)`; weekly-limit `resets Aug 22, 8pm (America/New_York)` |
| 3   | Clock time with explicit zone | `resets at 8pm (UTC)`                                                                              |
| 4   | Bare clock time               | `resets at 8pm`                                                                                    |
| 5   | Relative duration             | `try again in 2 hours`                                                                             |

Form 1 accepts an optional `Z`, `UTC`, or `±HH:MM` marker. Forms 1–4 share one keyword
anchor: `reset`, `resets`, or `try again`, followed by an optional `at`/`on`. Form 5
needs the keyword to end in `in` (`resets in 90m`, `try again in 2 hours`). A date or
time must follow the keyword immediately, so incidental prose such as "connection reset
by peer" cannot match. Claude Code's `seven_day` formatter emits a compact meridiem
(`8pm`, not `8 pm`) and omits `:00` when minutes are zero.

Parsing commits to the first form whose keyword matches; it does **not** fall through to
a lower-priority form when that form then fails to resolve. That is why forms 3 and 4
are listed separately: `resets at 8pm (Not/AZone)` matches form 3, and an unrecognized
zone name there is treated as a failed parse rather than silently reinterpreted as the
bare form 4. Once a usage-limit pattern has already matched, if none of those keyword
forms match, SASE also scans for an unanchored month-name or ISO-ish timestamp so a date
without `resets`/`try again` can still set the expiry.

Forms carrying no zone marker — form 1 without a marker, form 2 without a parenthesized
zone, and form 4 — resolve through the configured SASE `timezone:`. Setting that to
something other than the host's zone will skew those parses.

Any failed or ambiguous parse falls back to `disable_seconds`. Reading a hint is an
optimization, never a gate: it cannot block or delay the disable.

### Draining a Disabled Provider

A **hard** disable stops new launches from landing on a provider; draining goes further
and relaunches the agents that provider already stranded — the ones that were
`STARTING`, `RUNNING`, or `WAITING` on it when the disable landed, plus rows that failed
on it just before the disable. `sase.agent._drain_selection` selects candidates from one
`list_all_agents()` snapshot:

- Live rows in `STARTING`, `RUNNING`, or `WAITING` on the disabled provider.
- `FAILED` rows whose `done.finished_at` is at or after `disable.created_at - 300s` and
  whose recorded `done.error` matches that provider's own usage-limit pattern through
  `detect_usage_limit()` — the same matcher that caused the disable in the first place.
  A manual disable therefore drains a recently-failed row only when the operator
  disabled the provider because they watched agents fail on it.

Effective provider is `agent_meta.json`'s `exec_llm_provider` when present, else the
listed `llm_provider` — a row rerouted through `SASE_LLM_EXEC_PROVIDER` is selected by
what actually ran, not by its display provider.

Each candidate is replanned exactly like `sase agent restart`, then its rewritten
prompt's route is classified through `plan_launch_units()`: if every launch unit is
blocked, the agent is **stranded** and reported, never guessed onto a substitute model.
Otherwise the first unit's resolved candidate — almost always chosen by ordinary alias
resolution routing around the disabled provider — is the **reroute** destination. A
prompt pinned to a direct `provider/model` spelling has nowhere else to go and is always
stranded; only a size or custom alias can reroute.

Never drained, and why:

- **Monitor rows** (`RunningAgentInfo.is_monitor`) supervise a shell command, not
  provider quota; killing one kills the monitored command instead of freeing anything.
- **`QUESTION`/`ANSWERED`** rows hold a pending user interaction that a restart would
  destroy.
- **The calling agent** — `sase agent drain` run from inside an agent never drains its
  own caller.

The real cost: like `sase agent restart`, a drain's `execute_agent_restart()` deletes
the previous run's artifacts before relaunching. Any in-flight progress on a `RUNNING`
row is lost; the chat transcript under `~/.sase/chats` survives.

The `llm_provider.usage_limit.relaunch` / `relaunch_limit` config fields (above) control
whether and how much a usage-limit hard disable drains automatically, as does sase's TUI
Launch Control [automatic provider drain](../../ace.md#automatic-provider-drain).

`sase agent drain <provider>` is the always-available manual escape hatch: it previews
with `--dry-run`, refuses a provider with no active hard disable (exit 2 for
`nothing_to_drain`, except an automatic request records that empty result as a
successful no-op), and confirms before discarding live progress unless `-y`/`--yes` or
`-j`/`--json` is given. `-m/--model` is the way to move an agent the plan would
otherwise report stranded — pointing the whole drain at a reachable model turns every
moved agent into an ordinary reroute. `-l/--limit` caps how many agents move at once;
anything dropped by the limit is reported, never silently skipped.

Automatic usage-limit drains send one notification for the disable window. The drain
notes report completed relaunches, failed replacement moves, and rows left alone; the
durable proc output has the complete JSON envelope. Inspect a bad drain with
`sase proc show <proc-id> --all-lines --output-only` and look at each result's `error`,
`recovery_dir`, and `recovery_prompt` fields.

Restart recovery bundles live under `~/.sase/restarts/<timestamp>-<agent>/`. For a
failed forced-reuse restart, open the saved `rewritten.md` prompt from that bundle in
sase's TUI and relaunch through the reviewed launch flow so name reuse, bead context,
session or clan membership, and scoped authorization are reconstructed. Do not recover
forced reuse by running a bare `sase run "$(cat rewritten.md)"`; `execution.md` is
retained for audit of the already-prepared launch text, not as a privileged replay path.

## Related

- [Providers and models](index.md) — the provider integration overview.
- [Environment variables](../environment-variables.md) — provider-specific variables.
