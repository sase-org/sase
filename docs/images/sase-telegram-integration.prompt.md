---
pdf: false
---

# SASE Telegram Integration Prompt

## Target

- Document: `docs/architecture.md` / `docs/index.md`
- Image: `docs/images/sase-telegram-integration.png`
- Alt text: "SASE Telegram integration showing outbound notifications, inbound callbacks
  and commands, bridge files, shared Telegram state, and the separate sase-telegram
  package boundary"

## Final GPT Image Prompt

Use case: infographic-diagram

Asset type: documentation architecture diagram PNG for
`docs/images/sase-telegram-integration.png`

Primary request: Create a polished 16:9 landscape architecture infographic titled
`SASE Telegram Integration` showing the Telegram bridge between SASE core, the separate
`../sase-telegram` package, and Telegram. Use a light neutral background with crisp
blocks, clear arrows, readable short labels, and distinct accent colors. Avoid
decorative gradients, fake screenshots with dense tiny text, and paragraph-length raster
text.

Layout:

- Three vertical zones from left to right: `SASE core`, `../sase-telegram`, and
  `Telegram`.
- Put a clear vertical process boundary between SASE core and `../sase-telegram`
  labelled `process boundary`.
- In the middle zone show a single AXE scheduler node near the top feeding two
  independent horizontal lanes.
- Top lane: OUTBOUND, labelled `O1` through `O5`, arrow direction left to right,
  subtitle `notifications -> Telegram`.
- Bottom lane: INBOUND, labelled `I1` through `I4`, arrow direction right to left,
  subtitle `Telegram -> SASE`.
- Place a shared state store bar under both lanes, not inside only one lane.
- Right zone should be a clean Telegram chat mock panel with multiple
  notification/action badges, not only a binary approval card.

Required exact labels, keep them large and readable:

- Title: `SASE Telegram Integration`
- Left zone labels: `SASE core`, `~/.sase/notifications/notifications.jsonl`,
  `*.response.json`, `sase run`, `generated images & artifacts`
- Middle header: `../sase-telegram`, `separate package: pip install sase-telegram`
- Boundary label: `process boundary`
- Scheduler label: `AXE scheduler runs chops`
- Outbound lane labels: `O1 sase_chop_tg_outbound`, `O2 read notifications.jsonl`,
  `O3 HWM/read/rate-limit gate`, `O4 format Markdown/buttons/attachments`,
  `O5 Telegram Bot API`
- Inbound lane labels: `I1 callbacks/text/photos/docs`, `I2 sase_chop_tg_inbound`,
  `I3 dispatch`, `I4 write response / slash command / launch agent`
- State store labels grouped under `~/.sase/telegram/`:
  `delivery: rate_limit.json, last_sent_ts, outbound.lock, outbound_debug.log`;
  `inbound: update_offset.txt, pending_actions.json, awaiting_feedback.json`;
  `attachments: images/, commands_registered_ts, project_context.json`
- Telegram badges: `Plan Approval`, `HITL`, `Question`, `Workflow Complete`,
  `Agent Launched`, `Agent Killed`, `Error Digest`, `Image Generated`
- Telegram command badges: `/list`, `/kill`, `/resume`, `/changes`, `/xprompts`,
  `/bead`, `/update`
- Plan approval buttons: `Tale`, `Approve`, `Epic`, `Reject`, `Feedback`
- Footnote near launch arrow:
  `Launch disabled when SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED is set`

Accuracy constraints:

- AXE feeds both outbound and inbound lanes.
- O3 filters by high-water mark, read state, silent flag, and rate limit.
- Generated images and artifacts feed O4 and then Telegram `sendPhoto` / `sendDocument`.
- Cross-boundary arrows are labelled with `notifications.jsonl`, `*.response.json`, and
  `sase run subprocess`.
- Do not write `notifications.json`, `last_send_ts`, `mailing_inbox.json`, or
  `Telegrams Bot API`.

Style: match modern technical documentation infographics: flat vector-like blocks, soft
shadows, restrained color, high contrast text, generous spacing, clean arrows, no
one-hue palette. Use 16:9 composition.

## Post-Processing Notes

The checked-in PNG was generated with GPT image generation from the prompt above. It is
1672x941 to match the prior asset dimensions. A small ImageMagick relabel pass corrected
the `../sase-telegram` header and the `last_sent_ts` state file label.

The final image addresses the critique by separating the outbound and inbound flows,
showing the SASE core to `../sase-telegram` process boundary, naming the bridge files,
moving the shared state store under both lanes, and showing Telegram notification types,
slash commands, plan buttons, attachments, and the launch-disabled mode.
