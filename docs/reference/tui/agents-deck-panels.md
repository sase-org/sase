---
title: Agents tab LLM calls and tool runs
description: LLM call and tool run panels on the Agents tab.
---

# Agents tab LLM calls and tool runs

This page describes the LLM calls and tool runs panels on the Agents tab.

## Agents Tab LLM Calls Panel

The Tools deck's `LLM Calls` card shows a chronological timeline of the LLM tool calls
the selected agent has made — file reads, edits, bash invocations, web fetches,
sub-agent launches, and so on.

Entries are read from the `tool_calls.jsonl` artifact in the agent's run directory. Each
call renders as one timeline row:

- A status label colored by outcome — `ok` (success), `fail` (error), `stop`
  (interrupted), `agent` (sub-agent launch), or `wait` (the post-call record has not
  arrived yet).
- The tool name, optionally followed by a compact target (such as the file path the tool
  acted on) and the call's duration.
- A short preview of the call result on the next line, when the collector captured one.
  Command-output previews keep a marked suffix with at least the final 50 logical lines;
  the character budget is soft so unusually wide trailing lines remain complete. Other
  preview types remain head-oriented.

The panel header shows the total call count, the failure count, the interrupted count,
and a timestamp for the most recent reload. While a background reload is in flight
(because the artifact changed on disk), `(refreshing...)` appears next to that
timestamp. The body shows `No provider tool-call artifact available` when the file does
not yet exist for this agent and `No tool calls recorded` when the file exists but
contains zero records.

The timeline has three detail levels: compact, expanded, and full. While the focused
deck panel shows the Tools deck, `l` / `h` step the level up / down and `L` / `H` jump
to full / compact, taking priority over their usual fold actions.

For retry chains and planner-to-coder follow-up sessions, the panel aggregates
`tool_calls.jsonl` from related artifact directories so the selected logical agent shows
one ordered tool timeline. Discovery uses the persistent artifact index when it is
available; if the index is missing or stale, sase's TUI falls back to direct lineage
pointers plus a bounded scan of nearby sibling artifacts.

