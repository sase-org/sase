---
title: Procs tab
description: The Procs tab layout, status icons, monitors, durable procs, filtering, and keys.
---

# Procs tab

This page lists the Procs tab layout, status icons, monitors, durable procs, filtering,
and keys.

## Procs Tab {#procs-tab-1}

Open the SASE Admin Center with `#`, then press `4` (or switch tabs until you reach
**Procs**). You can also run the keyless **Open procs panel** command from the command
palette. The tab shows procs (hook runs, mentor executions, agent launches, plugin
operations, etc.) with live output for running procs and completed output for finished
ones.

### Durability and Scope

Procs the TUI runs itself are **mirrored** into the durable proc store
(`~/.sase/procs/procs.jsonl`, with one combined output log per proc under
`~/.sase/procs/logs/`), so their outcome survives the session that produced them and is
visible from `sase proc list` / `sase proc show`. Supervisor-backed procs — commands
submitted with `sase proc run`, programmatic submissions, and the unattributed command
fallback for an epic approval whose planner agent session cannot be resolved — are read
back out of that store and rendered here, so work that this process never owned still
shows up on the tab.

The pane defaults to **this session** plus unattributed procs; press `a` to widen it to
every session. Historical `detached` rows remain visible in both modes. The pane title
names the active scope and the running-lane counts, e.g.
`Procs · this session   ⚙ 2  ⚒ 1  ⚙ 1   [4 running · 5 done]`. The blue gear is running
TUI background procs — the same rows the top-bar `bg:` group counts, excluding monitors,
tool-run carriers, and update rows; the sky-blue `⚒` chip is tool-lane procs (an
inventory count, so it shows a dim `⚒ 0` when empty — it can differ from the top-bar run
count because foreground runs have no proc and a joined run has two); the orange gear is
bare monitors. A green `⚙ N` chip appears after the orange chip only while update procs
run, and update rows carry a green `⚙` marker. All counts follow the tab's current
scope, so `a` moves them with the list. A zero blue/orange lane still renders as a dim
`⚙ 0` so a missing chip cannot be read as "unknown". The bracketed totals keep their
current meaning: blue plus tool plus green plus orange equals the running count. Rows
read from the store carry a colored session chip (`ace·sase#14 4f2a`) that matches the
one `sase proc list` prints; a session that has since exited renders dim with a `†`. An
ordinary unattributed proc renders a dim `—`; a historical detached proc carries a cyan
`◆ detached` marker that makes the detached row kind explicit.

