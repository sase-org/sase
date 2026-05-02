# Notification Panel — Brainstorm

A wide-net list of ideas for making sase's notification panel better. Grouped by theme, not
prioritized. Each idea has a rough size tag (S/M/L) and a one-line "why" so you can skim and pick.

## Current state (one-paragraph recap)

`N` opens a Textual modal that lists unread notifications backed by
`~/.sase/notifications/notifications.jsonl`. Senders include `plan`, `question`, `hitl`, `sync`,
`axe`, and workflow names. Each notification carries notes, file attachments, and an action type
(`PlanApproval`, `JumpToAgent`, `JumpToChangeSpec`, `HITL`, `UserQuestion`, `ViewErrorReport`,
`Tmux`). State is binary: `read`/`dismissed`, plus a `silent` flag for hidden agents. Polling in
`AgentNotificationMixin._poll_agent_completions()` drives toasts, the unread badge, and tmux bell.

Key pain points surfaced from code/git history: noisy retry/fallback notifications (later
suppressed), fragile auto-dismiss state machine for external Telegram approvals, no
search/filter, no grouping, no snooze, planned Telegram integration not yet wired up.

---

## 1. Triage & state model

The single read/dismissed bit is the biggest constraint — most other ideas downstream get
cheaper once richer state exists.

- **Snooze (S)** — `s` to push a notification out by 15m / 1h / "until tomorrow morning". Hidden
  from list during snooze window, then reappears as unread. Big quality-of-life win for plan
  approvals you can't action right now.
- **Pin / star (S)** — keep a notification at the top until manually unpinned. Useful for
  plans/questions you want to keep visible while you context-switch.
- **Archive vs dismiss (S)** — distinguish "I dealt with this" from "I don't care, hide forever".
  Currently dismissed = both. Lets you re-open recent archives with `u` (un-archive).
- **Per-sender mute (S)** — `M` on a notification mutes future ones from that sender for a TTL.
  Cheaper than editing config when an axe digest gets spammy.
- **Grouping / threading (M)** — collapse notifications by `cl_name` or `agent_name`. A retry
  chain or a workflow with three HITL steps shows as one expandable thread instead of three rows.
- **Severity tier (S)** — explicit `severity` field (`critical` / `info` / `chatter`) instead of
  inferring from sender. Drives sort order, color, and whether the tmux bell rings.
- **Custom labels / tags (M)** — free-form tags (`@security`, `@waiting-on-user`) settable from
  the panel and queryable in filter mode. Encodes user-defined workflows the dataclass doesn't.

## 2. Filtering, search, and navigation

Right now it's a flat scroll. Once you have >20 unread it gets ugly fast.

- **Inline filter bar (M)** — `/` opens a filter input with prefix syntax: `sender:plan`,
  `cl:foo-bar`, `unread`, `today`, `has:plan`. Reuse the existing CLs-tab filter mini-language.
- **Saved filters (S)** — `F1`/`F2`/`F3` jump between user-defined filters
  ("plans only", "errors only", "today's"). Stored in `sase.yml`.
- **Tabbed sub-views (M)** — top of modal has tabs: `All` / `Plans` / `Questions` / `Errors` /
  `Workflows`. Number badges per tab. Hot-swappable with `1`-`5`.
- **Date separators (S)** — `── Today ──`, `── Yesterday ──`, `── Earlier ──` headers between
  rows. Cheap, big legibility upgrade.
- **Jump-to-next-unhandled (S)** — `Tab` skips past read/snoozed entries to the next
  actionable one (plan approval / question / HITL). Lets you treat the panel like an inbox-zero
  queue.
- **Search highlights (S)** — when filtering, highlight match spans in notes/sender like
  `agents` tab does. Already a solved pattern in this codebase.

## 3. Information density & content

The list rendering is good, but each row currently leaks context that could live in the row.

- **Show CL/agent status next to each notification (S)** — a plan approval is more urgent if the
  agent is `IDLE_AWAITING_PLAN` vs already `RETRIED`. Lift the agent's current status into the
  row prefix.
- **Compact / expanded modes (S)** — `z` toggles between one-line-per-row and the current
  multi-line layout. Useful when triaging 50+ at once.
- **Inline action affordances (S)** — render `[Approve] [Reject] [View]` buttons in the row for
  plan approvals so power users don't have to open the file viewer first. Keymap: `a`/`r`.
- **Diff preview for plan files (M)** — when a plan attachment is selected, show the unified
  diff against the previous plan version instead of the full file. Most plan iterations are
  small deltas.
- **Sparkline of recent activity per sender (L)** — tiny ascii histogram in the header showing
  notification volume per sender over last 24h. Helps spot spam/regression.
- **"Why am I seeing this?" footer (S)** — small line under the notification explaining the
  trigger (e.g., "from `agent_completion_hook`, agent `coder.20260424...`"). Demystifies the
  source.

## 4. Action handlers & flows

The dispatch list (`JumpToAgent`, `JumpToChangeSpec`, etc.) is a nice abstraction; we can add
more verbs cheaply.

- **Reply inline to questions (M)** — `r` opens an inline textarea that writes
  `question_response.json` without leaving the modal. Currently you push another modal.
