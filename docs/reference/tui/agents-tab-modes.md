---
title: Agents tab search and modes
description: Search, leader, bang, and copy modes on the Agents tab.
---

# Agents tab search and modes

This page covers Agents tab search, the leader, bang, and copy key modes, and the
machine and repository context rows.

## Machines

When at least one remote machine is enrolled, the Agents tab shows local and remote rows
in one list. Remote agent, session, and clan nodes carry a short host-alias chip such as
`apollo` or `mac`; local rows never carry a `here` chip, including under a by-machine
group header. A fleet header row appears above the list only when there is something to
act on. A fleet configuration or follow-store error is shown on its own; otherwise the
row joins machine diagnostics and machine feed errors with `·`. Diagnostics naming one
or two machines read `apollo unknown` (or `apollo, mac unknown`); anything else reads as
a diagnostic count such as `3 machine issues`. One machine feed error reads
`<alias>: feed <status>: <detail>`, with `(cached 5m ago)` when a cache backs it; two or
more read `2 machines with feed errors`. Otherwise the row stays hidden. An entirely
local setup keeps the compact local view and exposes the machine connection route.

Remote rows use the same visible operations where the owner advertises support: machine
status, retry, bounded remote content, pending question/gate handling, stop, and fork.
The normal `x` stop and `F` fork actions work on capable remote rows; actions that
require local files, tmux, or local Patch state stay unavailable. Remote mutations are
durable requests, optimistically annotate the row while in flight, and refresh the
Agents list after they settle. Setup and recovery commands are covered by the
[Remote Dispatch Runbook](../../remote_dispatch.md).

Remote agents are grouped into the same session and clan nodes as local ones, with the
same queue badges (`cN`, `wN`) and the same session and clan status rules. A remote row
stays free of connection chrome while its machine's feed is online and fresh; anything
else is shown on the row. A stale feed reads like `stale · cached 5h ago`, and an
invalid feed reads `feed invalid`, is named in the Agents header, and adds a **Feed
error** line to the detail panel, so cached data never looks silently healthy. A remote
row the owner reports as `WAS RUNNING` shows how long ago it was `last seen`.

## Opened Repository Context

Configured `linked_repos` are recorded in agent metadata at launch time, while linked
and external repos opened during a run are recorded in opened-repository markers. For
non-terminal agents, sase's TUI can include dirty opened repos in the agent detail
`SASE CONTEXT` `ARTIFACTS` lane under `Deltas`. The field counts primary and opened-repo
changes together, groups linked and external entries under distinct glyphs and canonical
repo names, and resolves file hints relative to the opened repo directory. Missing
workspace directories, clean repos, and completed/failed agents are not part of this
live delta display.

When a SASE-launched agent uses `/sase_repo`, the run records an opened-repository
marker. The underlying command infers the host project and workspace from cwd;
configured linked repos remain backed by hidden `PROJECT_STATE: sibling` project
records, while external repos remain workspace-local and create no project record.
sase's TUI shows the markers in the prompt/detail `SASE CONTEXT` section with the repo
name, kind, resolved path, open time, and reason. Live deltas, commit diffs, and revert
all retain the canonical external name (for example, `gh:pallets/click`); reverting an
external repo discards local clone changes without re-cloning from the network.

## Agent Search

