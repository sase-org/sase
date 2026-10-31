---
title: Agent workflows
description: Plan workflows, approvals, holds, and retries on the Agents tab.
---

# Agent workflows

This page describes agent workflows on the Agents tab: auto-naming, plan workflows,
launch approval, holds, linked chats, and retry display.

## Agent Auto-Naming

Prompts with no `%id` directive, or with a bare `%id`, use the plain auto-name template
`@`. SASE reserves the lowest available token from the sequence `0`, `1`, ..., `9`, `a`,
..., `z`, `00`, `01`, ...; with no reserved names, plain auto-naming yields concrete
names such as `0`, then `1`.

An explicit `%id` value containing exactly one marker is an agent-name template. The
`@` marker is bare, so the first allocation for `%id:@.cld` becomes `0.cld`,
`%id:build-@` becomes `build-0`, and `%id:research.@.final` becomes `research.0.final`.
Keyed markers such as `%id:research.{@1}.final` are preferred for macro swarms: SASE
resolves every matching key in `%id`, `%clan`, `clan=`, waits, fork/resume references,
and prose before any spawned member can start. Bare `@` still works, but template
references use latest-wins lookup and can be unsafe when a swarm member starts after a
newer overlapping launch. See [Macro template directives](../macros/directive-syntax.md#directives) for
`{@<id>}` and `{@<id>!}` qualification rules.

Names are permanent IDs: a name used by any existing agent state remains reserved until
that agent is explicitly wiped or deleted. This enables the fork-by-name workflow: press
`F` on a running named agent to queue a follow-up that waits for it to finish and then
loads its conversation history.

### Provider/Model Suffixes

When the same base name is shared by multiple co-launched agents (e.g. multi-model
fan-out via the `%model:` directive), the rendered display name carries a short
`.<provider>` or `.<provider>(<model>)` suffix so each row is distinguishable. Provider
suffixes are supplied by the LLM provider plugins via the `llm_provider_short_name` hook
(built-in defaults: `cld` for Claude, `cdx` for Codex, `agy` for Antigravity).
Additional provider plugins can contribute their own short names. Model-name shorthands
come from the `llm_model_short_aliases` hook (e.g. `fable` for `claude-fable-5`,
`gpt61sol` for `gpt-6.1-sol`; see [Model Short Aliases](../providers/models.md#model-short-aliases))
and are resolved against the configured model so the suffix stays compact regardless of
how the model was spelled in the prompt or config. Single-runtime spawns omit the
suffix.

An explicit `%id:<name>` launch fails before spawning if `<name>` is already reserved.
The prompt is saved as a cancelled history entry and the error suggests the lowest free
numeric suffix, such as `<name>1`. To deliberately reuse a reserved name from the TUI,
launch with `%id:!<name>`; the `!` form confirms that SASE should wipe the previous
owner and then claim the name for the new agent. Reviving and dismissing agents preserve
their stored names.

The durable registry lives at `~/.sase/agent_name_registry.json` and is rebuilt from
visible artifacts plus dismissed bundles when missing or stale. Use
`sase agent names migrate-auto` to move older generated names into the permanent
namespace; see [TUI migration notes](../upgrading/tui.md#auto-name-migration).

### Per-Step Naming for Multi-Agent Workflows

Sequential plan-session workflows have a stable session container plus member suffixes.
When the first follow-up attaches, the original agent is renamed and the bare session
name becomes a pure container. Generated follow-up rows and phase metadata use canonical
double-dash suffixes. For example, if the initial agent was named `a`:

1. The first attachment creates session container `a` and gives the original its
   persisted role suffix (`a--plan` for a plan proposer or `a--0` for a generic agent).
2. The planner phase uses a canonical `--plan` role suffix.
3. Feedback and question-continuation rounds become `a--2`, `a--3`, etc.
4. Terminal follow-ups use the phase suffix, such as `a--code`, `a--epic`, or
   `a--commit`.

The base name (`a`) is reserved for the session as a whole, so `%wait:a` or `@a`
references resolve through the session container. In sase's TUI, the aggregate session
row displays that bare container name, while expanded concrete member rows keep their
exact suffixed names (`a--0`, `a--plan`, `a--code`, and so on). New plan-session
metadata stores double-dash `role_suffix` values (`--plan`, `--2`, `--code`, ...).
sase's TUI still canonicalizes older dotted suffixes (`.plan`, `.2`, `.code`, etc.) and
single-dash suffixes (`-plan`, `-2`, `-code`, etc.) when reading older artifacts. See
[TUI migration notes](../upgrading/tui.md#session-member-suffixes).

## Plan Workflows

When an agent submits a plan via `/sase_plan` (or `sase plan propose`, including the
`%auto:epic` path), it enters a planning phase before executing:

- **TALE** / **EPIC** — The agent has submitted an authored tale or epic and is waiting
  for user review. Tales are pink/magenta; epics are orchid. **PLAN** is the
  compatibility fallback when the authored tier cannot be resolved.
- **PLAN APPROVED** — The plan has been approved and the follow-up agent has been
  spawned. Shown in cyan/turquoise.
- **PLAN REJECTED** — The plan was rejected. A no-feedback rejection from sase's TUI or
  `sase plan reject` writes the rejection response first, then attempts to dismiss the
  notification, user-kill the matching planner, and persist dismissed-agent state so the
  row is hidden on refresh. If the matching row is already gone, the plan is still
  rejected. Rejected archived plans can still appear in history-oriented views, and
  redundant completion notifications are suppressed.

Plan files generated by the agent are displayed in the file panel alongside other agent
artifacts. Plan approval notifications include the LLM provider and model name, so users
can see which model proposed the plan (visible in both the TUI notification modal and
Telegram delivery).

sase's TUI arrival toast names the authored tier — **Tale ready** or **Epic ready** —
instead of using a generic Plan label. An epic toast adds the validated phase count,
dependency wave count when available, and the non-zero per-size counts (`XS`, `S`, `M`,
`L`, and `XL`). Those values are captured when the approval gate is created, so a
notification that is snoozed and later resurfaces keeps its original summary even if the
bundled plan was edited meanwhile. Batched warning toasts likewise count tales and epics
separately.

When `sase plan propose` writes the plan, it also touches `~/.sase/.ace_refresh_pulse`
to wake any running TUI immediately — the tier-aware `TALE` or `EPIC` status (or
fallback `PLAN`) appears without waiting for the next auto-refresh tick. The pulse file
is consumed by the inotify artifact watcher (see [Auto-Refresh](global-controls.md#auto-refresh)) and is
harmless if no TUI is open.

Root plan workflows also surface their tier-aware pending status when a re-proposed plan
is still awaiting review. Plan and feedback timestamps from feedback-round children
(`--2`, `--3`, ...; also `-2`, `.2`, etc.) propagate onto the root entry, and whenever
the root's latest plan timestamp is newer than its latest feedback timestamp the
override engine restores `TALE`, `EPIC`, or fallback `PLAN` over a `RUNNING` or `DONE`
label. This applies only to root plan workflows that have not yet spawned a terminal
follow-up (`--code`, `--epic`, ...); once a terminal follow-up is launched, the parent
moves on to `PLAN APPROVED` (or the matching follow-up status) instead.

The Plan Review modal title shows a provider-themed `PROVIDER(model)` badge between the
"Plan Review" label and the plan filename — orange for Claude, lime for Codex,
Antigravity indigo (`#6E5DE7`) for agy, neutral muted for other providers. The badge is
omitted when provider/model metadata is absent.

Whole-document Markdown previews in plan, launch, and custom-gate review modals
highlight leading YAML frontmatter as YAML and the remaining body as Markdown.
Highlighting does not alter validation or the reviewed file contents.

Plan Decisions (see [Plan Decisions](../work-units/plan-format.md#plan-decisions)) add typed choices and
toggles to plan frontmatter. The modal renders them as cards in a Decisions section
above the verdict: the current card shows its full question, options, and rationale with
a `▌` focus bar, while the other cards collapse to a header plus a one-line ask preview.
The header reads `Decisions · N`, gains `· M changed` when values move off their
defaults, and names memory decisions with `· 🧠 K`. Each card's answer chip shows its
value with `★` at the default and gold `●` once changed (`☑`/`☐` for toggles); the
current card wraps the chip in `‹ … ›` as the "h/l changes this" hint. Change a value
with `Space`, `h`/`l`, or `r`, move between cards with `j`/`k` or by clicking a card,
and click an option line in the current choice card to select it. Press `z` for a
full-width sheet with every card expanded; Esc leaves the sheet, and a second Esc
cancels. The primary action approves exactly the values on display. `decision_<id>`
fields are treated as already collected, so they do not appear as extra inputs either.
Changing decision definitions through the gate's plan editor is refused. Override a
default outside the modal with `sase gate answer` and `--set decision_<id>=...`.

For tale plans, the modal's primary **Approve** decision includes two independently
selectable add-ons: **Commit plan file to the plans sidecar** and **Run coder
follow-up**. Both are selected by default. Press `enter` to approve with the current
checkbox selection, move to another decision (reject or feedback) with `j` / `k` and
submit it with `Ctrl+S`, or press `c` for [Custom Approval](#custom-approval).

sase's TUI submits the decision as a tracked `sase gate answer` proc labeled
`Plan response: <choice>`, so a slow or failed submission shows up in the Procs tab and
an error toast rather than blocking the TUI; the inbox and Agents rows refresh once the
answer is recorded.

For the Tale and Commit choices, SASE publishes the reviewed plan to the archive before
the approval response is made terminal. The response carries a canonical `plan:`
reference, so a coder launched from a different numbered workspace resolves the same
archived plan without depending on the approver's checkout path. If publication fails,
SASE does not write the terminal response. The PlanApproval notification remains
actionable and can be retried after the archive problem is fixed.

The same pending approvals are available from the CLI. Run `sase plan` to see pending
proposals, recent approvals, and inferred rejected archived plans; run
`sase plan approve <name> --kind approve|commit|epic|tale` or `sase plan reject <name>`
to write the same response protocol used by the TUI modal. Use the plan name from a
Proposed row (the `id_prefix` still works); if the selector is omitted, the CLI acts
only when exactly one proposal is pending. CLI approval defaults to `tale`; an
epic-authored plan requires `--kind epic` or `--kind tale`. In the Plan Review modal,
`enter` follows the authored tier; use [Custom Approval](#custom-approval) to pick a
different outcome. `approve` starts the coder without committing an SDD plan, `tale`
commits the plan as an SDD tale and starts the coder, `epic` commits the matching SDD
tier and launches the bead follow-up, and `commit` records the approved plan in SDD
without launching a coder. `-m/--model` picks the follow-up agent's model, while
`-p/--prompt` adds extra coder instructions for the `approve` and `tale` paths. Tale and
epic choices validate the plan against the target schema before consuming the approval;
failures surface an error and keep the notification actionable. CLI rejection also
attempts the durable planner cleanup used by no-feedback TUI rejection.

### Auto-Approve Toggle

On an active agent, `A` changes the selected agent's autonomy record from its next gate.
If any auto-approval is on (including a launch-time `%auto:tale` / `%auto:epic`), it
switches the record to manual, and the next plan, epic, or question gate parks for
review. If auto-approval is off, turning it back on restores the last non-manual profile
(else `standard`): a `%auto:tale` agent comes back as tale, not bare. Later successors
inherit the toggled record.

The enabled profile determines which plans auto-resolve. `standard` covers both tiers;
`tale` covers tale plans and `epic` covers epic plans. The other tier parks for human
review. Covered plans use their authored tier for the archive and follow-up path. Use
`sase autonomy explain NAME` to inspect the agent's live policy and predicted decisions.

The row shows `⚡` while enabled, and the footer label switches between `auto-approve`
and `unapprove`.

Questions always wait for you, whichever profile is enabled. See the
[profile matrix](../macros/directive-launch.md#auto-directive).

### Plan Approval Keybindings

| Key           | Action                                                                  |
| ------------- | ----------------------------------------------------------------------- |
| `j` / `k`     | Move through Actions, then Decisions, then Verdict                      |
| `Space`       | Next choice (wrapping) or flip a toggle; on an AND member, toggle       |
| `l` / `Right` | Next choice, or set yes                                                 |
| `h` / `Left`  | Previous choice, or set no                                              |
| `r`           | Reset the focused decision row to ★                                     |
| `R`           | Reset every decision row to ★                                           |
| `z`           | Toggle the full-width decision sheet (Esc leaves the sheet first)       |
| `Enter`       | Submit the primary (approve) decision with the values on display        |
| `Ctrl+S`      | Submit the focused decision (for example reject or feedback)            |
| `1`–`9`       | Submit the correspondingly numbered decision                            |
| `i`           | Open the input panel for the focused decision's note or declared fields |
| `c`           | Open [Custom Approval](#custom-approval)                                |
| `e`           | Edit the plan file in `$EDITOR`                                         |
| `y`           | Copy the plan file path to the clipboard                                |
| `Y`           | Copy the plan content to the clipboard                                  |
| `d`           | Open Gate Debug                                                         |
| `Ctrl+D`/`U`  | Scroll plan content down / up                                           |
| `g` / `G`     | Scroll to top / bottom                                                  |
| `q` / `Esc`   | Cancel                                                                  |

The navigation, submit, and input-panel keys are the shared gate-modal keys; see
[Remapping Gate Modal Keys](global-controls.md#remapping-gate-modal-keys).

The question modal also supports `y` to copy questions and selected answers.

### Custom Approval

Pressing `c` in the plan approval modal opens a custom approval dialog. Choose the
approval outcome directly: Approve, Tale, or Epic. These choices map to the same
response protocol used by external approval transports: Approve runs the coder without
asking the runner to commit an SDD plan, while Tale and Epic commit the plan under the
matching tier in the resolved SDD plans root's `<YYYYMM>/` directory. The root may be
in-tree, a `.sase/sdd/` clone, or the split `--plans` sidecar;
`sase repo path plans` prints it.

| Key          | Action                        |
| ------------ | ----------------------------- |
| `Enter`      | Choose the highlighted action |
| `a`          | Highlight Approve             |
| `t`          | Highlight Tale                |
| `e`          | Highlight Epic                |
| `m`          | Select coder model            |
| `p`          | Edit additional coder prompt  |
| `w`          | Edit wait dependencies        |
| `c`          | Edit capacity (Epic only)     |
| `Ctrl+N`/`P` | Next / previous action        |
| `q` / `Esc`  | Cancel                        |

The dialog keeps the custom coder prompt and follow-up model controls for Approve and
Tale. Epic approval reads its land and phase models from structured plan frontmatter and
launches bead work directly, so those controls are hidden for Epic:

- **Additional prompt** — Optional extra instructions for the coder follow-up. It is
  used by Approve and Tale.
- **Wait for** — Optional comma-separated agent names, `turn=<agent>`, `bead=<id>`,
  and `hood=<name>` entries. Press `w` to edit it. The dialog validates the same grammar
  as `sase plan approve --wait` before returning to the approval screen. A `turn=<agent>`
  entry waits for that agent's current turn instead of the whole session; the approval
  row shows it as `agent (turn)`. Approve and Tale hold the coder follow-up; Epic
  holds the launched bead work.
- **Capacity** — Epic only. Press `c` to set a per-launch runner-capacity budget for the
  launched bead work; blank keeps the default queue behavior and `1` runs it alone.
- **Coder model** — Select an LLM model for the next follow-up agent instead of using
  the role default. For Approve and Tale that agent is the coder. Shows all registered
  models grouped by provider (Claude, Codex, Antigravity, Qwen, OpenCode, Muse Code,
  Grok Build) with a "Custom..." option for freeform input. A model its provider flags
  with an advisory carries a warning-styled `⚠ <label>` suffix on its row (`ⓘ` for
  informational advisories), with the full advisory sentence in the row's secondary text
  — this is where somebody actually chooses a model, so the trade is impossible to miss.
  See [LLM Providers — Model advisories](../providers/models.md#model-advisories). Type to filter by
  provider, model id, label, or short alias; use `j`/`k` or arrows to navigate, `Enter`
  to select, `Esc` to clear the filter or cancel, and `'` for jump hints over the
  visible selectable rows. The displayed default resolves to the model the handoff will
  actually use: for Approve and Tale, the validated tale size selects the corresponding
  `@<size>` alias directly, with sizeless tales using `@medium`. Selecting a
  specific model and then re-opening the picker and choosing "Follow-up default" resets
  the follow-up back to that role default (distinct from pressing `Esc`, which keeps the
  current selection).

The custom approval dialog does not expose separate commit/run switches because the
selected outcome determines the commit location and follow-up behavior. Additional
session members are launched explicitly with `%i(suffix, session=parent)`; they are not
selected at the plan gate.

## Launch Approval

Launches requested by a running agent (see
[Agent-initiated launches](../agents/agent-launches.md#agent-initiated-session-launches)) arrive
as priority notifications with a `LaunchApproval` action. Selecting one opens the launch
approval modal, which renders the request's human-readable preview
(`launch_preview.md`). Clan slots identify their rootless clan alongside the model,
kind, and planned member name. Press `a` to approve, `r` to reject, and `q` or `Esc` to
cancel. sase's TUI resolves the same hash-verified command bundle used by mobile and
remote callbacks, while retaining the older launch-request fallback (see
[TUI migration notes](../upgrading/tui.md#hitl-and-launch-request-fallbacks)). The CLI equivalents
are `sase launch approve <selector>` and `sase launch reject <selector>`. From inside an
agent, `sase launch request` hands work to a `LAUNCH` gate turn; with
[staged handoffs](../agents/agent-sessions.md#handoff-completion), publication waits for
host completion. The requesting process does not wait for the response. By default,
approval, rejection, timeout, or
gate/dispatch failure settles the turn and resumes the original requester as one session
successor. That successor receives the decision, reviewer feedback, typed dispatch
result, requester/workspace/session identity, and checkpoint; a stopped gate does not
resume. A request can explicitly choose `terminal_handoff` when every branch should end
without a requester continuation. Outside a SASE agent, terminal handoff is the default:
the command registers the gate, prints its creation descriptor, and returns. Automation
that needs the terminal gate result can then run
`sase gate wait -i <request-id> -k launch -j`.

## Agent Holds

An agent hold is a durable reverse wait: while it is active, matching `WAITING` or
`QUEUED` agents, later launches, and undispatched procs are kept from starting. Holds
are armed with [`sase agent hold`](../cli/agent.md#sase-agent-hold) or the
[`%hold` directive](../macros/directive-launch.md#hold-directive). sase's TUI shows holds in three places:

- **Agents tab rows.** A `QUEUED` row parked by a hold appends `held by <armer>` after
  its queue position. If a held agent and the agent that armed the hold end up blocking
  each other, SASE also sends a **Hold deadlock** notification; the hold's TTL still
  guarantees progress, but you can release the hold or kill one side sooner.
- **Launch-preview confirmation.** Submitting a prompt with a broad `%hold` — one that
  combines `future` with `scope=host`, or whose `pending` capture would freeze more
  WAITING and QUEUED agents than `agent_hold_confirm_capture_threshold` (default `10`) —
  opens an **Arm this hold?** confirmation before anything launches. It lists each broad
  hold's directive and live `pending` capture, plus a warning for a host-wide `future`
  hold. The accepted prompt is already represented by a preparing proc row. Cancelling
  restores it when safe, or stashes it when another prompt or modal has focus; a
  standalone hold confirmation defaults to **Cancel**. Narrow holds launch without
  asking. During the current beta, pressing **Arm** only confirms the launch preview; it
  does not write a hold to the store.
- **Holds pane.** Open SASE Admin Center with `#`, then Config > **03 Holds** (`0` then
  `3`). Each row shows the armer and its kind, the scope (`host` or `project:<name>`),
  the selectors (`names=`, `hoods=`, `tribes=`, `future`, and `pending=N`), and the time
  until expiry. Press `j` / `k` (or the arrow keys) to move, `d` to release the
  highlighted hold, `r` to reload, and `q` or `Esc` to close Admin Center.

## Linked Chats in Multi-Step Workflows

When a workflow spawns multiple agents (e.g., a planner step followed by a coder step),
the chat history files for each step are cross-linked via a `## Linked Chats` markdown
section. This section is inserted near the top of each chat file and lists all related
agents with their roles and file paths, making it easy to trace the full workflow from
any individual agent's chat history.

For example, a plan-then-code workflow produces chat files with:

```markdown
## Linked Chats

- **1. planner** — `/path/to/planner_chat.md`
- 2. coder — `/path/to/coder_chat.md`
```

The current agent's entry is bolded for quick identification.

## Retry/Fallback Display

When an agent encounters a retryable error (configured via `llm_provider.retry`), the
Agents tab shows retry state:

- **RETRYING** — Shown in bold orange when waiting before the next retry attempt.
  Includes a countdown timer: `RETRYING (45s)`.
- **↻N** — Shown after the status for running agents that have retried. The number
  indicates how many retries have occurred (e.g., `↻2` means two retries so far).
- **▸Model** — Appended to the retry annotation when the agent has fallen back to an
  alternate model (e.g., `↻3▸flash`).

### Prior Agent Attempts

Every time the axe retry loop retries an agent — context-limit retry, provider/API-error
retry, user-configured retry, or fallback-model switch — the failed attempt's partial
reply, error text, timestamps, and model are snapshotted under
`<artifacts_dir>/attempts/<N>/`. The AGENT REPLY area in the Agents tab renders these
prior attempts inline with styled dividers before the current/final attempt, so the full
arc of the agent's work stays visible in one scroll.

sase's TUI hydrates prior-attempt history lazily. Normal Agents-tab refreshes do not
enumerate every `attempts/<N>/` directory; the selected detail panel, `D` attempt-view
toggle, and content search hydrate the needed attempt records on demand.

Press `D` to collapse the view to the current attempt only; press `D` again to
re-expand. The binding only appears in the keybinding footer when the selected agent has
one or more prior attempts.

<a id="sase-repro"></a>
Moved to [sase repro](../cli/repro.md#sase-repro).
<a id="cli-options-17"></a>
Moved to [sase repro](../cli/repro.md#sase-repro).
<a id="command-behavior-11"></a>
Moved to [Agents Tab Reproduction Bundles](agents-tab.md#agents-tab-reproduction-bundles).

## Related

- [TUI hub](index.md) — all Agents tab reference pages.
- [Agent statuses](agent-statuses.md) — agent, wait, and completion statuses.
- [TUI migration notes](../upgrading/tui.md) — suffixes, auto-names, and launch fallbacks.