Store reads happen on a worker thread and are revalidated by store mtime about once a
second, so the tab never stats, reads, or locks the store from a render or keystroke
path. Retention is governed by `procs.history_limit` (see
[configuration](../config/runtime-and-storage.md#procs)): finished rows and their
logs age out oldest-first, and running procs are never pruned. Because the store owns
that retention, `d` / `D` do not dismiss rows; they only explain the retention policy.

The top-bar `bg:` group's blue chip counts this session's active background procs plus
**every active unattributed proc globally**, including an approved epic that had to use
the unattributed command fallback. Tool-run carriers are counted in `tools:` instead,
running bare monitor turns in the orange chip there, and service procs and oneshots are
left to the Services tab.

### Layout

The tab uses a two-panel layout: a proc list on the left and an output pane on the
right. Running procs refresh their output on the pane's 0.25 s tick while the Procs tab
is visible.

### Opening a row

With the proc list focused, `Enter` or a click opens the first matching destination
below. The hints line can list more than one `⏎:` token when a row qualifies for more
than one action; these are not separate choices, and their display order does not
determine what opens. Jump mode (`'`) selects a row by its hint without opening it.
While jump mode is active, the hints line shows the jump prompt and these opening
actions do nothing.

1. **Command Line** (`command-line` tag). Admin Center closes and the
   [Command Line](global-controls.md#command-line) opens on that block. The hint is `⏎: block`. A missing
   record still opens the panel and says the record was pruned.
2. **Tool run.** The row's `tool-run:<id>` tag wins. If that tag is absent, a
   `tool-run-join:<id>` tag is used. Admin Center stays open and switches to **Tools**,
   focused on that run. The hint is `⏎: run`. This is how a monitor that reserved a run,
   and a monitor that joined one with `sase monitor start -J`, open the run. Those rows
   show `⚒`.
3. **Monitor without a run tag.** When the monitor's agent row is loaded, Admin Center
   closes and the Agents tab reveals that agent. The hint is `⏎: agent`, and only when
   the jump can land. If the agent is not on the Agents tab, sase's TUI says so and
   stays put.

A row that is none of these does not navigate.

### Proc Status Icons

| Icon | Color  | Meaning                                                    |
| ---- | ------ | ---------------------------------------------------------- |
| `◌`  | Dim    | Pending (supervisor starting)                              |
| `●`  | Green  | Running                                                    |
| `✓`  | Cyan   | Success                                                    |
| `✗`  | Red    | Error                                                      |
| `⊘`  | Yellow | Killed                                                     |
| `?`  | Dim    | Unknown                                                    |
| `⚙`  | Orange | Monitor turn (same mark as the Agents tab and the top bar) |
| `⚒`  | Sky    | Tool-run carrier (same mark as the `tools:` group)         |

### Monitors on this tab

A `sase monitor start` supervisor is a durable proc like any other, but this tab marks
it the same way the rest of sase's TUI does. See
[Monitors](../automation/monitors.md).

- **Orange `⚙`.** Bare monitor rows carry the orange gear between the status icon and
  the label (`● ⚙ just check-full`), matching the Agents tab and the orange chip in the
  top bar's `tools:` group. A monitor carrying a live run shows `⚒` instead. The same
  mark prefixes the output header.
- **Agent name.** Each monitor names its member agent (`acme--mon`) on the list's
  secondary line (`acme--mon · Working...`) and on an `agent` line in the output header.
- **Status chip.** When the matching agent row is loaded, the effective status label
  (`TESTING` while running, `TESTED` once settled) appears in that pair's accent color
  between the agent name and the secondary text (`acme--mon · TESTING · Working...`),
  and again on the output header's `agent` line.
- **Live `live_reply.md`.** While the Procs tab is active, the 0.25 s tick refreshes the
  selected running proc. For a monitor, that output is the tail of
  `<artifacts_dir>/live_reply.md`: the last 400 lines, including text rotated into
  `live_reply.md.1`. Until that log has text, the pane still shows `Working...`. On the
  Agents tab, the Reply card follows that same file in place when the live-reply follow
  is active; see
  [Agents Tab Main Deck](agents-main-deck.md#agents-tab-main-deck-1).
- **`<enter>`.** A monitor that owns or joined a tool run opens that run (`⏎: run`). A
  monitor without a run tag whose agent is loaded jumps to the Agents tab (`⏎: agent`).
  Command Line rows take precedence over both destinations. See
  [Opening a row](#opening-a-row).
- **Visible in both scopes.** Monitor procs are unattributed, so they appear in both
  **this session** and **all sessions**.
- **`K` stops the supervisor.** Kill uses the named-proc stop path: it stops the
  supervisor, settles the session, and runs any `--next` action.

### Durable Procs

Procs are durable records shared by every SASE surface, not just rows in this pane. They
live in `~/.sase/procs/procs.jsonl`, with one combined stdout/stderr log per proc under
`~/.sase/procs/logs/<proc_id>.log`. Because the records outlive the process that
produced them, `sase proc` can list and inspect work started anywhere — including a
TaskTriage launch or unattributed command submitted from another client.

Each proc carries a 12-character id resolvable by unique prefix (three characters
minimum, like a git short SHA), so `sase proc show k7m2` works. Statuses are `pending`,
`running`, `success`, `error`, and `killed`; terminal states are final, and a proc whose
supervisor died without reporting is reconciled to `error` rather than left running
forever. `sase proc list` reuses the icons above and adds `◌` for pending and `⊘` for
killed.

A proc may also carry a **named proc**: `sase proc run -N/--name NAME` (bare names
resolve beneath the calling sase-agent; `agent/name` is fully qualified) names the proc
so `sase proc show`, `sase proc list -N`, and `sase proc kill` can address it by name
instead of id. Resolution tries an exact fully qualified name, then an exact proc id,
then a unique id prefix. Active uniqueness is scoped per project — starting a proc under
a name already held by an active proc in the same project is a conflict — and a name is
only reusable once the proc holding it settles. A monitor's member agent name (for
example `acme--mon`) is its own named proc.

**Kinds and ownership.**

| Kind       | Typical producer                                          | Owner and scope                                                     |
| ---------- | --------------------------------------------------------- | ------------------------------------------------------------------- |
| `tui`      | Work run and mirrored by sase's TUI                       | sase's TUI process; scoped to its session                           |
| `command`  | `sase proc run` or `sase.procs.submit_proc()`             | The proc supervisor; attributed to one session or left unattributed |
| `detached` | Historical rows from retired CLI/API detached submissions | The detached proc supervisor; global because no session owns the row |

The programmatic submission API is `sase.procs.submit_proc()`. Pass `session_id=None`
when no interactive session should own the row; it still writes a `command` proc. See
[TUI migration notes](../upgrading/tui.md#detached-procs) for the older detached
wrapper. The public `read_procs()` and
`filter_procs()` helpers accept `kind=` as either one kind or a collection, including
`detached` when a caller needs historical rows. A `command` or historical `detached` row
that remains `pending` without a supervisor PID for 60 seconds is reconciled to `error`;
a mirrored `tui` row is left to its owning TUI. Epic launches record the approving
surface as `ace`, `telegram`, `cli`, or `axe`, with `api` retained as the fallback for
direct or unrecognized API callers.

Session attribution controls which TUI includes a proc by default; the proc still
executes under its own supervisor. Here, a **TUI session** is one running TUI process,
not an agent session. The attribution rules depend on how the proc starts.

A hand-off tool-run proc (`sase tool run -H`, `sase tool run -d`, or the automatic
reservation path) is stamped only when the submitting process is itself a live
registered TUI session, such as a catalog launch started inside sase's TUI. An agent
escalation, a detached run, and a human shell `-H` leave the proc unattributed even when
another TUI is open. There is no latest-session fallback, and a failed session lookup
still submits the proc with no session. Unattributed rows stay visible in **this
session**.

For `sase proc run` and `sase proc list`, `--session` accepts a full session id, a
unique id prefix or short handle, or `current`, `latest`, and `none`. The default
(`current`) uses this process's registered TUI session, then the newest live one, then
no session. This latest-session fallback applies to these proc commands, not to tool-run
hand-offs. `sase proc run --session none` creates an unattributed command row.
`sase proc list` scopes work to the resolved session plus unattributed rows by default,
and widens to every session with `--all`. Rows from a session that has since exited
render dim with a `†` marker.

**Retention.** [`procs.history_limit`](../config/runtime-and-storage.md#procs)
caps how many _finished_ procs are kept; pending and running work is never pruned for
being old. Lowering the limit removes the oldest finished rows and their log files.
Finished procs tagged `command-line` (TUI Command Line submissions) keep a separate
bucket of 50 beside this limit. See
[TUI migration notes](../upgrading/tui.md#config-and-keymap-aliases) for the older
`tasks.history_limit` key.

The CLI equivalents are `sase proc list`, `sase proc show ID` (`--follow` to stream),
`sase proc run [--session SESSION|none] -- COMMAND` (`--wait` to stream and inherit the
exit code), and `sase proc kill ID`. A hidden `--kind` filter remains for
historical kind rows; see [TUI migration notes](../upgrading/tui.md#detached-procs). Approved epics normally launch as
[monitor turns](../automation/monitors.md); only an unresolvable planner agent
session uses an unattributed command proc. See the generated [`sase proc`](../cli/proc.md) page.

### Filtering procs

Press `/` to reveal a query bar above the proc list, prefilled with the query already
active. Typing narrows the list live; the status lane shows `N matches` or a parse error
with its exact span. `Enter` commits and returns focus to the list; `Esc` restores the
query that was active when the bar was opened. Unlike the Artifacts panes, the bar is
**hidden when there is no query** and appears — read-only, syntax-highlighted — only
while a filter is active, so an active filter is never invisible without also being
silent. The header gains a `· N/M shown` segment while filtered, and the query survives
closing and reopening the Admin Center in the same session.

Free text (and its explicit `text:` spelling) matches the command string, the row label,
and the retained output; `cmd:` and `out:` narrow to one side. Every key is negatable
with a leading `-`, and a boolean key takes the bare shorthand (`monitor` means
`monitor:true`). The `service` boolean matches service-proc runs (daemon or oneshot),
and `svc:<name>` narrows to one service proc by exact name. `tag:<tag>` matches a proc
tag exactly (for example `tag:command-line` for Command Line runs, visible by default),
and `origin:<origin>` matches the submitting origin (for example `origin:ace`).

The seeded default query is `-service`, so service-proc runs stay hidden unless asked
for; `ace.procs.default_query` in `sase.yml` changes the seed. It applies only when no
committed query is persisted — a user-cleared query stays cleared.

| Key        | Kind     | Meaning                                                        |
| ---------- | -------- | -------------------------------------------------------------- |
| free text  | string   | Command, label, output (implicit AND); same as `text:`         |
| `cmd:`     | string   | Command string only                                            |
| `out:`     | string   | Retained output only (last 32 KB)                              |
| `name:`    | string   | Row label / display name                                       |
| `agent:`   | string   | A monitor row's member agent name                              |
| `project:` | string   | Project key or display name                                    |
| `status:`  | enum     | `pending`, `running`, `settling`, `success`, `error`, `killed` |
| `kind:`    | enum     | `command`, `tui`, `detached`                                   |
| `monitor`  | bool     | A `sase monitor start` named proc                              |
| `service`  | bool     | A service proc run (daemon or oneshot)                         |
| `svc:`     | string   | Service name (exact)                                           |
| `tag:`     | string   | Proc tag (exact, for example `command-line`)                   |
| `origin:`  | string   | Submitting origin (exact, for example `ace`)                   |
| `running`  | bool     | Active and owned by a live session                             |
| `failed`   | bool     | Terminal status is `error` or `killed`                         |
| `exit:`    | int      | Exit code (exact)                                              |
| `min:`     | duration | Runtime at least N seconds (or `5m`, `2h`, `1d`)               |
| `max:`     | duration | Runtime at most N                                              |
| `after:`   | date     | Completed at or after the bound                                |
| `before:`  | date     | Completed at or before the bound                               |
| `since:`   | date     | **Started** at or after the bound                              |
| `until:`   | date     | **Started** at or before the bound                             |
| `limit:`   | host     | Row cap; `all` removes it                                      |

Runtime is `(finished_at or now) - started_at`, so `min:`/`max:` read sensibly for a
still-running proc too. `before:`/`after:` bound **completion** time and `since:`/
`until:` bound **start** time; a running proc has no completion time, so
`before:`/`after:` never match it and `-before:X` includes it. For example,
`"just check" -monitor -min:300` matches non-monitor procs that ran for at least five
minutes and mention `just check` in their command or output.

`m` cycles the `monitor` term through three states without opening the bar for editing:

```
(no monitor term)  →  monitor  →  -monitor  →  (no monitor term)
```

Each press rewrites the query in place, leaving every other term untouched, and never
steals focus from the row list. If the monitor term was the query's last term, the last
press clears the filter and removes the bar.

### Keybindings {#keybindings-2}

Default configurable actions are listed in the generated
[TUI keymaps reference](keymaps.md). This page keeps Procs-tab behavior details.

| Key                 | Action                                             |
| ------------------- | -------------------------------------------------- |
| `j` / `k`           | Navigate proc list                                 |
| `/`                 | Filter procs                                       |
| `m`                 | Cycle the `monitor` filter                         |
| `'`                 | Jump to a proc row via adaptive hints              |
| `a`                 | Toggle scope: this session / all sessions          |
| `K`                 | Request a kill for a selected active durable proc  |
| `Enter`             | Open the selected monitor's agent                  |
| `d`                 | Explain finished-proc retention (does not dismiss) |
| `D`                 | Explain finished-proc retention (does not dismiss) |
| `e`                 | Open proc output in `$EDITOR`                      |
| `y`                 | Copy proc output to clipboard                      |
| `Ctrl+D` / `Ctrl+U` | Scroll output pane down / up                       |
| `g` / `G`           | Jump output pane to top/bottom                     |
| `Tab` / `Shift+Tab` | Switch Admin Center tabs                           |
| `q` / `Esc`         | Close SASE Admin Center                            |

`K` and `D` also answer to `Shift+K` and `Shift+D`, matching the pane's existing
`Shift+G` convention. `d` and `D` currently perform no dismissal; both explain that
finished rows age out according to `procs.history_limit`.

`K` opens a danger confirmation only for a store-backed row that sase's TUI still
considers active. The backend stops command/named-proc records, including monitor
supervisors. It refuses a TUI-owned record because only its owning sase's TUI session
may stop it, and a `detached` record whose supervisor has died is reconciled to `error`
rather than killed. Other ineligible rows explain why: a finished proc reports
`Proc already finished`, a proc still being submitted reports
`Proc is still submitting — try again in a moment`, and a session-local row with no
durable record reports that it cannot be killed from the Procs tab.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [SASE Admin Center](admin-center.md) — Config, Logs, Machines, Procs.
- [Services tab](services-tab.md) — sidebar, jobs, and control keys.
- [TUI keymaps](keymaps.md) — generated keymap defaults.
- [TUI migration notes](../upgrading/tui.md) — detached procs and history-limit alias.