Press `/` or `f` on the Agents tab to open the auto-hiding filter bar. `,/` (leader
mode) starts forward inline deck search over the focused deck panel — the text of all
Main cards (with card titles as separators), the Files view content, or the Tools LLM
Calls text: type to jump to matches, `Ctrl+R` reverses the search direction, `Enter`
keeps the matches (`Esc` or `Ctrl+C` cancels), `n` / `N` move between them, `y` / `Y`
yank the current match or selection / its whole line, and `Esc` or `q` closes a
committed search. The filter bar uses the same **structured Boolean Agent dialect** as
the Archive view (`in:archive`) and [`sase agent search`](../../configuration.md#sase-agent),
evaluated against the live `agents-live` profile. Bare words match an agent's `cl_name`,
`display_name`, `agent_name`, and `status`, plus its **macro, live reply/response, chat
transcript, and prior attempt replies** through the `text` corpus. When
`ace.current_project.seed_agents_query` is on, sase's TUI seeds this query with the
current project's exact `project:` term on first load and marks it `seeded` until you
edit it. That setting defaults **off** because the same query also drives unread jumps
and prospective clans. While a filter is active, the Agents header shows it as
`filter: <query>` with any `seeded` marker, a `[matched/loaded]` count, and the edit-key
hint; clicking the query opens the filter bar.

The bar previews each valid edit against the loaded snapshot, `Enter` commits and adds
the previous query to history, `Escape` restores the pre-edit query and result, `Tab`
accepts completions, and `^` / `_` walk query history while the bar is open. Each
successful `Enter` commit is remembered in machine-local SASE state and restored in the
next sase's TUI session; submitting an empty or whitespace-only query remembers the
unfiltered view. Typing, `Escape`, invalid submits, history preview, saved-slot
commands, and `,/` deck search do not replace the remembered query.

Restored Agents queries are applied before provider filtering and before current-project
seeding. A restored query does not push history, change saved-query slots, or write back
to disk until you submit again. Non-empty remembered records from the inactive query
dialect, or from an older `agents-live` profile, are ignored with a warning; explicit
empty records restore across dialects.

A leading `#` saves or deletes an Agents-tab saved-query slot in the `agents-live`
namespace: `#3 status:FAILED`, `# status:queued`, and `#3` save, allocate, or delete a
slot without changing the committed query.

Property keys (closed allowlist):

| Key                                                | Form                                    | Matching behavior                                                                                                               |
| -------------------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `name`, `session`, `clan`, `project`               | `key:value`                             | Exact, case-insensitive identity fields; completions include observed values.                                                   |
| `kind`                                             | `kind:agent`, `kind:workflow`, etc.     | Enum for agent/member/session/clan/workflow rows.                                                                               |
| `status`, `provider`, `source`, `needs`            | `key:value`                             | Enums; `source` accepts `axe` / `manual`, and `needs` accepts `input`.                                                          |
| `role`, `workflow`, `model`, `cl`, `text`          | `key:value`                             | Case-insensitive substring fields; `text:` searches the full text corpus.                                                       |
| `machine`, `tribe`, `tab`                          | `key:value`                             | Exact live operational fields; `machine` accepts `here`, aliases, and hostnames; `tab` is exact and `main` means no stored tab. |
| `pinned`, `unread`, `hidden`, `attention`, `retry` | `key:true` / `key:false`                | Boolean properties.                                                                                                             |
| `since`, `until`, `after`, `before`                | `key:2h`, `key:today`, `key:YYYY-MM-DD` | Start and finish bounds; `Nh` / `Nd` / `Nw` / `Nm`, `today`, and ISO dates.                                                     |
| `min`, `max`                                       | `key:5m`, `key:1h`                      | Runtime duration bounds.                                                                                                        |
| `attempt`                                          | `attempt:2`                             | Retry attempt number.                                                                                                           |

Boolean operators: juxtaposition is implicit `AND`; explicit `AND`, `OR`, and `NOT` (or
`!`) are honored, and parentheses group expressions. Bare and quoted strings are
case-insensitive; prefix a quoted string with `c` for case-sensitive matching, as in
`c"FAILED"`.

Legacy token migration:

| Legacy (`agent_query`)                                                                                                            | Unified (`agents-live`)                    |
| --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| `type:workflow` / `type:run` / `type:running`                                                                                     | `kind:workflow` / `kind:agent`             |
| `age>2h`, `age>=2h`                                                                                                               | `until:2h` (started at or before 2h ago)   |
| `age<5m`, `age:5m`                                                                                                                | `since:5m` (started at or after 5m ago)    |
| `status:foo` (substring)                                                                                                          | `status:FOO` (enum, completion-assisted)   |
| `project:foo` (substring)                                                                                                         | `project:foo` (exact; completion-assisted) |
| `tribe:` (bare, "any tribe")                                                                                                      | no direct equivalent; OR explicit tribes   |
| everything else (`cl:`, `machine:`, `pinned:`, `needs:input`, `source:axe`, `text:`, booleans, `AND`/`OR`/`NOT`, parens, quoting) | unchanged spelling                         |

Parse failures are non-fatal: the filter bar renders the error inline and keeps the last
good result. When the bad token is a known legacy spelling such as `age>2h` or
`type:run`, the error appends the unified replacement hint.

A committed query also decides how much agent history is loaded. When the persistent
artifact index can answer every term exactly — `cl:`, `model:`, `provider:`, `project:`,
`kind:agent` / `kind:workflow`, and `machine:` (including a negated `machine:` filter),
combined with `AND` / `OR` — the loader selects matching agents from the whole archive.
Any other term (for example `status:`, `name:`, `tribe:`, `tab:`, or free text) is first
evaluated against the bounded recent-history window, and the header adds
`filtered on partial history; loading full history...` until a quiet-window full-history
reconcile finishes and older matches can appear. Whenever the applied roster is
knowingly less than the visible inbox for the current query — a fallback scan, a
truncated inbox, a query-incomplete read, or a committed-query change still loading —
the header shows a loading indicator instead (`⟳ loading agents...` with no filter
committed), which clears on the completing apply. Pushdown-miss queries are only partial
when the read was viewport-bounded or truncated; a non-truncated baseline read saw the
whole visible inbox.

Transcript files are read only by the background content-index worker while a query is
active and are cached by `(path, mtime_ns)` so auto-refresh stays cheap. Per-file reads
are capped at 512 KB; missing or unreadable files are skipped silently. Keystrokes do
string-level canonicalization only; row matching runs through the Rust-backed
`agents-live` query index.

## Leader Mode (`,` prefix) {#leader-mode-prefix-1}

Leader mode is available on every tab. In the Agents tab it also exposes notification
shortcuts for the currently loaded agent list; global entries such as `,m` and `,U`
behave the same from other tabs. Unread-completed actions operate on terminal rows that
are loaded in the Agents tab; `,j` can reveal a direct member hidden by a collapsed
clan. Help is not a leader command: press the app-level `?` to open the Help modal.

Here, "stopped" means a dismissable terminal row such as `DONE`, `FAILED`, `PLAN DONE`,
`TALE DONE`, `PLAN REJECTED`, `PLAN COMMITTED`, or `EPIC CREATED`; it is separate from
the Agents header's "stopped" attention bucket for rows paused on user action.

The CLI equivalent of `,x` without the edit pause is `sase agent restart NAME`: it stops
the named agent and immediately relaunches the stored prompt under the same name.

SASE also has a scheduler-driven [Agent Auto-Restart](../agent-auto-restart.md)
service for update-skew failures. An in-flight recovery appears as amber `↻ RESTARTING`
with a dim reason. A replacement keeps the same name and shows a `↻` chip plus
provenance describing the update and preserved error report (`v`). It allows at most one
automatic restart per lineage; see the guide's current probe/deferral limitation before
assuming that an eligible failure will relaunch. Inspect recovery with
`sase agent auto-restart list -a` and `sase agent auto-restart show NAME`.

If any agents are marked, `,x` acts on that marked set instead of the focused row. Stale
marks are ignored; if any remaining marked agent has no recoverable prompt, sase's TUI
warns and leaves the set untouched. After confirmation, sase's TUI kills or dismisses
the marked agents and opens a prompt stack with one editable pane per original prompt in
mark order. Embedded `---` inside an individual agent prompt stays inside that agent's
pane.

Each recovered prompt is marked for forced name reuse so the relaunch keeps the original
agent's name instead of claiming `<name>1`. The marker is a `!` on the `%id` directive,
and its exact shape follows the prompt:

| Original prompt           | Rewritten as                        |
| ------------------------- | ----------------------------------- |
| `%id:foo`                 | `%id:!foo`                          |
| `%id(foo)`                | `%id(!foo)`                         |
| a clan member's prompt    | `%id(!<suffix>, clan=<clan>)`       |
| a session member's prompt | `%id(!<suffix>, session=<session>)` |
| no `%id` directive        | unchanged — a fresh name is used    |

Note that the clan and session forms carry the member's trailing `<suffix>` — the part
after the `<clan>.` prefix, or the session role segment — not the full agent name; the
membership keyword supplies the rest. An existing `bead=` value is carried across, and a
standalone `clan:` declaration is dropped in favor of the `clan=` keyword. The last row
is not a failure: a prompt that never named its agent has nothing to reuse, so it simply
relaunches under a newly allocated name. A serial session member is the one case where a
prompt with no `%id` is still rewritten, because its `session=` attachment comes from
the row rather than the prompt; session roots are not treated that way. Forced reuse of
a session member replaces only that member and its own descendants; the session root and
the sibling members are left untouched, so the `session=` attachment still finds its
parent.

sase's TUI is the surface that confirms that reuse, and it carries the authorization
through to the launch, so no second confirmation is asked for. Forced reuse cannot be
combined with alt/fan-out directives in one segment; such a prompt is rejected with an
explanatory error and preserved in prompt history, so you can reopen it from `,.` and
split the launch.

`,X` targets the most recently launched agent this sase's TUI session accepted, instead
of the focused or marked row(s) — marks are ignored entirely, even when agents are
marked. Repeating `,X` walks back through this session's launch history one accepted
launch at a time; a launch already killed or dismissed by hand is skipped. A launch
leaves that history only once its kill or dismissal actually starts, so canceling the
confirmation, losing the row mid-action, or failing to resolve the prompt leaves the
same launch as the next `,X` target instead of walking back to an older one — and
pressing `,X` again while that confirmation is still up neither opens a second one nor
advances. Once its target row exists, `,X` reuses the exact `,x` machinery above (the
same confirmation rule and forced-name-reuse rewrite), so a single-agent launch opens
one editable pane and a bulk-Patch or multi-prompt `---` launch opens one pane per
launched agent in launch order. Nothing is recorded across sase's TUI restarts: the
targetable history is this session's in-memory launch stack, not disk state.

`,X` is meant to undo a premature `<enter>` press, including the moment right after
submit before the launched agent's row exists yet. In that in-flight window sase's TUI
restores the submitted prompt immediately (no confirmation — the `,X` press is the
confirmation) and kills the launched agent(s) once the launch proc finishes. A
replacement submit from the restored prompt waits until that kill settles so the
original name is not resurrected underneath it. Repeat `,X` while the kill is still
pending re-focuses the restored prompt and does not walk back to an earlier launch.
Restarting sase's TUI mid-flight drops the pending kill: the launch completes, the row
appears, and ordinary `,x` applies.

Submitting a prompt returns immediately: `<enter>` removes the prompt bar on the next
repaint, even when the launch still has to wait, and the launch carries on as a pending
launch. The launch shows as a `launch <name>` row in the proc indicator and the Procs
tab from the moment you press `<enter>`; its message names what it is waiting for (for
example "waiting for kill/dismiss cleanup" while a `,x` or `,X` cleanup settles), and
the durable `sase run` row takes over when it is submitted. A launch that has not been
submitted yet has nothing to kill, so `,X` on it simply cancels the launch and reopens
its prompt in a bar (still marked for forced name reuse, so a re-submit stays behind the
same cleanup). A cancelled bulk-Patch launch restores its shared prompt; the Patch marks
are not restored. Quitting sase's TUI while a launch is still pending stashes its prompt
so `@` can restore it.

Press `,r` on a `DONE` or `FAILED` agent to preview commits attributed to that agent
before creating git revert commits. For plan/follow-up sessions, sase's TUI reverts the
session scope when the row carries session metadata; otherwise it reverts the focused
agent name. The preview includes the primary workspace plus recorded `linked_repos`
metadata entries that still point at an existing workspace directory; never-opened
linked workspaces are not part of this action. Each repository is checked before
execution, and a dirty or non-git linked repo is reported and skipped while clean
repositories can still be reverted. Successful execution creates one revert commit per
repository, pushes when a remote tracking branch is available, and writes
`revert_result.json` beside the agent artifacts.

When agents are marked, `,r` previews the combined commit set for the marked `DONE` /
`FAILED` rows. Marked agents must come from the same primary workspace. The bulk path
still groups work by repository, deduplicates overlapping session matches, skips marked
rows with no matching commits, and reports partial linked-repo failures instead of
hiding them.

## Bang Mode (`!` prefix) {#bang-mode-prefix-1}

## Copy Mode (`%` prefix) {#copy-mode-prefix-1}

Press `%` to open the **Copy as…** palette for the focused agent. It supports mouse
selection, arrows or `j`/`k` plus `Enter`, and every configured direct accelerator
below. `q`/`Esc` cancels unless that key is itself configured for a copy target, in
which case the target wins.

## Related

- [TUI hub](index.md) — all Agents tab reference pages.
- [Agents tab](agents-tab.md) — tabs, keys, lists, and actions.
