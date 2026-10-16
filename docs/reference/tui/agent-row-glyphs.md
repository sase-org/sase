---
title: Agent row glyphs
description: Glyphs, markers, and badges on Agents tab rows.
---

# Agent row glyphs

This page names the glyphs, markers, and badges rendered on Agents tab rows.

## Agent Row Glyphs {#agent-row-glyphs-1}

To keep rows compact, agent statuses and types are rendered as one- or two-character
badges instead of verbose text:

| Glyph | Meaning                                                                                                                                                                                                                                                                                                           |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `▶`   | RUNNING                                                                                                                                                                                                                                                                                                           |
| `✓`   | DONE                                                                                                                                                                                                                                                                                                              |
| `✓P`  | PLAN DONE                                                                                                                                                                                                                                                                                                         |
| `▶P`  | PLAN APPROVED                                                                                                                                                                                                                                                                                                     |
| `★E`  | EPIC CREATED                                                                                                                                                                                                                                                                                                      |
| `✎`   | PLAN                                                                                                                                                                                                                                                                                                              |
| `✗`   | FAILED                                                                                                                                                                                                                                                                                                            |
| `…`   | QUEUED                                                                                                                                                                                                                                                                                                            |
| `⏳`  | WAITING                                                                                                                                                                                                                                                                                                           |
| `?`   | QUESTION                                                                                                                                                                                                                                                                                                          |
| `↻`   | RETRYING (followed by attempt count, e.g. `↻2`)                                                                                                                                                                                                                                                                   |
| `⊛`   | Finalizer chip: the most severe finalizer state since the newest successful run (failed > refused > interrupted > deferred > running), with `k of n runs` when several runs are in play; the row word reads `FINALIZING` while finalizers run (see [Finalizers on the Agents tab](agent-statuses.md#finalizers-on-the-agents-tab)) |
| `≡`   | Workflow row (top-level)                                                                                                                                                                                                                                                                                          |
| `❑`   | Patch / Patch row (top-level)                                                                                                                                                                                                                                                                                     |
| `⚡`  | Autonomous (`%auto`) agent                                                                                                                                                                                                                                                                                        |
| `◌`   | Hidden agent (visible only when `.` toggles them in)                                                                                                                                                                                                                                                              |
| `⚙`   | Monitor turn (row label)                                                                                                                                                                                                                                                                                          |
| `⚙N`  | N running monitors in a session/clan subtree, or in a tribe panel title for its whole tribe (amber)                                                                                                                                                                                                               |
| `⚙N`  | N finished monitors in a session/clan subtree, or in a tribe panel title for its whole tribe (grey)                                                                                                                                                                                                               |
| `⋔`   | Gate turn; its gate accent while pending/running, grey when settled, red on failure                                                                                                                                                                                                                               |
| `⋔N`  | N gates in a session/clan subtree or tribe panel title, colored by lifecycle bucket                                                                                                                                                                                                                               |
| `▣`   | Stand-alone `%proc` named proc (row label)                                                                                                                                                                                                                                                                        |
| `▣N`  | N stand-alone named procs in a panel title's separate proc chip                                                                                                                                                                                                                                                   |

A monitor turn (a session member whose work is a supervised command, started with
`sase monitor start`) renders an amber `⚙` glyph and omits a left-side title — identity
is the right-hand `%id` (`<session>--mon`), not the configured monitor label. A live
elapsed suffix or exit-code/timeout badge replaces the ordinary agent statuses. The
status token — the start label while running, the stop label once settled — is colored
by a deterministic accent derived from that pair, so every `TESTING`/`TESTED` monitor is
the same hue; failed, timed-out, and lost monitors stay red. Two extra badges mark a
stalled monitor handoff: a red `⚠` replaces the exit-code badge when a terminal
monitor's supervisor never reported a real exit code, and an amber `⚑` follows the row
when its `--next` follow-up was dropped or launched degraded — a monitor can finish
cleanly and still strand its follow-up. See [Monitors](../automation/monitors.md).

Gate turns use `⋔` and their authored pending/settled labels, such as `GATE`/`GATED`,
`QUESTION`/`ANSWERED`, or plan-tier statuses. A pending gate has no LLM process and does
not occupy a runner slot, but it may retain the session's workspace claim. Its state is
one of pending, settling, answered, completed, failed, timeout, stopped, or lost.
Session and tribe chips count pending/running, settled, and failed gates separately by
color. After a decision, the gate member owns the displayed outcome: handoff outcomes
`PLAN APPROVED`, `TALE APPROVED`, `EPIC APPROVED`, and `ANSWERED` use the Running bucket
even though the gate itself has settled, so the row represents the successor handoff.
Rejection and cancellation use Done; timeout, failure, and lost gates use Failed.

A monitor row nests under the agent that started it, not under a synthetic aggregate —
one gear-glyph row at the starter's depth plus one. It is revealed by its **agent
session's** fold rather than its starter's own: a collapsed session shows an amber `⚙N`
badge for its running monitors and a grey `⚙N` badge for its finished ones — the two
counts partition the subtree's monitors, with a monitor that has not reported a terminal
state counting as running — and counts every monitor in its collapsed ` ×N`, but renders
no monitor row, even when the session root itself is the starter. The tribe panel title
aggregates both lanes across the whole tribe, so a fully collapsed panel still reports
both what is still running and how much has already completed inside it. A single `l` on
the session container row reveals every member and monitor in that session in one step;
monitors are not deferred to a further "fully expanded" press the way hidden workflow
steps are. Selecting a monitor row and pressing `l` or `H` acts on that governing
session fold — `H` collapses the session and reanchors the cursor there — while `h`
still walks up to the monitor's starter.

A monitor has no LLM process to kill, so `x` on a selected **running** monitor row is
routed off the ordinary kill/dismiss path: it opens a `Stop Monitor` confirmation
(defaulting to **Keep running**) and, once confirmed, terminates the supervised command
through the same code path as `sase monitor stop`. As with the CLI, stopping never
launches the recorded `--next` follow-up agent. The stop itself runs as a tracked proc,
so a slow teardown does not block the TUI. `x` on a monitor row that has already settled
falls through to the normal dismiss behavior, and bulk scopes still win over the single
row: marks, a focused panel, and a focused group are all handled before sase's TUI looks
at whether the selected row is a monitor.

Agents launched by `sase bead work` also show a gold `◆ <bead_id>` badge between the
status glyph and the tribe/name. That trailing gold `◆` linked-bead badge is a
fixed-style identity marker, not a wait-count token; waited-on beads in a `WAITING`
summary use status-colored `○` / `◐` / `●` tokens instead. A phase agent named
`<epic_id>.<N>` displays that phase bead ID; the final `<epic_id>.land` agent displays
the parent epic bead ID; a standalone task worker named `<task_id>` displays its task
bead ID. Legacy plain `<epic_id>` land agents keep the same badge. Legacy dismissed
names keep the badge after their historical date prefix is stripped. Modern phase and
task rows use their explicit launch metadata immediately; legacy bead-shaped names
retain the deferred bead-store confirmation fallback.

Each agent row also carries a per-provider emoji badge before the display name so the
LLM provider behind a row is readable at a glance without scanning the right-hand model
suffix:

| Badge | Provider          |
| ----- | ----------------- |
| 🎭    | Claude            |
| 🪐    | Antigravity (agy) |
| 🤖    | Codex             |
| 🐼    | Qwen              |
| 🐙    | OpenCode          |
| 🦋    | Muse Code (Meta)  |
| 🚀    | Grok Build (xAI)  |

The same provider palette also colors the `<PROVIDER>(<model>)` suffix on the right edge
of the row — the provider name, the parentheses, and the model name each render in a
distinct shade from that provider's palette so multi-model fan-outs are easy to scan.
Providers without a dedicated palette (anything outside the table above) fall back to a
neutral purple palette and render no emoji badge.

An agent that was materialized on this machine by the retired agents-sync import leg
carries an **owner badge** — ` [<label>]` after its identity name — recording where it
came from. A foreign machine belonging to you renders as just the machine name; another
user's run renders as `username@machine`. The badge appears wherever an imported
identity is named: agent rows, the Archive Record Lifecycle card, and neighbor pickers.
Imported sequential sessions are also folded under one synthetic session-container row
so members imported without their root still group as one session instead of scattering
across the panel. Both are presentation over leftover local state; nothing imports new
rows any more, and `sase agent names purge-local-state` removes the state that produces
them (see [Agent Hood Synchronization](../upgrading/agents-sidecar.md#legacy-v1-limitations)).

Workflow child rows for `python` and `bash` steps render a leading `❯` glyph plus the
step name, styled with the matching step-type accent — bash amber, python green —
because that name is those rows' identity. The glyph's presence is a stronger signal
than the step-type color alone for colorblind users and for rapid scanning; color still
carries the bash/python distinction. Sase turns (session-member agent turns, monitor
named procs, and workflow `agent` steps) omit a left-side title; their identity is the
right-hand `%id` / session-member name. Parallel rows fan out into structural children,
and `prompt_part` rows are invisible by default.

The right-hand edge of each row carries a runtime suffix
(`<start-timestamp> · <elapsed>`) right-aligned within the panel. Active rows that have
actually started include a `🏃‍♂️` marker before the ticking elapsed duration; unread
completed rows use a `✅` marker in the same suffix slot, or `❌` when the agent
finished in a `FAILED` state; and user-paused rows (`PLAN`, `QUESTION`, `WAITING INPUT`)
use a `✋` marker while waiting for a human response. Pre-run `WAITING` and `QUEUED`
rows with no `BEGIN` time hide the suffix so admission waits do not look like live
runtime. On an active sequential-session container, the live suffix is
`🏃‍♂️ <current-turn-runtime> / <session-total-runtime>`: the left value is the concrete
agent or monitor turn currently executing, and the right value is the aggregate session
interval. Gate-turn windows are excluded from that session total — they measure the
human decision, not agent runtime — and the same exclusion applies to clan totals. On an
active clan container the live suffix is
`<lowest-running-lane-runtime> / <clan-total-runtime>` (same marker), where the left
value is the smallest current runtime among the clan's running lanes (a sequential
session lane contributes its total runtime, the same value its own row shows on the
right of its suffix) and the right value is the aggregate clan interval. For finished
agents, the start-timestamp half is rendered as a humanized `(date_prefix, time)` pair
sized to fit the existing 15-cell slot:

- **Same day**: `HH:MM:SS`
- **Prior day, same year**: `Mon DD HH:MM` (drops seconds — they're noise once a row
  finished hours ago)
- **Different year**: `Mon DD 'YY` (date only)

The elapsed duration starts at `BEGIN` when a row recorded wait-before-run metadata,
otherwise at the row start time. For slot-participating user agents, `BEGIN` is runner
admission and includes primary and linked-workspace preparation in the active runtime.
Completed `DONE` / `PLAN DONE` / `TALE DONE` workflow rows use the terminal agent stop
time when one exists; plan-step rows that finish without a subprocess stop time anchor
to the latest recorded plan submission time so completed planning rows do not keep
ticking. `PLAN APPROVED` rows with a running follow-up show active elapsed time for the
planner segment plus the coder segment, excluding the idle approval gap between plan
submission and code launch. The date prefix uses a softer `dim #8787AF` while the time
half keeps the standard `#8787AF`, giving the column internal hierarchy without
inflating the palette. Statuses not in the table fall back to `(STATUS)` text for
forwards compatibility.

A stand-alone `%proc` unit is backed only by the proc store — it is never an agent,
never nested under an agent session, and never counted in agent runner, unread, clan, or
session totals. It renders as its own top-level `▣` row with a Bash/Python language
badge, current phase/status, elapsed time, and project, and a panel title reports it in
a separate `▣<count>` chip alongside the ordinary agent metrics. Selecting one opens a
`NAMED PROC` detail (status/phase timeline, project/ workspace/cwd, language, code
digest and safe preview, waits, condition result, timeouts, and a bounded live-log
tail). `x` on a running stand-alone named proc asks for confirmation and then kills it
and removes its row in one step — the durable cleanup proc stops it through the native
proc service — and `x` dismisses a finished one with no confirmation. Dismissal only
clears the Agents-tab row — the proc stays visible in the [Procs pane](procs-tab.md#durable-procs)
and in `sase proc show`, and a dismissed Agents-tab row does not come back. See
[Typed launch units](../macros/directive-syntax.md#typed-launch-units) for the directives that create it.

## Related

- [TUI hub](index.md) — all Agents tab reference pages.
- [Agents tab grouping](agents-tab-grouping.md) — group banners and modes.