- **Quick-approve plans without opening (S)** — `A` on a `PlanApproval` row asks `y/n`,
  approves, dismisses. For trivial plans you trust at a glance.
- **Delegate to mentor (M)** — `D` on a plan/question routes the response to a chosen mentor
  agent. Useful when you want a second opinion before approving.
- **Re-trigger / retry from the panel (M)** — for failed-workflow notifications, `R` (capital)
  spawns a retry agent (already supported under the hood by `run_agent_retry_spawn.py`).
- **Copy-to-clipboard helpers (S)** — `y` yanks the CL name, `Y` yanks the file path, `Ctrl-y`
  yanks the full notification JSON for sharing.
- **Quick-jump to tmux session if it exists (S)** — automatically run the `Tmux` action if a
  matching session is alive, otherwise fall through to `JumpToAgent`. Removes a chooser step.

## 5. Delivery channels & cross-device

Telegram is planned but not wired. While you're touching the design, broaden it.

- **Generic outbound webhook adapter (M)** — instead of hardcoding Telegram, define a
  `NotificationChannel` interface and ship Telegram + Google Chat (already a sibling plugin) +
  generic-webhook implementations. Enables Slack/Discord/ntfy without core changes.
- **Per-sender / per-severity routing (M)** — config: "`plan` notifications go to Telegram and
  TUI", "`axe` digests only TUI". Avoids phone spam.
- **Quiet hours (S)** — config-driven window where outbound channels are silenced (still
  persisted, still TUI-visible). Cheaper than per-sender muting for a focused work session.
- **Desktop notifications via `notify-send` / `osascript` (S)** — local-only fallback when no
  remote channel is configured. One small adapter.
- **Email digest (L)** — once-a-day rollup of all dismissed/read notifications as an audit
  email. Useful for compliance / standup prep.
- **Two-way external responses are fragile** — `_auto_dismiss_external_plan_response()` checks
  three different signal patterns. Replace with a single canonical `<notification_id>.response.json`
  written by any channel; the polling watcher dismisses on file presence. Simpler invariant.

## 6. Persistence, performance, observability

The JSONL + fcntl design is fine at small scales but has rough edges as it grows.

- **Rotate / compact `notifications.jsonl` (S)** — when read+dismissed entries dominate, archive
  them to `notifications-YYYY-MM.jsonl` and keep the live file small. Polling re-reads the file
  on every refresh today.
- **Index by id (S)** — keep an in-process dict of `id → offset` so `mark_read()` / `mark_dismissed()`
  don't need to rewrite the whole file. Currently every state change rewrites JSONL.
- **Watcher instead of polling (M)** — `inotify` / `fsevents` / `kqueue` instead of refresh-cycle
  polling. Lower idle CPU, lower latency for new toasts.
- **Schema versioning (S)** — add a `schema_version` field so future shape changes can migrate
  cleanly. Currently every reader has to defend against missing fields.
- **Telemetry hooks (S)** — emit counts to the existing Prometheus integration: notifications
  created/dismissed/snoozed by sender, time-to-action for plan approvals. Helps tune noise.
- **`sase notify ls` / `sase notify dismiss <id>` (S)** — round out the CLI so scripts can
  inspect/manage notifications without opening the TUI. The producer side (`sase notify`)
  already exists; the consumer side doesn't.

## 7. Onboarding & discoverability

Several existing keybindings are non-obvious.

- **First-run hint (S)** — when the panel opens with zero notifications, show a one-screen
  cheat sheet of what actions exist and what each sender means.
- **Help overlay `?` (S)** — already a Textual idiom; missing here. Auto-generated from the
  `BINDINGS` list.
- **Footer keymap groups (S)** — current footer is flat. Group bindings by category
  (Navigate / Triage / Open / Channel) so the eye can find what it needs.

## 8. Speculative / research-shaped

Don't build these soon, but worth keeping warm.

- **AI-summarized digest at the top (L)** — a small LLM call summarizes the current unread set
  ("3 plans waiting, 1 question on `cl-foo`, 2 axe errors related to retry handling"). Reuses
  the project's existing provider plumbing.
- **"Auto-action policies" (L)** — user-defined rules: "auto-approve any plan from
  `mentor.summarize-hook`", "auto-dismiss `sync` notifications older than 1h". Small DSL in
  `sase.yml`.
- **Notification permalinks (M)** — every notification has a stable URL like
  `sase://notification/<id>` that opens the panel pre-focused on that row. Useful from external
  channels and from the Gchat plugin.
- **Cross-machine sync (L)** — notifications produced on one machine appear on another.
  Probably overkill but the gchat plugin already implies cross-machine awareness.

---

## Suggested first slice

If we were sequencing this, a high-leverage starter pack that doesn't require schema migrations:

1. Snooze + archive (richer state)
2. `/` filter bar with `sender:` / `cl:` prefixes
3. Date separators in the list
4. Help overlay `?`
5. Replace the three-pattern external-response state machine with a single
   `<id>.response.json` convention

Together those address the "no filter, no search, fragile state machine, undiscoverable
keymap" complaints without touching channels or persistence.
