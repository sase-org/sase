# Telegram Integration for Sase: Agent-to-User Messaging

Research into using the Telegram Bot API for bidirectional messaging between sase agents and the user, via the
heartbeats lumberjack. Also covers alternatives to Telegram and trade-offs.

## How It Would Work in Sase

### The Heartbeats Lumberjack

The `sase_athena.yml` config defines a `heartbeats` lumberjack with a 60-second interval. Adding Telegram support means
adding new chops to this lumberjack:

1. **Outbound (sase -> Telegram)**: Polls `~/.sase/notifications/notifications.jsonl` for unread notifications and
   forwards them as Telegram messages to the user.
2. **Inbound (Telegram -> sase)**: Polls the Telegram Bot API for incoming messages and injects them into sase as
   notifications, HITL responses, or agent commands.

This is the same architectural pattern described in the [Twilio SMS research](../texts/twilio_sms_integration.md), but
with Telegram replacing SMS as the transport.

### Architecture Diagram

```
+----------------------+         +-----------------+
|  heartbeats          |         |  Telegram Bot   |
|  lumberjack (60s)    |         |  API            |
|                      |         |                 |
|  +----------------+  |  send   |                 |
|  | tg_outbound    |--+-------->|  --> user app   |
|  | chop           |  |         |                 |
|  +----------------+  |         |                 |
|                      |         |                 |
|  +----------------+  |  poll   |                 |
|  | tg_inbound     |<-+-------->|  <-- user app   |
|  | chop           |  |         |                 |
|  +----------------+  |         |                 |
+----------------------+         +-----------------+
         |                                |
         v                                |
  ~/.sase/notifications/            HTTP API calls
  notifications.jsonl               (long polling,
                                     no webhook
                                     server needed)
```

**Key design choice**: Use **long polling** (`getUpdates`) for inbound messages rather than webhooks. This avoids
running a publicly-accessible HTTP server. The Telegram API holds the connection open until an update arrives or a
timeout occurs, which is more efficient than repeatedly polling an empty endpoint. The 60-second heartbeat interval
naturally fits this pattern.

### Integration Points

Same as the Twilio design — sase already has the infrastructure:

- **Notification system** (`sase.notifications.senders`): Outbound chop reads notifications from JSONL store.
- **Chop script pattern** (`sase.scripts.sase_chop_*.py`): Discoverable scripts that receive serialized context.
- **HITL actions**: The notification model supports `action="HITL"` for response routing.
- **Runner pool**: Cross-process coordination prevents resource contention.

---

## Telegram Bot API Overview

### How It Works

