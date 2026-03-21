# SMS Integration for Sase: Twilio and Alternatives

Research into adding SMS (text messaging) capabilities to sase, enabling bidirectional text communication between the
user and sase agents via the heartbeats lumberjack.

## How It Would Work in Sase

### The Heartbeats Lumberjack

The `sase_athena.yml` config defines a `heartbeats` lumberjack with a 60-second interval. It currently runs the
`pylimit_split` xprompt chop every 60 seconds. Adding SMS support would mean adding a new chop (or set of chops) to this
lumberjack that:

1. **Outbound (sase → phone)**: Polls the sase notification store (`~/.sase/notifications/notifications.jsonl`) for
   unread notifications and forwards them as SMS messages to the user's phone.
2. **Inbound (phone → sase)**: Polls an SMS provider's API for new incoming messages and injects them into sase as
   notifications, HITL responses, or direct agent commands.

### Integration Points

Sase already has the infrastructure needed:

- **Notification system** (`sase.notifications.senders`): 6 sender functions that create `Notification` objects and
  append them to JSONL storage. A new `notify_via_sms()` sender could be added.
- **Chop script pattern** (`sase.scripts.sase_chop_*.py`): Discoverable scripts that receive serialized context via
  `--context` and run periodically.
- **HITL (Human-in-the-Loop)** actions: The notification model already supports `action="HITL"` with `action_data` for
  response routing. SMS replies could feed back into this system.
- **Runner pool**: Cross-process coordination already prevents resource contention between lumberjack chops.

### Proposed Architecture

```
┌──────────────────────┐         ┌─────────────────┐
│  heartbeats          │         │  SMS Provider    │
│  lumberjack (60s)    │         │  (Twilio, etc.)  │
│                      │         │                  │
│  ┌────────────────┐  │  send   │                  │
│  │ sms_outbound   │──┼────────>│  ──> user phone  │
│  │ chop           │  │         │                  │
│  └────────────────┘  │         │                  │
│                      │         │                  │
│  ┌────────────────┐  │  poll   │                  │
│  │ sms_inbound    │<─┼────────>│  <── user phone  │
│  │ chop           │  │         │                  │
│  └────────────────┘  │         │                  │
└──────────────────────┘         └─────────────────┘
         │                                │
         v                                │
  ~/.sase/notifications/            REST API calls
  notifications.jsonl               (no webhook server
                                     needed)
```

**Key design choice**: Use **API polling** for inbound messages rather than webhooks. This avoids needing to run a
publicly-accessible HTTP server, which would be a significant infrastructure burden for a developer tool. The 60-second
heartbeat interval is a natural fit for polling — the user sends a text, and within 60 seconds sase picks it up.

---

## Twilio

### Overview

Twilio is the dominant player in programmable SMS. Mature Python SDK (`twilio-python`), extensive docs, huge community.
It's the "safe" choice.

### Pricing Breakdown (US, as of early 2026)

| Cost Component                   | Amount                                 |
| -------------------------------- | -------------------------------------- |
| **Per SMS sent (outbound)**      | $0.0079–$0.0083/segment                |
| **Per SMS received (inbound)**   | $0.0079–$0.0083/segment                |
| **Local phone number**           | $1.15/month                            |
| **Toll-free phone number**       | $2.15/month                            |
| **Failed message fee**           | $0.001/message                         |
| **Carrier surcharges**           | $0.003–$0.0065/msg (varies by carrier) |
| **A2P 10DLC brand registration** | $4 one-time                            |
| **A2P 10DLC campaign vetting**   | $15 one-time                           |
| **A2P 10DLC campaign monthly**   | $2/month                               |

**Volume discounts** kick in above 150K messages/month (irrelevant for personal use).

#### Estimated Monthly Cost (Personal Use)

For a single user sending/receiving ~100 texts/month:

```
Phone number:         $1.15
A2P campaign:         $2.00
100 outbound SMS:     $0.83  (at $0.0083/msg)
100 inbound SMS:      $0.83
Carrier surcharges:   ~$0.40 (avg $0.004/msg × 100)
─────────────────────────────
Total:                ~$5.21/month
```

One-time setup: ~$19 (brand registration $4 + campaign vetting $15).

### A2P 10DLC Registration (Required)

US carriers now require Application-to-Person (A2P) registration for SMS sent from 10-digit long codes. This is
unavoidable with any provider, not just Twilio.

**Sole Proprietor registration** (for personal/individual use):

- Must verify identity with OTP sent to a personal US/Canadian mobile number (not a VoIP number)
- One phone number per campaign
- Limited throughput (adequate for personal use)
- Process takes a few days for approval

### Code Complexity

Sending an SMS with Twilio is ~5 lines of Python:

```python
from twilio.rest import Client

client = Client(account_sid, auth_token)
message = client.messages.create(
    body="Agent completed task X",
    from_="+1TWILIO_NUMBER",
    to="+1YOUR_NUMBER",
)
```

