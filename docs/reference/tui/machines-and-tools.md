---
title: Machines, statistics, and tools
description: Machines, Statistics, and Tools tabs plus the Config Flags pane in the sase TUI.
---

# Machines, statistics, and tools

This page lists the Machines, Statistics, and Tools tabs and the Config Flags pane.

## Config Flags pane

Open **SASE Admin Center** with `#`, then Config > **02 Flags**. The pane is the
keyboard-first control surface for every code-owned SASE feature flag. It shows
effective state, kind, default, provenance, saved machine preference, description,
removal bead, and removal horizon; it does not edit portable configuration files.

Config's nested catalog is:

```text
01 All · 02 Flags · 03 Holds · 04 Launch · 05 Memory · 06 Snippets · 07 Macros
```

`sase flag enable` and `sase flag disable` remain available alongside the pane as the
automation surface.

The pane uses the Admin Center list/detail layout: a header with registered/on/saved
counts, a flag rail, a scrollable detail card, a hidden inline filter, and a one-line
footer. Effective on/off and source are shown separately from saved on/off. When
environment or root CLI `-f`/`-F` still wins, a yellow “forced for this process” warning
explains that saving restarts sase's TUI and the service host but will not take effect
until that override is removed.

| Key              | Action                                                                             |
| ---------------- | ---------------------------------------------------------------------------------- |
| `/`              | Open an inline filter over key, description, kind, effective state, and provenance |
| `Esc`            | Close/clear the filter before closing Admin Center                                 |
| `j` / `k`        | Move the rail; arrows, Home/End, and mouse clicks work the same way                |
| `q`              | Close Admin Center                                                                 |
| `Enter`/`Space`  | Open a cancel-first confirmation (`OFF -> ON` or `ON -> OFF`)                      |
| `r`              | Reload the catalog                                                                 |
| `0` then `1`–`7` | Jump to a numbered Config child                                                    |

Confirmation is cancel-first. It names the flag, the current-to-target state, the saved
state path, any shadowing source, and that **sase's TUI and service host restart after
TUI tasks and installation changes finish**. Confirming writes only the machine-state
file, waits up to 60 seconds for TUI-local work and installation mutations, then
performs one controlled sase's TUI+service-host restart. Independent commands keep
running. Durable operations started from this TUI still finish their result handling
first, within the same 60-second wait. A restart failure does not roll back the saved
preference.

