---
title: "[07] Driving SASE From Your Phone — Telegram as the Mobile Control Surface"
date: 2026-05-21
draft: true
description: >-
  The sase-telegram plugin turns an existing Telegram chat into a mobile control surface for SASE — launch agents,
  approve plans, kill runs, and review generated images from the phone in your pocket.
categories:
  - Agentic Software Engineering
  - Plugins
slug: telegram-mobile-agents
links:
  - Plugins: plugins.md
  - Notifications: notifications.md
  - Mobile Gateway: mobile_gateway.md
  - "[06] ChangeSpecs in Practice — Review State Outside the Chat": blog/posts/changespecs-in-practice.md
  - View on GitHub: https://github.com/sase-org/sase-telegram
---

# [07] Driving SASE From Your Phone — Telegram as the Mobile Control Surface

The mobile gateway is the long-term path to a phone-native SASE client. The plugin already in everyone's pocket is
Telegram. **sase-telegram** is the bridge: pip-install a plugin, point it at a bot token, and a regular Telegram chat
becomes a two-way control surface for agents, plans, ChangeSpecs, and generated artifacts.

<!-- more -->

[\[06\]](changespecs-in-practice.md) showed how review state lives in a `.sase` ChangeSpec on disk. This post is about
moving the operator off the keyboard entirely: replying to plan approvals, launching new runs, and reviewing rendered
plans or generated images from the same chat you already use for everything else.

## What The Plugin Actually Is

sase-telegram is a chop, not a long-running daemon. Installing it adds two CLI scripts that AXE runs on its normal
cadence:

| Command                 | Direction | What it does                                                                                |
| ----------------------- | --------- | ------------------------------------------------------------------------------------------- |
| `sase_chop_tg_outbound` | Phone ←   | Reads unsent SASE notifications, formats them as Telegram MarkdownV2, attaches PDFs/images. |
| `sase_chop_tg_inbound`  | Phone →   | Polls Telegram for button presses, text, photos, and slash commands; writes response files. |

Both scripts shell into the same notification machinery [\[03\]](axe-background-daemon.md) covered. The outbound side
reads from the unsent-notification high-water mark; the inbound side writes response files that the local SASE process
picks up the next time it sweeps. There is no separate state machine — Telegram is just another transport, drawn from
and back into the same notification tables that drive the in-TUI inbox and Slack delivery.

Credentials and runtime knobs are deliberately small:

```
pass show telegram_sase_bot_token   # bot token via pass(1)
SASE_TELEGRAM_BOT_CHAT_ID            # chat to send messages to
SASE_TELEGRAM_BOT_USERNAME           # bot username
SASE_TELEGRAM_RATE_LIMIT=8/15        # sliding-window rate limit
SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED # presence-disables launches on shared hosts
```

The bot token never lands in the repo. The chat ID and username are environment variables. The rate limiter is a sliding
window so a noisy axe sweep can't flood the chat. On shared hosts that should receive notifications but not spawn
agents, set `SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED` and callbacks/feedback/slash commands keep working while free-form
text is logged and ignored.

## Outbound Notifications

Outbound sends unread, non-silent SASE notifications to Telegram using the same notification store ACE reads. Plan
approvals, HITL requests, user questions, and completion notices arrive as Telegram messages with inline keyboards or
attachments when applicable.

The plugin does not maintain a separate delivery threshold. Delivery is controlled by the notification high-water mark,
read state, silent flag, rate limiter, and outbound lock.

## Launching Agents From The Chat

Any text message that isn't a slash command, a feedback reply, or a callback is treated as a prompt for a new agent. The
inbound script expands xprompt references the same way the local CLI does, so `#mentor reorder` from your phone launches
with the same template you use in the terminal. Model fan-out works too: `%{%m:opus | %m:sonnet} draft tests for X`
launches the same prompt across both models and gives the runs auto-assigned names so they don't collide.

Photos and image documents follow the same path. Send a screenshot of a failing UI or a whiteboard sketch and the plugin
downloads the attachment to `~/.sase/telegram/images/`, then launches an agent with the image and message text as
context. This is the cheapest possible answer to "I'm not at my desk but I can describe what's wrong with a picture" —
the picture is just another way to seed a prompt.

Each launch confirmation message comes back with the agent's provider/model label, workspace number, a prompt snippet,
and four buttons: **Resume**, **Wait**, **Kill**, **Retry**. Resume and Wait are copy-text buttons — pressing them
copies a pre-filled command to your clipboard so the next interaction can happen in-terminal if you want it to. Kill and
Retry stay inside Telegram. The result is that an agent launched from the chat has the same control surface as one
launched from ACE, just rendered as buttons instead of keystrokes.

## Approving Plans, Answering Questions, Reviewing Images

The actionable notification types each get their own inline keyboard:

