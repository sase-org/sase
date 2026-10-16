---
title: Agents and runners configuration
description: Agent launch, completion, capacity, restart, and process-scope settings.
---

<!-- generated, do not edit; source: src/sase/config/sase.schema.json and src/sase/default_config.yml (tools/render_config; run just fix to regenerate) -->

# Agents and runners configuration

Agent launch, completion, capacity, restart, and process-scope settings.

Defaults come from the schema when declared, otherwise from the bundled YAML. An object
with listed children is expanded below; `{…}` and `[…]` summarize compound defaults. A
dash means the schema has no finite allowed-value list.

## `agent_auto_restart`

| Config key                                                                                              | Type    | Default                    | Allowed values | Description                                                                                                                          |
| ------------------------------------------------------------------------------------------------------- | ------- | -------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| <a id="agent_auto_restart"></a>`agent_auto_restart`                                                     | object  | {…} (6 keys; values below) | —              | Controls recovery of agents interrupted by a live update, including quiescence, retry, and storm limits.                             |
| <a id="agent_auto_restart-enabled"></a>`agent_auto_restart.enabled`                                     | boolean | `true`                     | —              | Master kill switch for automatic update-skew restarts. False disables every automatic path; pending failures are re-surfaced loudly. |
| <a id="agent_auto_restart-quiescence_seconds"></a>`agent_auto_restart.quiescence_seconds`               | number  | `30`                       | —              | Seconds the managed code tree must stay quiet before the healer relaunches anything.                                                 |
| <a id="agent_auto_restart-max_defer_seconds"></a>`agent_auto_restart.max_defer_seconds`                 | number  | `1800`                     | —              | Maximum age of a deferred ledger record before it is declined instead of re-attempted.                                               |
| <a id="agent_auto_restart-pending_resurface_seconds"></a>`agent_auto_restart.pending_resurface_seconds` | number  | `600`                      | —              | Age after which a pending failure with no ledger record is re-surfaced loudly.                                                       |
| <a id="agent_auto_restart-storm_max_per_episode"></a>`agent_auto_restart.storm_max_per_episode`         | integer | `12`                       | —              | Maximum automatic launches per update episode before the storm breaker pauses the feature.                                           |
| <a id="agent_auto_restart-storm_max_per_30m"></a>`agent_auto_restart.storm_max_per_30m`                 | integer | `20`                       | —              | Maximum automatic launches per rolling 30 minutes before the storm breaker pauses the feature.                                       |

## `agent_hold_confirm_capture_threshold`

| Config key                                                                              | Type    | Default | Allowed values | Description                                                                                |
| --------------------------------------------------------------------------------------- | ------- | ------- | -------------- | ------------------------------------------------------------------------------------------ |
| <a id="agent_hold_confirm_capture_threshold"></a>`agent_hold_confirm_capture_threshold` | integer | `10`    | —              | Pending-capture count above which a launch preview's %hold needs interactive confirmation. |

## `agent_hold_default_ttl`

| Config key                                                  | Type   | Default | Allowed values | Description                                                                                                        |
| ----------------------------------------------------------- | ------ | ------- | -------------- | ------------------------------------------------------------------------------------------------------------------ |
| <a id="agent_hold_default_ttl"></a>`agent_hold_default_ttl` | string | `"2h"`  | —              | TTL applied to `sase agent hold create`/`run` when --ttl is omitted. Bare seconds or a number suffixed with s/m/h. |

## `agent_hold_max_ttl`

| Config key                                          | Type   | Default | Allowed values | Description                                                                                                   |
| --------------------------------------------------- | ------ | ------- | -------------- | ------------------------------------------------------------------------------------------------------------- |
| <a id="agent_hold_max_ttl"></a>`agent_hold_max_ttl` | string | `"12h"` | —              | Maximum TTL accepted by `sase agent hold create`/`run --ttl`. Same duration syntax as agent_hold_default_ttl. |

## `agent_scope_teardown`