Reading incoming messages (polling approach):

```python
messages = client.messages.list(
    to="+1TWILIO_NUMBER",
    date_sent_after=last_poll_time,
)
for msg in messages:
    if msg.direction == "inbound":
        process_incoming(msg.body)
```

### Pros

- Most mature SMS API; best docs and community support
- First-class Python SDK
- Huge ecosystem of examples and integrations
- Reliable delivery infrastructure
- Free trial credits ($15) for prototyping

### Cons

- **Most expensive** per-message of the major providers
- Pricing is complex (base + carrier surcharges + registration fees)
- A2P 10DLC registration is bureaucratic
- Overkill for personal/low-volume use
- Monthly costs add up even when idle ($3.15/month minimum)

---

## Alternatives to Twilio

### Telnyx

**Best alternative for developers.** Owns its own telecom network end-to-end, resulting in lower latency and lower
costs.

| Cost Component            | Amount                                |
| ------------------------- | ------------------------------------- |
| **Per SMS sent/received** | $0.004/segment                        |
| **Local phone number**    | ~$1.00/month + $0.10/month SMS add-on |
| **A2P 10DLC fees**        | Same carrier-mandated fees apply      |

**Estimated monthly cost** (~100 msgs): **~$3.20/month** (roughly 40% cheaper than Twilio).

- Python SDK available
- "Twexit API" for easy migration from Twilio (minimal code changes)
- Pay-as-you-go, no minimums
- Good developer docs

**Verdict**: Strong choice if cost matters. Similar DX to Twilio.

### Plivo

**Best budget option.** Known for aggressive pricing.

| Cost Component                 | Amount                  |
| ------------------------------ | ----------------------- |
| **Per SMS sent (outbound)**    | $0.0045–$0.0055/segment |
| **Per SMS received (inbound)** | Free (local numbers)    |
| **Local phone number**         | ~$0.80/month            |

**Estimated monthly cost** (~100 msgs): **~$2.35/month** (free inbound is a big win for this use case).

- Python SDK available
- 190+ country coverage
- Good fraud prevention
- Smaller community than Twilio

**Verdict**: Cheapest option. Free inbound is ideal for a polling-based design.

### Vonage (formerly Nexmo)

| Cost Component         | Amount            |
| ---------------------- | ----------------- |
| **Per SMS sent**       | $0.00809/segment  |
| **Local phone number** | Varies by country |

- Python SDK (recently modernized, v4.x)
- 1,600 carrier network
- Similar pricing to Twilio (not much savings)

**Verdict**: No compelling advantage over Twilio for this use case.

### Bird (formerly MessageBird)

