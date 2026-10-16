---
title: Macro directives
description: The generated catalog of prompt directives and their syntax.
---

<!-- generated, do not edit; source: Rust directive_contract (tools/render_keymap_macro_reference; run just fix to regenerate) -->

# Macro directives

The TUI, macro language server, and launch parser share this Rust-owned contract. Aliases, syntax forms, argument summaries, and descriptions below are generated from that contract. The marker directive uses its current `macros_enabled` spelling here; `%xprompts_enabled` remains accepted for old prompts.

| Directive | Alias | Forms | Arguments | Purpose |
| --- | --- | --- | --- | --- |
| `%model` | `%m` | :value, (...) | :model or (model, alias=model) | Override the LLM model for this prompt |
| `%effort` | `%e` | :value | :level | Set the reasoning-effort level for this prompt |
| `%final` | — | :value, (...) | :instance\|!instance\|none or (instance, ...) | Select configured finalizer instances for this launch |
| `%id` | `%i` | :value, (...), bare | :agent-id or :name.{@key}; ([id], bead=, clan=/session=/tribe=) | Assign an agent ID with optional bead, clan, session, or user-managed tribe |
| `%clan` | `%c` | :value, (...) | :name or :name.{@key}, (name, tribe=/summary=/summary_script=), or :name:: summary | Declare a new parallel agent clan |
| `%wait` | `%w` | :value, (...), bare | :agent or (agent, bead=, hood=, time=, for_epic=) | Wait for another agent/workflow and/or a time floor |
| `%queue` | `%q` | :value, (...) | :N or <M>x or (N, <M>x, capacity=, priority=, p=, weight=, w=) | Set this launch's capacity budget, <M>x multiplier of this machine's max_running_agents budget, priority, and capacity weight |
| `%hold` | — | :value, (...) | :agent or (agent, pending, future, hood=, tribe=, ttl=, scope=) | Hold selected pre-run agents until this launch settles |
| `%dispatch` | — | :value, (...) | :machine or (machine) | Send this launch to an enrolled remote machine |
| `%tab` | — | :value, (...) | :name or (name) | Place this launch's presentation root on a named agent tab |
| `%if` | — | (...), :: body | %if(should_run=true\|false) omits disabled segments; %if:: gates admission with a script guard | Statically omit a prompt segment, or gate launch with a typed predicate |
| `%proc` | — | (...), :: body | %proc("cmd"), %proc(bash=\|python=), or %proc:: plus one fence | Launch a stand-alone proc unit with a Bash or Python body |
| `%auto` | `%a` | :value, bare, + | :mode (plan\|tale\|epic\|manual\|off) | Request automatic gate resolution; use %auto, %auto+, or %auto:<mode> with mode plan, tale, or epic. %auto:manual and %auto:off disable automatic approval; any other spelling fails at launch |
| `%hide` | `%h` | bare, + | flag | Hide the agent from the default Agents tab display |
| `%repeat` | `%r` | :value | :count | Run the prompt multiple times |
| `%alt` | — | %{…}, :value, (...) | (variants) | Split prompt into variants with different text; shorthand %{A \| B} |
| `%macros_enabled` | `%xprompts_enabled (legacy)` | :value | :false\|true | Enable or disable macro expansion for a text region |

## Argument details

### `%model`

Override the LLM model for this prompt

### `%effort`

Set the reasoning-effort level for this prompt

Suggested values: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.

### `%final`

Select configured finalizer instances for this launch

Suggested values: `none`.

### `%id`

Assign an agent ID with optional bead, clan, session, or user-managed tribe

