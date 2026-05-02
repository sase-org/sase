# Telegram Integration Improvements & Power-User Workflows

Research into improvements for the existing sase-telegram integration and general Telegram power-user workflows.

**Context**: The sase-telegram plugin (`../sase-telegram/`) is a working, production-grade two-way integration. It runs
as two chops (outbound/inbound) on a 5-second lumberjack interval, sends notifications with inline keyboards, handles
button callbacks and text messages, supports agent launching from Telegram, and has rate limiting, activity-aware
sending, and PDF conversion.

---

## Part 1: Integration Improvements

### 1. Streaming Responses via sendMessageDraft (Bot API 9.3+)

**What**: Bot API 9.3 (December 2025) introduced `sendMessageDraft`, which lets bots stream partial messages to users as
they're generated — similar to how ChatGPT streams responses. As of Bot API 9.5, this is available to all bots (not just
AI-designated ones).

**Why it matters**: Currently, when a workflow completes and produces a long response, the user sees nothing until the
full message arrives. With streaming, the user could watch the agent's output appear in real-time, just like in the TUI.

**How to use it**:

- When forwarding agent output to Telegram, send partial chunks as they're generated via `sendMessageDraft`.
- Useful for: workflow-complete summaries, plan content review, error digests.
- Falls back to regular `sendMessage` for bots on older API versions.

**Effort**: Medium. Requires changes to both the outbound chop (to detect streaming-capable content) and the Telegram
client wrapper (to support the new API method). Need to verify python-telegram-bot support for this method.

### 2. Forum Topics in Private Chats (Bot API 9.3+)

**What**: Bot API 9.3 extended forum topics to private chats. A single bot can now manage multiple conversation threads
with one user using `message_thread_id`.

**Why it matters**: Currently, all sase notifications (plan approvals, HITL requests, workflow completions, error
digests, agent launches) go into a single flat chat. With topics, each category or even each agent/bead could have its
own thread, making it much easier to track parallel work.

**Possible threading schemes**:

- **By notification type**: Topics for "Plans", "HITL Requests", "Errors", "Completions", "Agents".
- **By agent/bead**: Each active agent or bead gets its own topic, keeping all related messages together.
- **By epic**: Group all bead-related messages under their epic's topic.
- **Hybrid**: Type-based topics with agent name in the message header.

**How to use it**:

- Enable topics on the bot's private chat.
- Use `createForumTopic` to create topics dynamically.
- Pass `message_thread_id` when sending messages.
- Map inbound messages to the correct agent/context based on which topic they came from.

**Effort**: Medium-high. Requires topic lifecycle management (create, archive, close) and mapping between sase concepts
(agents, beads, notification types) and Telegram topics.

### 3. Native Checklists (Bot API 9.1+)

**What**: Bot API 9.1 introduced `sendChecklist` and `editMessageChecklist` with `ChecklistTask` items.

**Why it matters**: Plans and beads have natural checklist semantics. Instead of sending a plan as a wall of markdown
text with Approve/Reject buttons, send it as an interactive checklist where the user can see (and potentially check off)
individual steps.

**Use cases**:

- Plan approval: Send plan steps as a checklist. User reviews each step before approving.
- Bead tracking: Show bead phases as checklist items, auto-updating as phases complete.
- Epic overview: Show all beads in an epic as a checklist.

**Effort**: Medium. Need to parse plan content into checklist items and handle checklist state updates.

### 4. telegramify-markdown for Better Formatting

**What**: The `telegramify-markdown` Python library converts standard Markdown (including LLM output) directly to
Telegram-compatible `(text, entities)` tuples using UTF-16 code unit offsets. Built on Rust pulldown-cmark bindings.

**Why it matters**: The current `formatting.py` does manual MarkdownV2 escaping, which is fragile and has known edge
cases (the code already has a fallback to plain text when MarkdownV2 parsing fails). `telegramify-markdown` handles this
correctly, including LaTeX-to-Unicode, expandable blockquotes, and Mermaid diagram rendering.

**Benefits**:

- More reliable formatting (no more fallback-to-plain-text).
- Support for expandable blockquotes (great for long content — user taps to expand).
- Better code block handling.
- Actively maintained.

**Effort**: Low. Replace the manual escaping logic in `formatting.py` with `telegramify-markdown` calls. Test with
various notification types to ensure parity.

### 5. Expandable Blockquotes (Bot API 7.4+)

**What**: The `expandable_blockquote` entity type collapses long quoted content behind a "tap to expand" UI.