- SmartRouting technology (doesn't use aggregators)
- Free tier available, paid plans from $45/month for 30K messages
- Good if you also want WhatsApp/email in the future

**Verdict**: Interesting for multi-channel, but paid tier is expensive for low-volume personal use.

---

## Provider Comparison Summary

| Factor              | Twilio    | Telnyx  | Plivo  | Vonage   |
| ------------------- | --------- | ------- | ------ | -------- |
| **Per-msg (out)**   | $0.0083   | $0.004  | $0.005 | $0.008   |
| **Per-msg (in)**    | $0.0083   | $0.004  | Free   | ~$0.008  |
| **Phone # / month** | $1.15     | ~$1.10  | ~$0.80 | ~$1.00   |
| **Python SDK**      | Excellent | Good    | Good   | Good     |
| **Docs quality**    | Best      | Good    | Good   | Adequate |
| **Community size**  | Largest   | Growing | Medium | Medium   |
| **Est. monthly**    | ~$5.21    | ~$3.20  | ~$2.35 | ~$5.00   |

---

## Design Decisions Needed

### 1. Which SMS provider?

**Recommendation**: Start with **Twilio** for prototyping (free trial credits), then consider **Telnyx** or **Plivo**
for production if cost matters.

Alternatively, build a provider-agnostic abstraction layer from the start (see decision #4).

### 2. What should trigger outbound SMS?

Options:

- **All unread notifications** — every notification in the JSONL store gets texted. Simple but potentially noisy.
- **Filtered notifications** — only certain senders/actions (e.g., HITL requests, error digests, workflow completions).
  More useful.
- **Explicit opt-in** — a new `sms=True` flag on the `Notification` model that senders set when a notification is
  SMS-worthy. Most flexible.

**Recommendation**: Start with filtered notifications (HITL + errors), add the explicit flag later.

### 3. How should inbound SMS be handled?

Options:

- **HITL response routing** — If there's a pending HITL request, treat the incoming text as the HITL response. This is
  the highest-value use case.
- **Agent command injection** — Parse the text as a command (e.g., "approve", "reject", "status"). Limited but useful.
- **Free-form prompt relay** — Forward the text body directly to the active agent as a user message. Most powerful but
  requires careful session routing.

**Recommendation**: Start with HITL response routing + simple commands ("approve", "reject", "status"). Free-form relay
is a future enhancement.

### 4. Provider abstraction layer?

Options:

- **Direct SDK integration** — Just call Twilio's SDK directly in the chop script. Simplest, fastest to implement.
- **Thin abstraction** — A `SmsSender` protocol with `send()` and `poll_incoming()` methods, with a `TwilioSender`
  implementation. Easy to swap providers later.
- **Plugin system** — SMS provider as a sase plugin (like sase-github). Most flexible but heaviest.

**Recommendation**: Thin abstraction. It's ~20 extra lines of code and makes provider switching trivial.

### 5. Where should credentials live?

Options:

- **Environment variables** — `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`. Standard Twilio
  convention.
- **sase config** — In `sase.yml` under a new `sms:` section.
- **Both** — Config file for phone numbers and preferences, env vars for secrets.

**Recommendation**: Env vars for secrets (SID, auth token), sase config for everything else (phone numbers, which
notifications to forward, provider choice).

### 6. Rate limiting and quiet hours?

Should outbound SMS respect quiet hours (e.g., no texts between 11pm–7am)? Should there be a max messages/hour cap to
prevent runaway costs from a bug?

**Recommendation**: Yes to both. Defaults in `default_config.yml`, overridable in user config.

---

## Implementation Effort Estimate

### Phase 1: Outbound SMS (~2-4 hours)

- New chop script: `sase_chop_sms_outbound.py`
- Provider abstraction: `sase/sms/provider.py` + `sase/sms/twilio_provider.py`
- Config additions: `sms:` section in sase config schema
- Filter logic: which notifications get texted
- Add chop to heartbeats lumberjack config

### Phase 2: Inbound SMS polling (~2-4 hours)

- New chop script: `sase_chop_sms_inbound.py`
- Polling logic: track last-seen message timestamp
- HITL response routing: match incoming SMS to pending HITL requests
- Simple command parsing ("approve", "reject", "status")

### Phase 3: Polish (~1-2 hours)

- Quiet hours and rate limiting
- SMS delivery status tracking
- Error handling and retry logic
- Config validation
- Tests

**Total estimate: ~5-10 hours of implementation work.**

### External Setup (One-Time, ~30 minutes)

1. Create account with chosen provider
2. Purchase a phone number
3. Complete A2P 10DLC registration (sole proprietor)
4. Set environment variables
5. Wait for A2P approval (1-3 business days)

---

## Risks and Considerations

- **A2P registration wait time**: Carrier approval takes 1-3 business days. You can't send SMS from a 10DLC number until
  approved. Toll-free numbers are an alternative but cost more.
- **Carrier filtering**: Even registered messages can be filtered by carriers if content looks spammy. Keep messages
  concise and informational.
- **Cost creep**: A bug in the outbound chop could send hundreds of messages before detection. Rate limiting is
  essential.
- **SMS segment limits**: Messages over 160 characters are split into multiple segments, each billed separately. Keep
  notifications brief.
- **Polling latency**: With a 60-second heartbeat interval, inbound messages have up to 60 seconds of latency. This is
  acceptable for the use case but worth noting.
- **Two-way conversation state**: If you want true back-and-forth conversations over SMS, you need session tracking.
  This is a significant complexity increase beyond simple command/response.

---

## Sources

- [Twilio SMS Pricing (US)](https://www.twilio.com/en-us/sms/pricing/us)
- [Twilio Messaging Pricing](https://www.twilio.com/en-us/pricing/messaging)
- [Twilio A2P 10DLC Sole Proprietor Registration](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/direct-sole-proprietor-registration-overview)
- [Twilio A2P 10DLC Fees](https://help.twilio.com/articles/1260803965530-What-pricing-and-fees-are-associated-with-the-A2P-10DLC-service-)
- [Twilio Python Quickstart](https://www.twilio.com/docs/messaging/quickstart)
- [Twilio Messages API (for polling)](https://www.twilio.com/docs/messaging/api/message-resource)
- [Is Twilio's Pricing Justified? (2026 review)](https://emitrr.com/blog/twilio-pricing/)
- [Telnyx vs Twilio SMS Comparison](https://telnyx.com/resources/telnyx-vs-twilio-sms)
- [Telnyx SMS Pricing](https://telnyx.com/pricing/messaging)
- [Plivo vs Twilio Pricing Comparison](https://www.plivo.com/blog/twilio-alternative-comparison/)
- [Plivo as Twilio Alternative](https://www.plivo.com/twilio-alternative/)
- [Top Twilio Competitors (Prelude)](https://prelude.so/blog/twilio-competitors)
- [5 Best Twilio Alternatives (Textellent)](https://textellent.com/blog/twilio-alternatives/)
- [Top Twilio Alternatives (GetVoIP)](https://getvoip.com/blog/twilio-alternatives/)
