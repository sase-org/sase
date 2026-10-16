---
title: "Agent and runner configuration"
description:
  "Configuration for agent admission, runner capacity, and lifecycle behavior."
---

# Agent and runner configuration

Configuration for agent admission, runner capacity, and lifecycle behavior.

## gate

Settings for durable, command-backed gates. The only current setting controls how the
hourly `gate_turn_reclaim` housekeeping job settles a
[gate turn](../automation/notification-gates.md#gate-turns-and-continuation) whose gate
has already passed its own deadline.

```yaml
gate:
  turn:
    reclaim_grace_seconds: 3600
```

[Generated reference for `gate`](automation.md#gate)

Within the grace window, reclaim cancels an expired gate and settles its turn as a
normal `timeout`; once the window has passed, a still-pending turn settles as `lost`
instead. A missing, negative, or non-integer value falls back to `3600`. The retired
`gate.shell` `.reclaim_grace_seconds` key is accepted as this same setting. Setting both
keys is an error; use only `gate.turn`.

Source: `src/sase/default_config.yml`, `src/sase/gate_turn/reclaim.py`

## autonomy

Autonomy profile each generated epic worker launches with. Values are built-in profile
names from `sase autonomy list`: `standard` (tale plans approve + archive, epic plans
approve + launch, questions take the first option), `tale` (epic plans wait for you),
`epic` (tale plans wait for you), or `manual` (everything waits). Custom profile names
are not supported. This setting controls generated workers; a fresh user launch without
`%auto` remains manual. See the
[profile matrix](../macros/directive-launch.md#auto-directive).

```yaml
autonomy:
  roles:
    epic_phase: standard
    epic_land: standard
```

To restore "nested epics wait for me", set both roles to `tale` in your user-level
`~/.config/sase/sase.yml` or in the project-level `sase/sase.yml`:

```yaml
autonomy:
  roles:
    epic_phase: tale
    epic_land: tale
```

The setting is read when the epic's worker prompts are rendered, so already launched
workers keep the profile in their prompt. `sase autonomy list` shows the effective role
assignments.

An unknown profile name logs a warning and falls back to `standard`; missing, empty, or
non-string role values also use `standard`. Check `sase autonomy list` after editing the
setting to see the effective profiles and their sources.

[Generated reference for `autonomy`](agents.md#autonomy)

Source: `src/sase/default_config.yml`, `src/sase/autonomy/roles.py`

<a id="maxrunningagents"></a>

## max_running_agents

The configured global runner-capacity budget across all projects. The key remains an
integer and the packaged default remains `10`, but the value is interpreted as capacity
units. A normal launch claims `1.0`; `%queue(weight=...)` / `%q(w=...)` can request a
non-negative finite weight (`%q(w=0)` adds no load but still takes its queue turn).

A standalone agent owns one claim of its effective weight. A live serial session shares
one claim across its agent, monitor, and serial successor turns; serial continuations
inherit the session weight when omitted, and must reacquire capacity after the session
has released its claim. Independently launched clan members and live parallel clan
members each hold their own claim. A processless gate turn deliberately releases runner
capacity while it owns a user decision, even when it retains the session's workspace
claim. Workflow Python/bash steps and axe Patch runners hold none of this capacity; axe
runners continue to use their separate `axe.max_*_runners` limits.

```yaml
max_running_agents: 10
```

[Generated reference for `max_running_agents`](agents.md#max_running_agents)

The effective cap is an active machine-wide temporary override first and this merged
configured value second. In Launch Control, fixed `Ctrl+R` opens **Runner Capacity**:
`e` previews and writes the user-base/chezmoi source, `o` chooses a relative, custom,
until-cleared, or exact-time override, and `x` clears it. Temporary state is stored as a
versioned record at `~/.sase/max_running_agents_override.json`; a new set replaces the
previous value, expiry is enforced at its deadline, and a persistent edit leaves an
active override in force. Lowering the effective value is non-preemptive, so existing
agents continue and new launches wait for occupied capacity to drain. Parked waiters and
question continuations reread the effective cap on each normal poll. An explicit
`%queue(capacity=N)` (or `sase bead work -c/--capacity N` for an epic) uses that
positive-integer value as the launch's own admission budget, replacing the global budget
for that launch only. Once admitted, the launch holds an ordinary weighted claim, so
occupied capacity can honestly exceed the global budget until work drains.

An authored `%queue(capacity=<M>x)` instead scales from this effective value, including
an active override: `%q:1.5x` resolves to `7.5` when the effective limit is `5`. It is
resolved again while the launch is queued, rather than freezing the configured value at
launch time. Multipliers accept up to two decimal places.

When upgrading from an unweighted scheduler build, restart sase's TUI and the service
host and let already running agent processes finish or relaunch them under the new
binary. Records without a `queue_weight` field use `1.0`, but mixed admission processes
do not provide a safe weighted-capacity rollout because every process must enforce
weighted claims. <a id="maxagentpipechain"></a>

## max_agent_pipe_chain

The bound on how many times one agent session may hand its turn forward with
`sase pipe`. The originally launched agent is depth `0`; each successful pipe records
`pipe_depth` on the successor and increments it by one. A pipe is refused when the next
link would exceed this value, and the refusal names the limit, this configuration key,
and the chain length already reached. The calling agent stays alive on a refusal, so it
can finish the work itself instead of handing it on.

```yaml
max_agent_pipe_chain: 8
```

[Generated reference for `max_agent_pipe_chain`](agents.md#max_agent_pipe_chain)

This is a configuration field rather than a feature flag: the number is one users choose
permanently to stop a self-piping chain from running away. A missing or malformed value
falls back to the packaged default rather than allowing an unbounded chain. Only
`sase pipe` records `pipe_depth`, so a plan-approval, question, or monitor follow-up
member created in between starts the count over at `0`. The bound is per session chain,
not per host, so it is unrelated to the concurrency cap in
[max_running_agents](#maxrunningagents).

Source: `src/sase/default_config.yml`, `src/sase/config/core.py`,
`src/sase/main/pipe_handler.py`

<a id="runnerslots"></a>

## runner_slots

Bounded deference for deprioritized runner-slot waiters. Admission sorts eligible
waiters by lower numeric `%queue(priority=N)` first, but that sort only compares agents
already parked at the instant a slot frees. Dependency-chained work joins the queue
seconds after its predecessor exits, so a long-parked deprioritized waiter would
otherwise reliably win that race against exactly the normal-priority work it was meant
to yield to. A waiter whose priority is numerically **worse than** the `10` default
therefore holds back for a bounded window instead of claiming the moment it becomes
eligible, which gives a better-priority agent time to park and win through the existing
sort.

```yaml
runner_slots:
  deference_seconds_per_step: 3
  deference_max_seconds: 60
```

[Generated reference for `runner_slots`](agents.md#runner_slots)

The window is `min((priority - 10) * deference_seconds_per_step, deference_max_seconds)`
seconds. With the defaults, `priority=20` defers for up to 30s and any priority at or
beyond `30` clamps to the 60s cap. Priority `10` is the boundary and it is inclusive:
default-priority and better-priority waiters (`priority <= 10`) never defer and claim on
the first eligible poll exactly as before. The asymmetry is deliberate—you cannot defer
to work that may never arrive, so only an agent that explicitly volunteered to be
deprioritized pays a delay.

Deference measures **continuous** eligibility, not total time parked. The window starts
when the waiter first becomes eligible while a better-priority agent is pending, and it
resets whenever the waiter stops being eligible, so time spent parked behind a full cap
never counts toward it. It also exits early: on any poll where no live, unstarted,
not-yet-parked agent with a better priority remains, the waiter claims immediately
instead of serving out the rest of the window. The agent log prints one
`Deferring for up to Ns (priority N)` line on entry into the window.

Both fields are read fail-open. Deference is a politeness optimization, so a missing,
non-integer, negative, or unreadable value falls back to the built-in default rather
than propagating an error. This differs deliberately from `max_running_agents`, where
configuration errors do propagate: a bad value here must never strand a runner.

Bounded deference is not priority aging and not preemption. A running agent is never
stopped to make room, and a deferred waiter's own priority does not improve while it
<a id="agentscopeteardown"></a> waits. See
[Agent waiting for a runner slot](../runner-slots.md) for diagnosis, and
[`%queue(priority=N)`](../macros/directive-syntax.md#supported-directives) for the
directive itself.

## agent_scope_teardown

Lifetime of processes an agent starts. An agent runner's `sase-agent-*` scope bounds
every process the agent starts: leftovers are swept at runner exit and between
in-process successor turns, and long-lived work must escape via `detach_scope` into its
own scope. Members matching a spare pattern (plus their descendants) are never killed,
so shared user daemons survive.

```yaml
agent_scope_teardown:
  enabled: true
  term_grace_seconds: 3
  reaper_min_scope_age_seconds: 120
  spare_process_patterns:
    - "^ssh-agent$"
    - "^gpg-agent$"
    - "^tmux: server$"
    - '^ssh: .*\[mux\]$'
```

[Generated reference for `agent_scope_teardown`](agents.md#agent_scope_teardown)

This is a config field, not a feature flag: users may permanently disable it or extend
the spare list, and the sweep is on by default. An invalid spare pattern is logged and
ignored. The sweep is Linux/cgroup-v2 only and a no-op elsewhere.
<a id="agentautorestart"></a>

Source: `src/sase/default_config.yml`, `src/sase/config/_settings_system.py`,
`src/sase/agent/scope_sweep.py`

## agent_auto_restart

Controls recovery of agents interrupted by a live SASE update. It is enabled by default
and requires the scheduler's `agent_auto_restart` job. It keeps a separate restart
ledger and allows at most one automatic relaunch per lineage. See
[Agent Auto-Restart](../agent-auto-restart.md) for eligibility, evidence, and current
healer limitations.

```yaml
agent_auto_restart:
  enabled: true
  quiescence_seconds: 30
  max_defer_seconds: 1800
  pending_resurface_seconds: 600
  storm_max_per_episode: 12
  storm_max_per_30m: 20
```

[Generated reference for `agent_auto_restart`](agents.md#agent_auto_restart)

All fields are under `agent_auto_restart`. Numeric values are non-negative numbers of
seconds or integer counts, not duration strings; malformed values use their defaults.
`enabled` requires a YAML boolean. This is a persistent configuration choice with no
feature flag. `sase agent auto-restart resume` clears the storm pause; it does not
override `enabled: false` or reset spent lineage records.

Source: `src/sase/default_config.yml`, `src/sase/config/_settings_system.py`

## agent hold limits

Three top-level keys bound agent holds armed by the `sase agent hold create` / `run`
commands and the [`%hold` directive](../macros/directive-launch.md#hold-directive).

```yaml
agent_hold_default_ttl: 2h
agent_hold_max_ttl: 12h
agent_hold_confirm_capture_threshold: 10
```

[Generated reference for `agent_hold_default_ttl`](agents.md#agent_hold_default_ttl)

The launch preview lists each `%hold` with its scope and a TTL resolved against these
values, showing both the default and the cap. sase's TUI and an interactive `sase run`
ask for confirmation when a preview combines `future` with `scope=host`, regardless of
the threshold. They can also ask when a `pending` capture exceeds the threshold, but the
capture check needs project context: the TUI supplies it, typed launch plans can resolve
it, and a plain project-scoped `sase run` prompt currently cannot. The Admin Center
[Config tab](../tui/admin-center.md#config-tab)'s **Holds** child lists and releases
active holds, and `sase doctor -C agent_holds.stale` reports holds whose armer died or
whose TTL passed.

A missing or unparsable TTL, or a negative or non-integer threshold, falls back to the
default shown above rather than failing the command.

Source: `src/sase/default_config.yml`, `src/sase/config/_settings_runner.py`,
`src/sase/agents/cli_hold.py`, `src/sase/agent/launch_hold_preview.py`

## tmux_agent {#tmux_agent}

Configuration for [tmux Agent](../tui/launch-control.md#tmux-agent): Launch Control's
`t` binding and `sase tmux-agent`. Both surfaces share this block. A bad value is
dropped with a warning rather than making the tmux key binding fail.

```yaml
tmux_agent:
  # Base tmux window name. The first window is this name; later ones get a
  # numeric suffix (ai, ai2, ai3, ...).
  window_name: "ai"
  # Pass each agent CLI's approval-bypass flags (see the provider's
  # llm_interactive_cli descriptor). Per-provider overrides win.
  bypass_permissions: true
  # Reasoning effort applied to launches. "" follows llm_provider.default_effort;
  # "off" passes no effort flags at all.
  effort: ""
  # Run `clear` in the new window before starting the CLI.
  clear_screen: true
  # Optional shell command run after an agent CLI window closes, alongside
  # SASE's own window renumbering. Empty means nothing extra runs.
  after_close_command: ""
  # Per-provider overrides, keyed by registered provider name.
  providers:
    claude:
      enabled: true # false hides the provider from both surfaces
      key: "" # override the single-key menu shortcut
      model: "" # pin a model, e.g. "gemini-3.7-flash-high"
      effort: "" # per-provider effort; "" inherits, "off" disables
      args: [] # extra CLI args appended verbatim
      env: {} # environment variables for the new tmux window
      bypass_permissions: true # omit to inherit the global default
```

[Generated reference for `tmux_agent`](agents.md#tmux_agent)

`effort` accepts `""`, `"off"`, `"none"`, `"minimal"`, `"low"`, `"medium"`, `"high"`,
`"xhigh"`, and `"max"`. A config-default effort is best-effort: a provider that cannot
honor the level launches without the flag rather than failing. An explicit
`sase tmux-agent -e <level>` that the provider cannot honor is a usage error.

Three per-provider entries are load-bearing if you want the resolved argv to match the
shell script this feature replaces:

```yaml
tmux_agent:
  effort: "max"
  providers:
    claude: { env: { EDITOR: nvim } }
    codex: { effort: "xhigh" }
    grok: { effort: "xhigh" }
    opencode: { effort: "off" }
    agy: { model: "gemini-3.7-flash-high" }
    qwen: { model: "qwen3.6-plus" }
    muse: { model: "muse-spark-1.3" }
```

- `codex` and `grok` cap out at `xhigh`. A config-default effort is best-effort, so
  `effort_cli_args` logs and skips `max` rather than downgrading it — without the
  per-provider `xhigh` they would launch with no effort flag at all, unlike the script.
- `opencode` accepts every level as `--variant <level>`, so a global `max` would add a
  flag the script never passes; `effort: "off"` keeps it bare.
- `agy` and `qwen` need no effort entry: both declare an empty supported-effort map, so
  the global `max` is skipped for them automatically and their argv already matches.
  Their `model` pins reproduce the script's hardcoded models.

`EDITOR=nvim` is a personal preference, not a provider requirement, which is why it
lives on `tmux_agent.providers.claude.env` rather than in the Claude plugin.

Source: `src/sase/default_config.yml`, `src/sase/config/tmux_agent.py`

## Related

- [Agents and runners configuration](agents.md) — generated keys and defaults.
- [Agent providers](../providers/agent-clis.md) — provider setup.