**Why it matters**: Plan content and error digests can be very long. Currently, long content is truncated with "... (see
TUI for full output)". Expandable blockquotes let you send the full content in a compact form — the user sees a summary
and taps to expand if they want details.

**Use cases**:

- Plan content: Show first few lines, expand for full plan.
- Error traces: Show error summary, expand for full traceback.
- Workflow output: Show summary, expand for details.

**Effort**: Low. Modify `formatting.py` to wrap long content in expandable blockquote entities. Works well with
`telegramify-markdown` which supports this natively.

### 6. Message Effects (Bot API 7.4+)

**What**: The `message_effect_id` parameter adds visual effects (animations) to sent messages.

**Why it matters**: Subtle but useful for distinguishing message types at a glance. A "workflow complete" message could
have a different effect than an "error digest" message. The "fireworks" effect on a successful epic completion, for
example.

**Effort**: Very low. Just pass the `message_effect_id` parameter on send calls. Need to discover available effect IDs.

### 7. Copy Text Buttons (Bot API 7.11+)

**What**: `CopyTextButton` inline buttons that copy arbitrary text to the user's clipboard when pressed.

**Why it matters**: Useful for agent launch commands, error IDs, bead references, or any text the user might want to
paste elsewhere. Currently, the user has to manually select and copy text from messages.

**Use cases**:

- "Copy bead ID" button on bead completion notifications.
- "Copy error" button on error digest messages.
- "Copy command" button for suggested follow-up actions.

**Effort**: Very low. Add `CopyTextButton` to existing inline keyboards where appropriate.

### 8. Mini App for Rich Dashboard

**What**: Telegram Mini Apps are web applications that run inside Telegram. They support full-screen mode, device
storage, secure storage, and various device capabilities.

**Why it matters**: A Mini App could provide a lightweight dashboard for sase status — running agents, pending
notifications, bead progress — accessible from Telegram without needing to open the TUI. This would be especially useful
on mobile.

**Possible features**:

- Agent status dashboard (running, completed, errored).
- Notification inbox with filtering.
- Plan viewer with rich formatting (better than Telegram's message formatting).
- Bead/epic progress tracker.
- Quick actions (launch agent, approve plan, dismiss notification).

**Effort**: High. Requires building and hosting a web app. However, Telegram provides multiple storage tiers
(CloudStorage, DeviceStorage, SecureStorage) which reduce backend needs.

### 9. Inline Mode for Cross-Chat Agent Access

**What**: Inline mode lets users invoke your bot in any Telegram chat by typing `@botname query`.

**Why it matters**: You could type `@sase_athena_bot status` in any Telegram chat to get a quick agent status update, or
`@sase_athena_bot launch fix typo in README` to launch an agent without switching to the bot's DM.

**Use cases**:

- Quick status checks from any chat.
- Sharing agent outputs with collaborators in group chats.
- Launching agents from anywhere in Telegram.

**Effort**: Medium. Need to implement inline query handling in the inbound chop and define result types.

### 10. Improved Dot Commands

**Current dot commands**: `.kill <name>`, `.list`, `.listx`.

**Possible additions**:

- `.status` — Overall sase status (active lumberjacks, pending notifications, resource usage).
- `.bead [id]` — Show bead status, or list active beads.
- `.epic [id]` — Show epic progress.
- `.logs <agent>` — Tail recent agent logs.
- `.retry <agent>` — Re-launch a failed agent.
- `.quiet [duration]` — Temporarily suppress notifications (e.g., `.quiet 2h`).
- `.config` — Show current Telegram integration config.
- `.help` — List all available commands.

**Effort**: Low per command. The inbound chop already has dot command parsing infrastructure.

### 11. Reaction-Based Quick Responses

**What**: Bots can receive reaction updates on their messages.

**Why it matters**: Instead of pressing an inline keyboard button, users could react to a plan approval notification
with a thumbs-up to approve or thumbs-down to reject. This is faster on mobile (long-press message -> react) than
finding and pressing a small button.

**Effort**: Medium. Need to handle `MessageReactionUpdated` events in the inbound chop and map reactions to actions.

### 12. Improved Agent Launching UX

**Current**: Send text to launch an agent. Supports `%m(opus,sonnet)` for multi-model.

**Possible improvements**:

- **Reply-to-context**: Reply to an error notification to launch an agent with that error as context.
- **Photo/document analysis**: Already supports photos. Extend to documents (PDFs, code files) as agent context.
- **Forwarded messages**: Forward a message from another chat to use as agent context.
- **Voice messages**: Transcribe voice messages (via Whisper or Telegram's built-in transcription for Premium) and use
  as agent prompts. Useful when on mobile.
- **Quick-launch buttons**: After a workflow completes, include "Launch follow-up agent" buttons with pre-filled prompts
  based on the workflow's output.

**Effort**: Varies. Reply-to-context is low effort. Voice transcription is medium. Quick-launch buttons are low.

### 13. Local Bot API Server for Large Files

**What**: Telegram offers a self-hosted Bot API server that removes the 50MB upload limit (up to 2GB) and 20MB download
limit.

**Why it matters**: For large file attachments (build artifacts, large logs, database dumps), the standard Bot API
limits can be restrictive. The local server also enables `file://` URI scheme for sending local files without uploading
them first.

**Effort**: Medium for setup (Docker or binary), low for code changes (just change the API base URL).

---

## Part 2: Telegram Power-User Workflows

These are general Telegram tips and workflow patterns, not specific to sase integration code.

### 1. Chat Folder Organization

Set up dedicated folders for sase-related chats:

- **"Sase" folder**: Contains the sase bot chat, any sase-related channels/groups.
- **"Dev" folder**: Broader dev tools — CI/CD notification bots, GitHub bots, monitoring bots.
- Navigate with `Ctrl+1` through `Ctrl+7` on desktop for instant folder switching.
- Premium users get up to 20 folders with 200 chats each.

### 2. Saved Messages as Scratchpad

- `Ctrl+0` jumps to Saved Messages instantly.
- Forward important agent outputs, error traces, or plan summaries to Saved Messages for later reference.
- Use as a "clipboard" between devices — paste code on desktop, read on phone.
- Tag saved messages with hashtags for easy searchability (e.g., `#sase #error #plan`).

### 3. Keyboard Shortcuts for Speed

Essential desktop shortcuts for bot interaction:

| Shortcut         | Action                                       |
| ---------------- | -------------------------------------------- |
| `Ctrl+K`         | Quick search (find bot chat instantly)       |
| `Ctrl+0`         | Jump to Saved Messages                       |
| `Ctrl+1-7`       | Jump to chat folders                         |
| `Up Arrow`       | Edit last message (fix typo in agent prompt) |
| `Ctrl+F`         | Search within current chat                   |
| `Ctrl+Shift+F`   | Global search across all chats               |
| `Alt+Click Send` | Schedule a message                           |
| `Ctrl+B/I/U`     | Bold/italic/underline formatting             |
| `Ctrl+Shift+M`   | Monospace (for code in messages)             |
| `Ctrl+L`         | Lock Telegram with passcode                  |

### 4. Scheduled Messages for Delayed Agent Launches

`Alt+Click` the Send button to schedule a message. Use this to:

- Schedule agent launches for off-hours (e.g., start a long-running task when you leave for the day).
- Set reminders to check on agent progress.
- Queue multiple agent launches at specific times.

### 5. Multiple Accounts for Separation

Telegram Desktop supports up to 3 accounts per instance. Useful for:

- **Personal account**: Regular Telegram use.
- **Sase bot account**: Dedicated to sase interactions — cleaner notification flow.
- **Testing account**: For testing bot changes without affecting the production chat.

### 6. Pinned Messages for Active Context

Pin the most important active notification (current plan awaiting approval, critical error) to the top of the bot chat.
This persists the context even as new messages scroll by.

### 7. Telegram as CI/CD Notification Hub

Beyond sase, use Telegram bots for:

- **GitHub Actions**: `appleboy/telegram-action` sends build/deploy notifications to a Telegram channel.
- **Monitoring alerts**: Forward Grafana/PagerDuty alerts to a Telegram channel.
- **Cron job status**: Simple `curl` to the Telegram API at the end of cron jobs.

Pattern: Create one channel per project/environment, add relevant bots, use chat folders to organize.

### 8. Telegram Premium for Developer Productivity

Relevant Premium features:

- **4GB file uploads** (vs 2GB free) — useful for large artifacts.
- **Faster downloads** with priority.
- **20 chat folders** (vs 10) — better organization.
- **Voice-to-text transcription** — transcribe voice messages sent to the bot.
- **No ads** in public channels.
- **Custom emoji** in messages and folder names — visual categorization.

### 9. Custom Bot Commands Menu

Set up a command menu via BotFather so users see available commands when typing `/`:

```
/status - Show agent and bead status
/list - List running agents
/launch - Launch a new agent
/quiet - Toggle quiet mode
/help - Show available commands
```

This provides discoverability without remembering dot commands.

### 10. Notification Sound Customization

Set a custom notification sound for the sase bot chat:

- Open chat info -> Notifications -> Custom sound.
- Use a distinct sound so you can tell sase notifications apart from regular messages without looking at the phone.
- Or mute the chat and rely on silent notifications with badge counts.

---

## Part 3: MTProto / User-Client Possibilities

For advanced automation beyond what the Bot API supports, Telethon or Pyrogram provide MTProto access.

### When MTProto Makes Sense

| Capability             | Bot API          | MTProto     |
| ---------------------- | ---------------- | ----------- |
| Send/receive messages  | Yes              | Yes         |
| Read chat history      | No               | Yes         |
| Download files > 20MB  | No (50MB upload) | Yes (2-4GB) |
| Deletion notifications | No               | Yes         |
| Act as user account    | No               | Yes         |
| Join groups/channels   | No               | Yes         |
| Search messages        | Limited          | Full        |

### Potential Use Cases for sase

1. **Chat history search**: Query past agent outputs or notifications by keyword. Useful for "what did that agent say
   last week about the auth bug?"
2. **Message archival**: Automatically archive all bot conversations to local storage for offline reference.
3. **Cross-chat monitoring**: Watch specific channels/groups for keywords (e.g., incident alerts) and auto-launch
   agents.
4. **Large file transfers**: Send/receive files up to 2-4GB via MTProto without a local Bot API server.

### Caveats

- Requires separate credentials (`api_id` + `api_hash` from my.telegram.org, plus phone auth for user accounts).
- User-account automation has ToS implications — Telegram may ban accounts that automate too aggressively.
- More complex setup than the Bot API.
- Probably overkill unless a specific Bot API limitation is blocking a workflow.

---

## Priority Ranking

Ranked by impact-to-effort ratio:

| #   | Improvement                    | Impact                        | Effort      | Priority      |
| --- | ------------------------------ | ----------------------------- | ----------- | ------------- |
| 1   | telegramify-markdown           | High (fixes formatting pain)  | Low         | **Do first**  |
| 2   | Expandable blockquotes         | High (better long content UX) | Low         | **Do first**  |
| 3   | Copy text buttons              | Medium (better UX)            | Very low    | **Quick win** |
| 4   | More dot commands              | Medium (better control)       | Low         | **Quick win** |
| 5   | Message effects                | Low (polish)                  | Very low    | **Quick win** |
| 6   | Forum topics                   | High (threading)              | Medium-high | **Plan next** |
| 7   | Streaming (sendMessageDraft)   | High (real-time output)       | Medium      | **Plan next** |
| 8   | Native checklists              | Medium (better plan review)   | Medium      | **Plan next** |
| 9   | Reply-to-context agent launch  | Medium (better UX)            | Low         | **Plan next** |
| 10  | Quick-launch follow-up buttons | Medium (better UX)            | Low         | **Plan next** |
| 11  | Reaction-based responses       | Medium (faster mobile UX)     | Medium      | **Later**     |
| 12  | Inline mode                    | Medium (cross-chat access)    | Medium      | **Later**     |
| 13  | Voice message transcription    | Medium (mobile UX)            | Medium      | **Later**     |
| 14  | Mini App dashboard             | High (rich mobile UI)         | High        | **Later**     |
| 15  | Local Bot API server           | Low (niche file size need)    | Medium      | **If needed** |
| 16  | MTProto integration            | Low (niche use cases)         | High        | **If needed** |

---

## Sources

- [Telegram Bot API Changelog](https://core.telegram.org/bots/api-changelog)
- [Telegram Bot API Documentation](https://core.telegram.org/bots/api)
- [Telegram Mini Apps Documentation](https://core.telegram.org/bots/webapps)
- [telegramify-markdown (GitHub)](https://github.com/sudoskys/telegramify-markdown)
- [python-telegram-bot Documentation](https://docs.python-telegram-bot.org/)
- [Telethon Documentation](https://docs.telethon.dev/)
- [Pyrogram: MTProto vs Bot API](https://docs.pyrogram.org/topics/mtproto-vs-botapi)
- [Telegram Desktop Keyboard Shortcuts](https://blog.invitemember.com/2024-telegram-desktop-shortcuts-effortless-efficiency/)
- [Telegram Bot Features](https://core.telegram.org/bots/features)
- [appleboy/telegram-action (GitHub Actions)](https://github.com/appleboy/telegram-action)