Records are produced by writers that share one normalized on-disk format. Claude uses
the SASE tool-call hook collector as the preferred source and keeps its stream-derived
parser as a fallback when hooks are unavailable. Codex writes equivalent rows from its
`codex exec --json` stream with `runtime: "codex"` and `source: "stream"`; current Codex
start/completion events can show pending rows, result previews, failures, interruptions,
and durations, while older completed-only `function_call` rows remain readable with more
limited detail. Qwen writes stream-derived rows from its `--output-format stream-json`
output with `runtime: "qwen"` and `source: "stream"`; start/completion (and Qwen's
`tool_use` / `tool_result`) pairs collapse into single rows the same way Codex pairs do.
Muse Code writes stream-derived rows from its `muse exec --json` JSONL stream with
`runtime: "muse"` and `source: "stream"`; proposed/scheduled and `tool.result` pairs
collapse into single rows like the others. Muse's stream never carries tool _arguments_,
so a Muse row's input target comes from `edit_facts.path` for edits, the parsed command
for `bash`, and otherwise a bounded preview of the result text — SASE does not invent
arguments Muse did not emit. Antigravity (`agy`) runs in plain-stdout mode; SASE never
scrapes display prose, but supported Antigravity versions may contribute guarded
`source: "trajectory"` rows from the local trajectory DB. When that extractor is
unavailable, the panel simply shows nothing for `agy` runs. Grok Build writes
stream-derived rows from its `streaming-messages-json` output with `runtime: "grok"` and
`source: "stream"`; Grok's native tool names (`run_terminal_command`, `read_file`,
`search_replace`, and so on) are mapped onto the same canonical display names Claude
rows use, and its JSON-encoded `tool_result` envelopes are decoded for exit codes and
file paths rather than shown raw. See
[LLM Providers — Claude tool calls](../providers/claude.md#claude-tool-calls),
[LLM Providers — Codex tool-call capture](../providers/codex.md#codex-tool-call-capture),
[LLM Providers — Qwen tool-call capture](../providers/qwen.md#qwen-tool-call-capture),
[LLM Providers — Muse tool-call capture](../providers/muse.md#muse-tool-call-capture),
[LLM Providers — Antigravity (`agy`) Integration](../providers/agy.md#antigravity-agy-integration),
and [LLM Providers — Grok Tool-Call Capture](../providers/grok.md#grok-tool-call-capture) for
provider integration details.

## Agents Tab Tool Runs

The Agents tab surfaces the machine-local ToolRun ledger (see
[Named Tools and ToolRuns](../../tool.md)) at three zoom levels: a live-only `⚒` chip on the
owning row, a header chip plus `Tool runs` field on the selection, and the Tools deck's
`⚒ Runs` card for diagnosis. Project-wide runs live in the Admin Center
[Tools tab](machines-and-tools.md#tools-tab). `⚒` (U+2692) means ToolRun everywhere — row, header, card,
pane, notification icon, and Procs cell. The old chop/Services link-trail icon moved to
`⏲` so the two are never confused. Say "tool run" or "ToolRun": never "tool call" for a
ToolRun.

The view is read-only. The TUI never reconciles, settles, or writes to the ledger on any
UI path: stopping a run goes through the explicit stop flow below, and everything else
only reads.

### State vocabulary

Every state shows glyph + word + color together, so meaning never depends on color
alone:

| State        | Glyph | Words (examples)                                             | Color                                      |
| ------------ | ----- | ------------------------------------------------------------ | ------------------------------------------ |
| running      | `⚒`   | `check 7/11`, `check 2m`, `check starting`, `check stopping` | bold Tools accent `#87D7FF`                |
| silent       | `⚒⚠`  | `check silent 4m`                                            | bold `#FF5F5F`                             |
| pass         | `✓`   | `pass`                                                       | `#5FD75F`                                  |
| new failures | `✗`   | `3 NEW · 1 KNOWN`                                            | `#FF5F5F`                                  |
| known only   | `≈`   | `known only · 2 KNOWN`                                       | `#87AF87` (calm: the known red, not yours) |
| undetermined | `?`   | `2 UNKNOWN`, or `untriaged`                                  | `#FFAF5F`                                  |
| killed       | `⊘`   | `killed at 9m00s · signal`, `timed out at 30m00s`            | `#D75FFF`                                  |
| stopped      | `⊘`   | `stopped at 1m02s`                                           | dim                                        |
| lost         | `⊘`   | `lost · wrapper_lost`                                        | dim `#FF5F5F`                              |

A live run is one in state `created` or `running`. A live run is **silent** when nothing
was heard from it for 60 seconds (six missed samples): the TUI says `silent` in red and
never claims an outcome. Severity picks one chip among several tools —
`new_failures > undetermined > killed > lost > stopped > known_only > pass` — with live
always outranking settled and silent outranking live. Ages format as `<1m`, `Nm`, `Nh`,
`Nd`.

### At a glance: the row chip

A row carries a `⚒` chip only while one of its runs is live; settled history never marks
the row. The chip shows the tool label plus progress against the reference run
(`check 7/11`), elapsed minutes (`check 2m`), `starting` for a created run, or
`stopping` once a stop is requested. All times are minute-resolution snapshots — a
relative time that doesn't tick would be a lie, and rows don't repaint on a tick.

Attribution is by node kind, never by name guessing. A monitor-owned run chips the
monitor row, not its starter; a named-proc run chips the proc row. History still shows
both relationships (a handed-off run is labeled `→ monitor <name>` or `→ proc <id>`). A
session container inherits its members' most severe live chip. Rows on remote machines
get no chip: the ledger is machine-local, so absence must never read as "no runs".

### In context: the header chip and `Tool runs` field

The selected node's header chip answers "did its latest check add NEW failures?" at a
glance: a live run wins over settled history (silent first), otherwise the most severe
settled run per label wins, with `+N` when other tool labels exist. Live elapsed turns
amber past the run's typical duration; settled times are absolute (`16:21`), never
relative. The expanded `Tool runs` field lists each run with its verdict line, and `%r`
(copy mode) copies the focused run's id.

### To diagnose: the `⚒ Runs` card

One block per run, newest first; `(` / `)` step between blocks. Selecting a node lands
on the newest block. A reader sitting on the newest block follows new arrivals; a reader
who moved back holds position and sees an arrival dot. A nested run renders as a `↳`
line inside its parent block, never as its own block.

Each block shows the outcome and context lines (tool label, verdict, argv, owner), a
stage waterfall, triage items with cross-run and cross-agent witness counts, child runs,
and a bounded log tail. Three detail levels come from `h` / `l` (full / compact via `H`
/ `L`), routed by the active card — while the Runs card is active those keys drive run
detail, not folds. When the detail or the log is pruned the block says so honestly
(`detail pruned · summary retained`) instead of showing an empty success.

A live block progresses in place: elapsed repaints once a second, pending stages come
from the reference run, and the block settles in place when the run does — no full
refetch unless the glance drifts. `v` hint mode gains one `⚒ run log <8hex>` target per
visible block, opening the retained log in the pager. A node with no runs and no calls
shows `No tool runs or LLM calls for this node`; on a remote row it says
`ToolRun history lives on <machine>` instead.

### Links from LLM Calls, slow tools, and Context cards

An LLM Calls row whose command ran `sase tool run` (or a wrapping `sase monitor start`)
gains a verdict suffix that clicks through to the run's block. A `sase tool run` row in
the Main deck slow-tool list gains a live-stage or verdict suffix. Monitor and
named-proc Context cards gain a clickable `Tool run` row. The run itself is never copied
into those surfaces — they link to it. In `v` hint mode each linked run also offers a
`⚒ run <8hex>` jump target alongside the `⚒ run log` targets.

### Stopping a run and running a tool

The command palette offers `Stop live tool run` and `Run project tool…` whenever a local
live run (for stop) or a local node (for run) is in play.

Stopping asks for confirmation in a DANGER dialog with Cancel focused, and the copy
names the consequence for the owner: an inline agent run's `sase tool run` exits 143
(its agent keeps running and sees a failed check), a monitor-owned run's monitor stops
and its follow-up agent never launches, and a hand-off proc is killed with the run
settling as stopped. A nested run resolves to its outermost stoppable ancestor first.
The stop itself runs as a durable proc (`sase tool stop RUN -j` with a typed result), so
it appears in the Procs tab and survives quit.

`Run project tool…` confirms the argv and the root, then hands `sase tool run -H <tool>`
off at the current project's primary checkout root through a session worker. When that
run settles, an `OpenToolRun` notification arrives; selecting it jumps to the run's
Agents-tab node with its ⚒ Runs card active and the run's block selected (or opens Admin
Center → Tools focused on the run).

## Related

- [TUI hub](index.md) — all Agents tab reference pages.
- [Agents tab main deck](agents-main-deck.md) — main deck, zoom, and node rail.