| Config key                                                                                                        | Type    | Default                                                                                                    | Allowed values | Description                                                                                                              |
| ----------------------------------------------------------------------------------------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------ |
| <a id="agent_scope_teardown"></a>`agent_scope_teardown`                                                           | object  | {`enabled`, `term_grace_seconds`, `reaper_min_scope_age_seconds`, `spare_process_patterns`} (values below) | —              | Sweeps leaked processes from agent-owned scopes at runner exit and reaps abandoned scopes.                               |
| <a id="agent_scope_teardown-enabled"></a>`agent_scope_teardown.enabled`                                           | boolean | `true`                                                                                                     | —              | Whether the runner sweeps leaked processes from its own sase-agent scope at exit and between in-process successor turns. |
| <a id="agent_scope_teardown-term_grace_seconds"></a>`agent_scope_teardown.term_grace_seconds`                     | number  | `3`                                                                                                        | —              | Grace between SIGTERM and SIGKILL when sweeping leaked scope processes.                                                  |
| <a id="agent_scope_teardown-reaper_min_scope_age_seconds"></a>`agent_scope_teardown.reaper_min_scope_age_seconds` | number  | `120`                                                                                                      | —              | Minimum scope age before the orphaned-scope reaper may sweep it.                                                         |
| <a id="agent_scope_teardown-spare_process_patterns"></a>`agent_scope_teardown.spare_process_patterns`             | array   | `["^ssh-agent$","^gpg-agent$","^tmux: server$","^ssh: .*\\[mux\\]$"]`                                      | —              | Regex patterns (re.search) matching shared daemons the sweep never kills.                                                |
| <a id="agent_scope_teardown-spare_process_patterns-item"></a>`agent_scope_teardown.spare_process_patterns[]`      | string  | not set                                                                                                    | —              | —                                                                                                                        |

## `autonomy`

| Config key                                                        | Type   | Default                                    | Allowed values                               | Description                                                                                                                             |
| ----------------------------------------------------------------- | ------ | ------------------------------------------ | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| <a id="autonomy"></a>`autonomy`                                   | object | {`roles`} (values below)                   | —                                            | Autonomy profile each generated worker role launches with.                                                                              |
| <a id="autonomy-roles"></a>`autonomy.roles`                       | object | {`epic_phase`, `epic_land`} (values below) | —                                            | Worker role to autonomy profile mapping.                                                                                                |
| <a id="autonomy-roles-epic_phase"></a>`autonomy.roles.epic_phase` | string | `"standard"`                               | `"manual"`, `"standard"`, `"tale"`, `"epic"` | Autonomy profile for epic phase agents launched by `sase bead work` / epic plan approval. E3 will widen values to config profile names. |
| <a id="autonomy-roles-epic_land"></a>`autonomy.roles.epic_land`   | string | `"standard"`                               | `"manual"`, `"standard"`, `"tale"`, `"epic"` | Autonomy profile for epic land agents. E3 will widen values to config profile names.                                                    |

## `finalizers`