| Notification      | Buttons                                      | Use                                                                |
| ----------------- | -------------------------------------------- | ------------------------------------------------------------------ |
| Plan Approval     | Tale / ✅ Approve / Epic / Reject / Feedback | The SDD plan modes from [\[04\]](beads-and-sdd.md), plus rejection |
| HITL Request      | Accept / Reject / Feedback                   | Mid-run human-in-the-loop checkpoints                              |
| User Question     | dynamic option buttons + Custom              | Multiple-choice questions emitted via `sase_questions`             |
| Agent Launched    | Resume / Wait / Kill / Retry                 | Lifecycle control over the run that was just launched              |
| Workflow Complete | Resume copy button                           | Re-enter the conversation with one tap                             |
| Image Generated   | inline image                                 | Review what an agent rendered without leaving the chat             |
| Error Digest      | digest file attachments                      | Triage failures with the same context the TUI shows                |
| Agent Killed      | Retry copy button                            | Re-launch the killed prompt with one tap                           |

Plan approvals are the everyday case. The plan content is wrapped in an expandable MarkdownV2 blockquote, and when the
plan is long enough to be inconvenient inline, sase-telegram renders it to PDF through SASE's shared Markdown renderer
and sends the PDF as an attachment. Either way, the four mode buttons map directly to the SDD plan modes from [04] —
**Tale** and **Epic** queue work at different scopes, and **Approve** accepts a plan as-is. **Feedback** is the escape
hatch: tap it and your next text message becomes the feedback body, written to a response file SASE picks up on the next
sweep.

Image notifications are how generated artifacts come back. The `sase_chop_tg_outbound` script attaches generated images
inline so you can review what an agent rendered without leaving the chat. Combined with launching from a photo, this
closes the loop: send an image, get an image, both inside Telegram. For richer review of multi-image runs the
[agent_images.md](../../agent_images.md) guide covers the local side.

## The Slash Command Surface

Beyond free-form prompts, sase-telegram registers a handful of slash commands with Telegram's `set_my_commands` API so
they show up in the chat input UI:

| Command              | What it does                                                                      |
| -------------------- | --------------------------------------------------------------------------------- |
| `/list`              | Lists running agents with their families and current state                        |
| `/kill [<name>]`     | Kills a specific agent or, with no argument, picks one from a button list         |
| `/resume`            | Sends a copy-text button to re-enter the most recent conversation                 |
| `/changes [project]` | Lists active ChangeSpecs with a copy-text button for the bare workflow tag        |
| `/xprompts`          | Exports the xprompt catalog so you can see what `#foo` will expand to             |
| `/bead [<id>]`       | Without an ID, lists active beads as picker buttons; with one, shows bead details |
| `/update`            | Starts the shared SASE chat update worker in a detached process                   |

`/changes` deliberately excludes Submitted, Archived, and Reverted entries — the assumption is that a phone is for live
work, not archive browsing. The copy-text button for each ChangeSpec emits its detected provider ref, such as
`#gh:foobar`, so the next agent you launch can target it directly. `/bead` follows the same picker pattern as the kill
flow: most of the time you want a button list, not the cognitive overhead of remembering an ID.

Deployments can add their own slash-menu commands under `telegram.commands` in SASE configuration. Each entry declares a
description, an executable with fixed arguments, message-or-PDF delivery, and a timeout; commands run without a shell.
See [Custom Telegram commands](../../configuration.md#telegram) for the schema and doctor check.

`/update` is the operationally interesting built-in. It detaches the shared chat update worker and runs
`sase update --json` through the same managed-versus-dev update planner as ACE. The updater performs any AXE restart
required by an actual code update; after the command succeeds or fails, the worker independently ensures AXE is running.
The completion message that arrives on the next inbound sweep reports success or the failure exit code and includes the
worker log path. The phone becomes, in effect, a remote control for keeping the local install fresh.

## What This Replaces (And What It Doesn't)

The [mobile gateway](../../mobile_gateway.md) is the richer host API for paired native clients, FCM push hints, and
Tailscale Serve deployments. sase-telegram remains the chat-native option and covers a high-value subset of the mobile
workflow with infrastructure that is already on every developer's phone:

- **What it replaces:** "I need to be at my laptop to approve a plan or answer a HITL question." Plan approvals, HITL
  requests, user questions, kill/retry, and launching new prompts all work from the chat. Generated images come back
  inline. Plans that don't fit inline come back as rendered PDFs.
- **What it doesn't replace:** ACE's two-dimensional view of every agent across every workspace, the keybinding-driven
  PR navigation, multi-line plan editing. The phone is a control surface, not a development environment, and
  sase-telegram is deliberately scoped to fit that.

If you operate the same SASE install from multiple machines and one of them shouldn't be allowed to launch agents on
your behalf, that's exactly what `SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED` is for: keep the notifications flowing, keep the
callbacks responsive, but reject free-form prompts as launches. Notifications still go to whichever host runs outbound;
the launch path is independent.

## What To Read Next

- [sase-telegram on GitHub](https://github.com/sase-org/sase-telegram) — the plugin source, with the full inbound and
  outbound script implementations and configuration reference.
- [Plugins overview](../../plugins.md) — how SASE plugins, chops, and entry points fit together.
- [Notifications](../../notifications.md) — the notification model that sase-telegram drives, including indicator,
  toast, modal, and Telegram delivery paths.
- [Mobile gateway](../../mobile_gateway.md) — where the longer-term native mobile story is heading.
- [Agent images](../../agent_images.md) — local-side review for runs that produce rendered images.