See [feature flags](../config/feature-flags.md#featureflags) for precedence, the
state file, and the CLI contract.

## Machines Tab

Open the SASE Admin Center with `#`, then press `3` or select **Machines**. This is a
local inventory and administration surface for the controller plus every enrolled
remote. It does not contact all gateways when opened: remote rows begin with state **not
checked** and health **unknown** until you request an explicit status check. Remote
capacity remains **not reported** even after that check because the status response does
not carry runner capacity. The local row reports the controller's configured runner
capacity immediately.

The list shows Alias, State, Health, Capacity, Last observed, and Endpoint. The local
Alias is the controller's configured machine name even though its Agents query token is
`here`. The detail card adds capabilities, provider, pinned installation identity,
quarantine state, and the status message from the most recent check while this Admin
Center remains open.

| Key       | Action                                                                                               |
| --------- | ---------------------------------------------------------------------------------------------------- |
| `j` / `k` | Move selection                                                                                       |
| `/`       | Filter aliases, endpoints, providers, installation identity, and quarantine                          |
| `s`       | Run one bounded authenticated hello for the selected remote                                          |
| `c`       | Show the persistent connect/enrollment flow                                                          |
| `r`       | Show repair guidance for the selected remote                                                         |
| `R`       | Show the rename command for the selected remote                                                      |
| `x`       | Show removal guidance for the selected remote                                                        |
| `y`       | Copy the commands shown in the action card                                                           |
| `Enter`   | Close Admin Center and open this machine's agent tab (or filter Agents when the tab strip is hidden) |
| `f`       | Close Admin Center and open Agents filtered to this machine                                          |
| `U`       | Reload local machine inventory without probing gateways                                              |

Connect, repair, rename, and remove are guidance actions: they display canonical CLI
commands and safety notes but do not mutate machine state themselves. `Enter` selects
the machine's agent tab when the tab strip is visible, and otherwise applies an Agents
query of `machine:local` for the local controller or `machine:<alias>` for a remote (`f`
always filters). See the
[Remote Dispatch Runbook](../integrations/remote-dispatch.md) for the
credentialed enrollment and recovery procedures.

## Statistics Tab

Open the SASE Admin Center with `#`, then press `6` or switch to **Statistics**. Its
eight sub-tabs summarize overview, runners, projects, providers, agent activity, macro
usage, plan/question activity, and performance for the selected time range. The strip is
numbered **01 Overview · 02 Runners · 03 Projects · 04 Providers · 05 Activity · 06
Macros · 07 Plans & Questions · 08 Perf**; press `0` and then the second digit to jump
straight to a view. The Admin Center-wide `'` entry-jump key arms this same
numbered-view selection instead of painting row hints — Statistics has no row cursor, so
the already visible strip numbers act as its jump hints; `Esc` or any non-digit cancels.
Use `[` / `]` to move between views, `t` / `T` to cycle time ranges, `c` to enter a
custom range, `p` / `P` to cycle project scope, `Ctrl+D` / `Ctrl+U` to scroll, `r` to
refresh, and `?` for the pane's key help. First open seeds the project filter from the
[current project](projects-tab.md#current-project) when `ace.current_project.seed_filters` is on; `p` /
`P` can always cycle away from that seed, including back to **All projects**. On Overview, Agents Run, Success Rate, and **Run commits (this machine)** open
Projects; Plans Proposed and Questions open Plans & Questions. The Projects sub-tab
reports default-branch output, committed plans, lifetime code, and this machine's runs.
Press `g` to group by project, repo, language, model, or Project → Patch. Output and
Runs paint first while Code measures. Overview's run-commit tile stays run-recorded and
is distinct from Projects default-branch commits and Patch Run commits.
A one-project report breaks commits down by code repo directly under OUTPUT; sidecar
repos are excluded, `—` marks unmeasured repos, and `≥` marks lower bounds from partial
history. With several projects in scope, `g` → repo shows a Project → Repo tree.
The summary card's `by lang` rows show each language's share of source plus test
lines and the repos or projects that hold them. `g` → language shows the Language →
Repo tree with exact lines, files, and shares. Repo `CODE LINES` count source plus
test lines.

The Projects report is also available through [`sase stats project`](../cli/stats.md),
with the same definitions in the terminal, Markdown, and JSON outputs:

| Section | What it measures | Time basis |
| ------- | ---------------- | ---------- |
| Output | Commits in code repositories and plans first committed to the plan store | Committer time within the selected range |
| Code | Source and test lines, documentation, agent context, languages, and repository age | Committed-tree snapshot and lifetime history |
| Runs | Agent runs launched on this machine, their outcomes, durations, and attributed Patches | Launch time within the selected range |

**Agent share** is the fraction of commits with an agent footer. In model breakdowns,
`?` means attribution could not resolve a model; `∅` means no agent footer on a commit,
or neither `proposed_with` nor `proposed_by` on a plan. A plan's `proposed_with` model
takes precedence over attribution through its `proposed_by` agent. Both `?` and `∅`
remain in the totals. **Success** divides completed runs by all runs, including runs
still in progress. **Tests** divides test lines by source plus test lines; documentation
and agent-context lines have separate counts. **Age** uses the earliest available commit
author timestamp; **Active days** counts distinct author dates in the SASE timezone.

The coverage footer identifies incomplete repository measurements and unresolved model
attribution. Code-repository measurements use the local `origin/HEAD` ref (the remote's
default branch), falling back to the checked-out `HEAD` if that ref cannot be resolved.
Results can differ between machines with different local refs. The CLI's fetch option
fetches from `origin` before measurement; a failed fetch reports an issue and uses local
refs. Local run counts remain specific to the machine that recorded them.

The **Perf** sub-tab combines five headline measures—Startup (median visible-ready),
Stalls (stall count, with hitches named separately in the tile's detail line), Launch
(p95 total launch time), Agent p95, and LLM p95—with startup stages, stall/hitch events,
grouped latency and reliability, and source-coverage diagnostics. Press `g` to group
latency by subsystem, provider, or workflow; the grouping also decides what the count
column counts (LLM invocations, agent runs, or an ungrouped count) and whether a Share
column applies. Perf counts come from telemetry and TUI logs, not the artifact index, so
they are not comparable with the run counts on the other sub-tabs. Perf is global: the
project chip remains visible but is marked **not applied**. See
[Reading the Admin Center Perf view](../../contribute/perf-runbook.md#reading-the-admin-center-perf-view)
for data sources, retention, and probe details.

The Statistics **Macros** sub-tab reports macros referenced by agent launch prompts:

- **By Usage** ranks macros by runs and shows references, share, agents, success,
  runtime, and recency.
- **By Model** breaks each macro down by model.
- **By Project** breaks it down by project.
- **Used With** shows macros referenced together in the same run.

Press `g` to cycle those four groupings without reloading the underlying statistics.
Press `x` to choose one macro and replace the ranking with its full time, model,
project, provider, tribe, and co-usage breakdown; press `X` to clear that focus. The
range and project filters apply before all macro aggregation.

These counts come from each run's launch-boundary `macros.json`, recorded before prompt
expansion. A run counts once per macro name, while **Refs** counts distinct argument
variants of the same name separately. References introduced inside workflow step
templates are intentionally excluded. Historical runs appear after the agent-artifact
index rebuilds at the current schema.

Each record carries a kind — `workflow`, `part`, or `swarm`. A macro swarm is consumed
by the dispatcher before any agent starts, so it never appears as a lexical reference in
a child's prompt; instead the swarm is attributed to every agent it launched, and a
nested swarm records every link of its chain. Because swarm records carry no arguments,
**Refs** equals **Runs** for a swarm row. Attribution is forward-only: runs launched
before this feature shipped are not backfilled.

This Statistics sub-tab is distinct from Config's **Macros** child described in
[Macro Browser](snippets.md#macro-browser): that child browses and edits
macro definitions, while the Statistics sub-tab measures how launch prompts used them.

## Tools Tab

Open the SASE Admin Center with `#`, then press `7` or switch to **Tools**. Its three
sub-views cover **Runs** (silent runs pinned first in red, then live, then settled
newest first), **Failures** (failure-signature groups with run and agent witness
counts), and **Catalog** (the current project's named tools with LAST and TYPICAL from
the run ledger). The pane is filtered to the current project by default; press `A` to
widen it to all projects. Use `[` / `]` to move between views, `/` to filter Runs with
`tool:`, `state:`, `agent:`, and `verdict:` tokens, `enter` to focus detail (`Failures`
lists the group's affected runs newest first with their agents), `a` to jump to the
run's ⚒ Runs block on the owning Agents row, `v` to open the retained log in the pager,
`y` to copy the run id, `s` to stop the focused live run (same DANGER confirm as the
Agents tab), `r` to run the focused catalog tool at the current project root, and `R` to
reload. The Runs detail reuses the Agents tab Runs block renderer. The pane never
settles or reconciles runs; the only writes it offers are the explicit stop and
catalog-run flows. The top-bar `tools:` group opens this pane with all projects, so the
pane never shows fewer runs than the chip claims.

<a id="models-panel"></a>

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [SASE Admin Center](admin-center.md) — Config, Logs, Machines, Procs.
- [Projects tab](projects-tab.md) — add, initialize, and current project.