| Config key                                                                                  | Type    | Default                                              | Allowed values      | Description                                                                                                 |
| ------------------------------------------------------------------------------------------- | ------- | ---------------------------------------------------- | ------------------- | ----------------------------------------------------------------------------------------------------------- |
| <a id="finalizers"></a>`finalizers`                                                         | object  | {`defaults`, `required`, `instances`} (values below) | —                   | Host-owned finalizer instances selected for SASE agent completion.                                          |
| <a id="finalizers-defaults"></a>`finalizers.defaults`                                       | array   | `["commit"]`                                         | —                   | Default finalizer instance IDs selected when no %final directive overrides them.                            |
| <a id="finalizers-defaults-item"></a>`finalizers.defaults[]`                                | string  | not set                                              | —                   | —                                                                                                           |
| <a id="finalizers-required"></a>`finalizers.required`                                       | array   | `[]`                                                 | —                   | Finalizer instance IDs that cannot be removed by %final.                                                    |
| <a id="finalizers-required-item"></a>`finalizers.required[]`                                | string  | not set                                              | —                   | —                                                                                                           |
| <a id="finalizers-instances"></a>`finalizers.instances`                                     | object  | {`commit`} (values below)                            | —                   | Configured finalizer instances keyed by lowercase slug.                                                     |
| <a id="finalizers-instances-key"></a>`finalizers.instances.<key>`                           | object  | not set                                              | —                   | —                                                                                                           |
| <a id="finalizers-instances-key-use"></a>`finalizers.instances.<key>.use`                   | string  | not set                                              | —                   | Provider reference such as builtin@commit or distribution@provider.                                         |
| <a id="finalizers-instances-key-after"></a>`finalizers.instances.<key>.after`               | array   | `[]`                                                 | —                   | Finalizer instances that must run before this instance.                                                     |
| <a id="finalizers-instances-key-after-item"></a>`finalizers.instances.<key>.after[]`        | string  | not set                                              | —                   | —                                                                                                           |
| <a id="finalizers-instances-key-max_attempts"></a>`finalizers.instances.<key>.max_attempts` | integer | `1`                                                  | —                   | Maximum executor attempts for this finalizer.                                                               |
| <a id="finalizers-instances-key-refusal"></a>`finalizers.instances.<key>.refusal`           | string  | `"fail"`                                             | `"fail"`, `"defer"` | Policy for an upheld deferral: 'fail' ends the turn, 'defer' completes the run with a disclosed dirty tree. |
| <a id="finalizers-instances-key-config"></a>`finalizers.instances.<key>.config`             | object  | `{}`                                                 | —                   | Provider-specific trusted configuration.                                                                    |

## `max_agent_pipe_chain`

| Config key                                              | Type    | Default | Allowed values | Description                                                                                                                                                                                   |
| ------------------------------------------------------- | ------- | ------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| <a id="max_agent_pipe_chain"></a>`max_agent_pipe_chain` | integer | `8`     | —              | Maximum number of sase pipe hops in one session chain. The original agent is depth 0; each successful pipe increments depth by one and is refused when the next link would exceed this bound. |

## `max_running_agents`

| Config key                                          | Type    | Default | Allowed values | Description                                                                                                                                                                                                                                                                                            |
| --------------------------------------------------- | ------- | ------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| <a id="max_running_agents"></a>`max_running_agents` | integer | `10`    | —              | Host-wide runner-capacity budget. Normal launches claim 1.0 capacity unit; %queue(weight=...) / %q(w=...) may request non-negative finite weights (%q(w=0) adds no load). Serial sessions share one live claim, while independent clan members and parallel session members each hold their own claim. |

## `runner_slots`

| Config key                                                                                    | Type    | Default                                                                | Allowed values | Description                                                                        |
| --------------------------------------------------------------------------------------------- | ------- | ---------------------------------------------------------------------- | -------------- | ---------------------------------------------------------------------------------- |
| <a id="runner_slots"></a>`runner_slots`                                                       | object  | {`deference_seconds_per_step`, `deference_max_seconds`} (values below) | —              | Priority-based deference for runner-slot waiters, bounded by a maximum delay.      |
| <a id="runner_slots-deference_seconds_per_step"></a>`runner_slots.deference_seconds_per_step` | integer | `3`                                                                    | —              | Seconds a waiter defers per priority step above the default priority of 10.        |
| <a id="runner_slots-deference_max_seconds"></a>`runner_slots.deference_max_seconds`           | integer | `60`                                                                   | —              | Maximum continuous-eligibility delay for a waiter with priority above the default. |

## `tmux_agent`