Bots are special Telegram accounts controlled by your code. They communicate through Telegram's HTTP-based Bot API (you
never deal with the underlying MTProto protocol). Bots are created via the [@BotFather](https://t.me/BotFather) bot
inside Telegram itself.

**Core flow**:

1. User sends `/start` to your bot (one-time) — this creates a chat and gives you their `chat_id`.
2. Your code calls `sendMessage` with that `chat_id` to push messages to the user.
3. Your code calls `getUpdates` (long polling) to receive messages from the user.

### Cost

**The Telegram Bot API is completely free.** No per-message fees, no monthly subscription, no API call charges.

Compare this to SMS:

|                              | Telegram | Twilio SMS    | Telnyx SMS    | Plivo SMS     |
| ---------------------------- | -------- | ------------- | ------------- | ------------- |
| **Monthly cost (~100 msgs)** | $0       | ~$5.21        | ~$3.20        | ~$2.35        |
| **Per-message cost**         | $0       | $0.008        | $0.004        | $0.005        |
| **Phone number cost**        | $0       | $1.15/mo      | $1.10/mo      | $0.80/mo      |
| **Registration fees**        | $0       | ~$19 one-time | ~$19 one-time | ~$19 one-time |
| **One-time setup cost**      | $0       | ~$19          | ~$19          | ~$19          |

The only "cost" of Telegram is that the user must have the Telegram app installed.

### Rate Limits

- **30 messages/second** global (across all chats)
- **1 message/second** per individual chat
- **20 messages/minute** per group chat

These limits are far more generous than needed for agent-to-user messaging.

### Bot Setup (One-Time, ~5 Minutes)

1. Open Telegram, search for **@BotFather** (verify the blue checkmark)
2. Send `/newbot`
3. Choose a display name (e.g., "Sase Agent Bot")
4. Choose a username (must end in `bot`, e.g., `sase_agent_bot`)
5. BotFather replies with your **API token** (format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)
6. Store the token as an environment variable
7. Send `/start` to the bot from your personal Telegram account — this generates your `chat_id`

No phone number purchase, no carrier registration, no approval wait. Compare to Twilio's 30+ minute setup plus 1-3
business days for A2P approval.

### Python Libraries

| Library                 | Stars | Paradigm        | Best For                                              |
| ----------------------- | ----- | --------------- | ----------------------------------------------------- |
| **python-telegram-bot** | ~28K  | Async (v20+)    | General purpose, best docs, largest community         |
| **aiogram**             | ~5K   | Fully async     | High-performance, built-in FSM for conversation flows |
| **Telethon**            | ~10K  | Async (MTProto) | User-account automation (overkill for bots)           |
| **pyTelegramBotAPI**    | ~8K   | Sync + async    | Quick prototyping, less boilerplate                   |

**Recommendation for sase**: **python-telegram-bot** (PTB). Best documentation, largest community, fully async, wraps
the entire Bot API. If conversational state machines become important later, **aiogram** has a slightly better built-in
FSM.

Alternatively, the raw HTTP API is simple enough to call with just `httpx`/`requests` — sending a message is a single
POST request. This avoids adding a dependency.

### Code Examples

**Sending a message (raw HTTP, no library needed)**:

```python
import httpx

async def send_telegram(token: str, chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    await httpx.AsyncClient().post(url, json={"chat_id": chat_id, "text": text})
```

**Sending a message (python-telegram-bot)**:

```python
from telegram import Bot

bot = Bot(token=TOKEN)
await bot.send_message(chat_id=CHAT_ID, text="Agent completed task X")
```

**Polling for incoming messages (raw HTTP)**:

```python
async def poll_telegram(token: str, offset: int = 0) -> list[dict]:
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    resp = await httpx.AsyncClient().get(url, params={"offset": offset, "timeout": 30})
    return resp.json().get("result", [])
```

**Rich content** — unlike SMS, Telegram supports:

- Markdown/HTML formatting in messages
- Inline keyboards (buttons the user can tap)
- File/image attachments
- Message editing and deletion
- Reply threading

### Security Considerations

- **No E2E encryption for bots**: Bot conversations use client-server encryption only. Telegram's servers can read bot
  messages. This is the same as SMS (carriers can read messages) but worse than Signal.
- **Token security**: The bot token is equivalent to a password. Store in env vars, never commit to version control. If
  compromised, revoke immediately via `/revoke` in BotFather.
- **Data on Telegram servers**: Telegram stores cloud chat messages on its servers. If messages contain sensitive agent
  data (error traces, file paths, credentials), this is a concern.
- **Privacy mode in groups**: Bots in groups only see commands directed at them by default. For 1:1 agent-to-user
  messaging this is irrelevant.
- **Practical risk**: For agent notifications like "task completed", "HITL request pending", "error digest" — the
  security profile is more than adequate. Sensitive data (credentials, secrets) should never be in notifications
  regardless of transport.

---

## Advantages of Telegram Over SMS

| Factor                       | Telegram                           | SMS                                 |
| ---------------------------- | ---------------------------------- | ----------------------------------- |
| **Cost**                     | Free forever                       | $2-5/month ongoing + per-message    |
| **Setup time**               | 5 minutes                          | 30+ minutes + 1-3 days A2P approval |
| **Message length**           | ~4096 chars, markdown              | 160 chars/segment, plain text       |
| **Rich content**             | Buttons, images, files, formatting | Plain text only                     |
| **Delivery reliability**     | Excellent (internet-based)         | Carrier-dependent, filtering risk   |
| **Two-way latency**          | Near-instant (long polling)        | Up to 60s (API polling)             |
| **Registration bureaucracy** | None                               | A2P 10DLC required                  |
| **Carrier dependencies**     | None                               | Carrier surcharges, filtering       |

### Disadvantages of Telegram vs SMS

| Factor                     | Telegram                    | SMS                                     |
| -------------------------- | --------------------------- | --------------------------------------- |
| **App required**           | Yes (must install Telegram) | No (works on every phone)               |
| **Universality**           | ~900M users                 | Every phone in the world                |
| **Works without internet** | No (needs data/wifi)        | Yes (cellular network)                  |
| **E2E encryption**         | Not for bots                | Not for SMS either (both are weak here) |

---

## Alternatives to Telegram

### Discord

**Best for**: Users already on Discord who want a free, two-way messaging solution.

- **Cost**: Free
- **Setup**: Moderate (developer portal, OAuth intents, bot must share a server with user for DMs)
- **Two-way**: Yes, full DM support
- **Python library**: discord.py (~15K stars, mature, async)
- **Rate limits**: 50 req/sec global, 5 msg/5sec/channel
- **Privacy**: Low (Discord sees all, no E2E)
- **Mobile app**: Excellent
- **Downside**: Requires user to use Discord. DMs require sharing a server. More community-oriented than 1:1 agent
  notifications. Heavier client than Telegram for this purpose.

### Slack

**Best for**: Teams already using Slack.

- **Cost**: Free plan has 90-day message history and max 10 app integrations. Pro: $7.25/user/month.
- **Setup**: Moderate-high (app dashboard, OAuth scopes, workspace install)
- **Two-way**: Yes
- **Python library**: slack-sdk + Bolt (official, maintained by Slack)
- **Rate limits**: Tier-based, 30K events/workspace/hour
- **Privacy**: Low (Slack sees all)
- **Mobile app**: Excellent
- **Downside**: Free plan limitations make it impractical. Designed for team collaboration, not personal agent
  notifications. Cost adds up quickly.

### Signal

**Best for**: Users who prioritize privacy above all else.

- **Cost**: Free
- **Setup**: **Very high**. No official Bot API. Relies on signal-cli (unofficial Java CLI that reverse-engineers
  Signal's protocol). Requires dedicated phone number, CAPTCHA registration, Java runtime, and ongoing maintenance
  (signal-cli must be updated every ~3 months or it stops working).
- **Two-way**: Yes, when it works
- **Python library**: signalbot, pysignald — all wrappers around signal-cli. None are mature or well-maintained.
- **Privacy**: Best-in-class (full E2E encryption via Signal Protocol)
- **Mobile app**: Excellent
- **Downside**: No official API = fragile. signal-cli can break with any Signal server update. CAPTCHA registration is
  finicky. **Not recommended for production automation.**

### Matrix / Element

**Best for**: Privacy-conscious users willing to self-host.

- **Cost**: Free (self-hosted). Managed hosting ~$5-20/month.
- **Setup**: High for self-hosting (Synapse server, domain, TLS). Low if using matrix.org public homeserver.
- **Two-way**: Yes, bots are first-class citizens
- **Python library**: matrix-nio (async, well-maintained), simplematrixbotlib
- **Privacy**: Excellent (E2E encryption available, full data sovereignty if self-hosted)
- **Mobile app**: Element is decent but not as polished as Telegram
- **Downside**: Self-hosting is a significant infrastructure commitment. Smaller user base.

### WhatsApp Business API

**Best for**: Nobody in this use case.

- **Cost**: Per-message pricing ($0.004-0.14/msg depending on category). Plus BSP fees.
- **Setup**: Very high (Meta Business Manager, business verification taking days-weeks, dedicated phone number, webhook
  server)
- **Two-way**: Yes, but business-initiated messages require pre-approved templates
- **Privacy**: E2E encrypted, but Meta collects metadata
- **Downside**: Designed for business-to-customer communication. Complex setup, ongoing costs, template approval
  process. Massive overkill.

### Push Notification Services (ntfy, Pushover, Gotify)

**Best for**: One-way notifications where the user never needs to reply.

| Service      | Cost                    | Self-Host                 | Two-Way | Setup                            |
| ------------ | ----------------------- | ------------------------- | ------- | -------------------------------- |
| **ntfy**     | Free (250/day hosted)   | Excellent (single binary) | No      | Extremely low (single HTTP POST) |
| **Pushover** | $4.99 one-time/platform | No                        | No      | Very low                         |
| **Gotify**   | Free                    | Required (no hosted)      | No      | Low-moderate                     |

**Key limitation**: All three are **one-way only**. The user cannot reply to a notification. This rules them out for
HITL responses and interactive agent communication — which is the highest-value use case.

ntfy is excellent as a supplement (e.g., urgent alerts) but cannot replace a two-way messaging channel.

### Email (SMTP/IMAP)

**Best for**: Fallback or low-priority digest notifications.

- **Cost**: Free with existing email accounts
- **Setup**: Low for sending (smtplib is in Python stdlib), moderate for receiving (IMAP polling)
- **Two-way**: Yes, but slow (email isn't instant, replies may land in spam, parsing threads is fragile)
- **Privacy**: Poor (unencrypted by default)
- **Downside**: High latency, spam filtering risk, not suited for interactive back-and-forth.

---

## Comparison Summary

| Platform       | Cost             | Setup           | Two-Way       | Privacy   | Best For                              |
| -------------- | ---------------- | --------------- | ------------- | --------- | ------------------------------------- |
| **Telegram**   | Free             | 5 min           | Yes           | Moderate  | **Best overall for this use case**    |
| **Discord**    | Free             | 15 min          | Yes           | Low       | Users already on Discord              |
| **Slack**      | $7.25/mo+        | 30 min          | Yes           | Low       | Teams already on Slack                |
| **Signal**     | Free             | Hours + ongoing | Yes (fragile) | Best      | Privacy maximalists (not recommended) |
| **Matrix**     | Free (self-host) | Hours           | Yes           | Excellent | Self-hosters wanting data sovereignty |
| **WhatsApp**   | Per-message      | Days            | Yes (limited) | Moderate  | Nobody (overkill)                     |
| **SMS/Twilio** | $3-5/mo          | 30 min + days   | Yes           | Poor      | Universality (no app install)         |
| **ntfy**       | Free             | 1 min           | **No**        | Good      | One-way alerts only                   |
| **Email**      | Free             | 10 min          | Yes (slow)    | Poor      | Low-priority digests                  |

---

## Design Decisions Needed

### 1. Telegram or something else?

Telegram is the recommended choice. It is free, trivial to set up, has excellent Python libraries, supports two-way
messaging, and the polling-based approach maps directly onto the heartbeats lumberjack architecture.

The only reasons to choose something else:

- **You refuse to install Telegram** -> SMS (Twilio/Telnyx) or ntfy for one-way.
- **You need E2E encryption** -> Matrix (self-hosted). Signal is technically possible but fragile.
- **You already use Discord heavily** -> Discord is comparable.

### 2. Library or raw HTTP?

Options:

- **Raw `httpx` calls**: No new dependency. The Telegram Bot API is simple enough (`sendMessage`, `getUpdates`) that a
  thin wrapper of ~30 lines covers the needs. Keeps the dependency footprint small.
- **python-telegram-bot**: Full-featured, well-maintained. Better for complex interactions (inline keyboards,
  conversation handlers, middleware). Adds a dependency.

**Recommendation**: Start with raw `httpx` calls. The outbound/inbound chop scripts only need `sendMessage` and
`getUpdates`. If the integration grows to include inline keyboards, conversation flows, or other advanced features,
migrate to PTB later.

### 3. What should trigger outbound messages?

Same options as the Twilio research:

- **All unread notifications** — potentially noisy.
- **Filtered by sender/action** — HITL requests, error digests, workflow completions. More practical.
- **Explicit opt-in flag** — `telegram=True` on the Notification model. Most flexible.

**Recommendation**: Start with filtered (HITL + errors). Same recommendation as the Twilio doc.

### 4. How should inbound messages be handled?

- **HITL response routing** — If a HITL request is pending, treat incoming text as the response. Highest value.
- **Command parsing** — "approve", "reject", "status". Simple and useful.
- **Inline keyboard buttons** — Telegram-specific: send HITL requests with "Approve" / "Reject" buttons that the user
  taps. Much better UX than typing a response. This is a significant advantage over SMS.
- **Free-form prompt relay** — Forward text to the active agent. Powerful but complex.

**Recommendation**: Start with HITL routing + inline keyboard buttons (this is where Telegram really shines over SMS).
Add command parsing and free-form relay later.

### 5. Credential storage?

- **Token**: Environment variable `SASE_TELEGRAM_BOT_TOKEN`
- **Chat ID**: `sase.yml` config under a new `telegram:` section (it's not a secret — it's just a user identifier)

```yaml
# sase.yml
telegram:
  chat_id: 123456789
  notify_on:
    - hitl
    - error_digest
    - workflow_complete
  quiet_hours:
    start: "23:00"
    end: "07:00"
```

### 6. Provider abstraction?

The Twilio research recommended a thin `SmsSender` protocol. For Telegram, the question is whether to build a generic
`MessageTransport` protocol that abstracts over both SMS and Telegram (and potentially Discord, etc.).

Options:

- **Telegram-specific** — Just build the Telegram integration. Simplest.
- **Generic transport protocol** — `MessageTransport` with `send()` and `poll()` methods. Implementations for Telegram,
  SMS, etc. More work up front, but supports multi-channel.

**Recommendation**: Start Telegram-specific. If you later add SMS or Discord, refactor into a transport protocol at that
point. YAGNI until then.

### 7. Rate limiting and quiet hours?

Same recommendation as the Twilio research: yes to both. Even though Telegram is free, quiet hours prevent 3am
notifications, and rate limiting prevents a bug from spamming your phone.

---

## Implementation Effort Estimate

### Phase 1: Outbound Messages (~1-2 hours)

- New chop script: `sase_chop_tg_outbound.py`
- Thin Telegram wrapper: `sase/telegram.py` (~30 lines, `send_message` + `get_updates`)
- Config additions: `telegram:` section in sase config schema
- Filter logic: which notifications get forwarded
- Add chop to heartbeats lumberjack config

### Phase 2: Inbound Messages + HITL (~2-3 hours)

- New chop script: `sase_chop_tg_inbound.py`
- Long polling with offset tracking (persist last `update_id`)
- HITL response routing
- Inline keyboard buttons for approve/reject
- Simple command parsing

### Phase 3: Polish (~1-2 hours)

- Quiet hours and rate limiting
- Message formatting (markdown for notifications)
- Error handling
- Config validation
- Tests

**Total: ~4-7 hours of implementation work.** Less than the SMS estimate because there's no provider abstraction layer,
no carrier registration, and the API is simpler.

### External Setup (One-Time, ~5 Minutes)

1. Create bot via @BotFather
2. Save token to environment variable
3. Send `/start` to bot, note `chat_id`
4. Add `telegram:` section to `sase.yml`

Compare to SMS: ~30 minutes setup + 1-3 business days carrier approval.

---

## Risks and Considerations

- **Telegram account required**: The user must install Telegram and create an account. This is a non-trivial ask for
  someone who doesn't already use it, though Telegram has ~900M users.
- **Internet required**: Unlike SMS, Telegram needs a data connection. Not a concern for a developer tool (you're
  already online), but worth noting.
- **Telegram service dependency**: If Telegram has an outage, messages won't deliver. Telegram's uptime is generally
  excellent, but it's a centralized service you don't control.
- **Bot privacy**: Telegram servers can read bot messages. Don't include sensitive data (credentials, secrets, full
  error traces with sensitive paths) in notifications.
- **Polling latency**: With `getUpdates` long polling and a 60-second heartbeat interval, inbound messages have
  near-instant delivery when the poll is active, but up to 60 seconds in the worst case (if a message arrives right
  after a poll completes). This is acceptable for HITL responses.
- **Token compromise**: If the bot token leaks, anyone can send messages as your bot or read incoming messages. Store it
  securely and rotate if compromised.
- **Telegram ToS**: Telegram's ToS allows bots. There are no restrictions on personal/developer bots. Mass marketing
  bots have restrictions, but those don't apply here.

---

## Recommendation

**Use Telegram.** It is the clear winner for this use case:

- **Free** vs $3-5/month for SMS
- **5-minute setup** vs 30+ minutes + days of carrier approval for SMS
- **Richer UX** (inline keyboards, markdown, attachments) vs 160-char plain text
- **Less implementation work** (~4-7 hours vs ~5-10 hours for SMS with provider abstraction)
- **No external dependencies** beyond Telegram itself (no carrier registration, no phone number purchase)

The only scenario where SMS wins is if you need messaging to work on a phone without Telegram installed and without
internet. For a developer tool where you're already online, this isn't a realistic constraint.

If one-way notifications are sufficient for now, consider **ntfy** as the simplest possible starting point (literally
one HTTP POST), then upgrade to Telegram when two-way messaging becomes needed.

---

## Sources

- [Telegram Bot API Documentation](https://core.telegram.org/bots/api)
- [Telegram Bots Introduction](https://core.telegram.org/bots)
- [Telegram BotFather Tutorial](https://core.telegram.org/bots/tutorial)
- [Telegram Bots FAQ (Rate Limits)](https://core.telegram.org/bots/faq)
- [python-telegram-bot GitHub](https://github.com/python-telegram-bot/python-telegram-bot)
- [aiogram GitHub](https://github.com/aiogram/aiogram)
- [ntfy.sh](https://ntfy.sh/)
- [Pushover API](https://pushover.net/api)
- [Matrix SDKs](https://matrix.org/ecosystem/sdks/)
- [discord.py GitHub](https://github.com/Rapptz/discord.py)
- [Slack Python SDK](https://docs.slack.dev/tools/python-slack-sdk/)
- [Signal-cli GitHub](https://github.com/AsamK/signal-cli)