| Keyword | Meaning | Suggested values |
| --- | --- | --- |
| `bead` | Associate this launch with a bead, including a closed bead; see [Bead Claim Lifecycle](../work-units/bead-lifecycles.md#bead-claim-lifecycle) | — |
| `clan` | Derive the full ID and join this agent clan | — |
| `session` | Attach this suffix to an existing agent session | — |
| `family` | Attach this suffix to an existing agent session | — |
| `tribe` | Assign this agent to a user-managed tribe | — |

### `%clan`

Declare a new parallel agent clan

| Keyword | Meaning | Suggested values |
| --- | --- | --- |
| `summary` | Attach a Rich-markup summary to this clan | — |
| `summary_script` | Generate this clan's summary with an executable script | — |
| `tribe` | Assign this clan to a user-managed tribe | — |

### `%wait`

Wait for another agent/workflow and/or a time floor

| Keyword | Meaning | Suggested values |
| --- | --- | --- |
| `agent` | Wait for an explicit agent identity | — |
| `bead` | Wait until this bead is closed | — |
| `for_epic` | Also wait for any epic these agents launch | `true`, `false` |
| `hood` | Wait for current members of this agent hood | — |
| `proc` | Wait for a proc ID or proc name | — |
| `time` | Start after a duration or absolute wall-clock time | `5m`, `1430` |
| `unit` | Wait for a logical launch unit ID | — |

### `%queue`

Set this launch's capacity budget, <M>x multiplier of this machine's max_running_agents budget, priority, and capacity weight

Suggested values: `1`, `100`, `1.5x`.

| Keyword | Meaning | Suggested values |
| --- | --- | --- |
| `capacity` | This launch's capacity budget, replacing max_running_agents, or <M>x multiplier of this machine's max_running_agents budget | `1`, `100`, `1.5x` |
| `p` | Alias for priority=; lower values start first | `10`, `1` |
| `priority` | Lower values start first; the default is 10 | `10`, `1` |
| `w` | Alias for weight=; non-negative capacity units claimed by this launch; 0 adds no load | `0`, `0.25`, `1.0`, `2.0` |
| `weight` | Non-negative capacity units claimed by this launch; 0 adds no load | `0`, `0.25`, `1.0`, `2.0` |

### `%hold`

Hold selected pre-run agents until this launch settles

Suggested values: `pending`, `future`.

| Keyword | Meaning | Suggested values |
| --- | --- | --- |
| `hood` | Hold launches in this agent hood | — |
| `scope` | Choose whether the hold applies to this project or host | `project`, `host` |
| `ttl` | Maximum hold duration | `20m`, `1h` |
| `tribe` | Hold launches assigned to this user-managed tribe | — |

### `%dispatch`

Send this launch to an enrolled remote machine

### `%tab`

Place this launch's presentation root on a named agent tab

### `%if`

Statically omit a prompt segment, or gate launch with a typed predicate

| Keyword | Meaning | Suggested values |
| --- | --- | --- |
| `should_run` | Statically keep or omit this prompt segment | `true`, `false` |

### `%proc`

Launch a stand-alone proc unit with a Bash or Python body

| Keyword | Meaning | Suggested values |
| --- | --- | --- |
| `bash` | Bash script body | — |
| `python` | Python script body | — |
| `timeout` | Total execution timeout from child start | `20m`, `1h` |
| `idle_timeout` | Idle-output timeout from child start | `20m`, `1h` |
| `cwd` | Working directory for the proc | — |
| `workspace` | Whether to acquire an operational workspace lease | `true`, `false` |
| `label` | Descriptive label; never identity | — |

### `%auto`

Request automatic gate resolution; use %auto, %auto+, or %auto:<mode> with mode plan, tale, or epic. %auto:manual and %auto:off disable automatic approval; any other spelling fails at launch

Suggested values: `plan`, `tale`, `epic`, `manual`, `off`.

### `%hide`

Hide the agent from the default Agents tab display

### `%repeat`

Run the prompt multiple times

Suggested values: `2`, `3`.

### `%alt`

Split prompt into variants with different text; shorthand %{A | B}

### `%macros_enabled`

Enable or disable macro expansion for a text region

Suggested values: `false`, `true`.