| Config key                                                                                              | Type    | Default                    | Allowed values                                                                          | Description                                                                                                                           |
| ------------------------------------------------------------------------------------------------------- | ------- | -------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| <a id="tmux_agent"></a>`tmux_agent`                                                                     | object  | {…} (6 keys; values below) | —                                                                                       | Configuration for launching interactive agent CLIs in a new tmux window                                                               |
| <a id="tmux_agent-window_name"></a>`tmux_agent.window_name`                                             | string  | `"ai"`                     | —                                                                                       | Base tmux window name. The first window is this name; later ones get a numeric suffix (ai, ai2, ai3, ...).                            |
| <a id="tmux_agent-bypass_permissions"></a>`tmux_agent.bypass_permissions`                               | boolean | `true`                     | —                                                                                       | Pass each agent CLI's approval-bypass flags. Per-provider overrides win.                                                              |
| <a id="tmux_agent-effort"></a>`tmux_agent.effort`                                                       | string  | `""`                       | `""`, `"off"`, `"none"`, `"minimal"`, `"low"`, `"medium"`, `"high"`, `"xhigh"`, `"max"` | Reasoning effort applied to launches. Empty follows llm_provider.default_effort; "off" passes no effort flags at all.                 |
| <a id="tmux_agent-clear_screen"></a>`tmux_agent.clear_screen`                                           | boolean | `true`                     | —                                                                                       | Run `clear` in the new window before starting the CLI.                                                                                |
| <a id="tmux_agent-after_close_command"></a>`tmux_agent.after_close_command`                             | string  | `""`                       | —                                                                                       | Optional shell command run after an agent CLI window closes, alongside SASE's own window renumbering. Empty means nothing extra runs. |
| <a id="tmux_agent-providers"></a>`tmux_agent.providers`                                                 | object  | `{}`                       | —                                                                                       | Per-provider overrides, keyed by registered provider name.                                                                            |
| <a id="tmux_agent-providers-key"></a>`tmux_agent.providers.<key>`                                       | object  | not set                    | —                                                                                       | Overrides for one registered agent-CLI provider.                                                                                      |
| <a id="tmux_agent-providers-key-enabled"></a>`tmux_agent.providers.<key>.enabled`                       | boolean | `true`                     | —                                                                                       | When false, hide this provider from both tmux Agent surfaces.                                                                         |
| <a id="tmux_agent-providers-key-key"></a>`tmux_agent.providers.<key>.key`                               | string  | not set                    | —                                                                                       | Override the single-key menu shortcut. Empty uses automatic assignment.                                                               |
| <a id="tmux_agent-providers-key-model"></a>`tmux_agent.providers.<key>.model`                           | string  | `""`                       | —                                                                                       | Pin a model for this provider, e.g. "gemini-3.7-flash-high". Empty leaves the CLI's default.                                          |
| <a id="tmux_agent-providers-key-effort"></a>`tmux_agent.providers.<key>.effort`                         | string  | `""`                       | `""`, `"off"`, `"none"`, `"minimal"`, `"low"`, `"medium"`, `"high"`, `"xhigh"`, `"max"` | Per-provider reasoning effort. Empty inherits the section default; "off" disables effort flags.                                       |
| <a id="tmux_agent-providers-key-args"></a>`tmux_agent.providers.<key>.args`                             | array   | `[]`                       | —                                                                                       | Extra CLI args appended verbatim to the resolved launch command.                                                                      |
| <a id="tmux_agent-providers-key-args-item"></a>`tmux_agent.providers.<key>.args[]`                      | string  | not set                    | —                                                                                       | —                                                                                                                                     |
| <a id="tmux_agent-providers-key-env"></a>`tmux_agent.providers.<key>.env`                               | object  | `{}`                       | —                                                                                       | Environment variables set in the new tmux window.                                                                                     |
| <a id="tmux_agent-providers-key-env-key"></a>`tmux_agent.providers.<key>.env.<key>`                     | string  | not set                    | —                                                                                       | —                                                                                                                                     |
| <a id="tmux_agent-providers-key-bypass_permissions"></a>`tmux_agent.providers.<key>.bypass_permissions` | boolean | not set                    | —                                                                                       | Override the section-level approval-bypass default for this provider. Omit to inherit.                                                |

## Related

- [Configuration reference](index.md) — all key families.
