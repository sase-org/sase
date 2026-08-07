---
diagram: docs/images/sase-telegram-integration.png
phase: critique
bead: sase-2s.6
pdf: false
---

# Critique: `sase-telegram-integration.png`

This is a one-page infographic showing the end-to-end Telegram bridge: SASE core (left),
the `../sase-telegram` chop service (middle), and the Telegram client (right). The
OUTBOUND lane is a 5-step pipeline (numbered 1–5) and the INBOUND lane continues the
numbering (6–8/9) underneath. A "State store (telegram-state)" strip sits at the bottom
of the middle column and a single Telegram chat mock-up occupies the right column.

## 1. Clarity issues a new user would hit

- **Numbering is one continuous sequence across two independent flows.** The 1→5
  OUTBOUND chain shares numbering with the 6→8/9 INBOUND chain, which suggests a single
  linear pipeline. They are actually two independent triggers (timer-driven outbound,
  poll-driven inbound) that both run from the same `axe` chop scheduler. Restart
  numbering at 1 inside each lane (or use `O1..O5` and `I1..I3`) and label the trigger
  of each lane explicitly.
- **No legend for "AXE lumberjack run chops".** A new user won't know that "AXE" is
  SASE's chop scheduler that periodically invokes named entry points, or that the two
  chops named `tg_outbound` / `tg_inbound` are configured under
  `axe.providers.telegram.chops` in the user's `~/.config/sase/*.yml`. Either drop the
  AXE node and start the lane at "Outbound chop / Inbound chop", or annotate AXE as
  "scheduler — runs chops on an interval (default 5s for telegram)".
- **The `SASE core ↔ ../sase-telegram` boundary is implicit.** The core column lists
  sources (`notifications.jsonl`, response files, agent launcher, generated images) but
  the diagram does not visually mark which arrows cross the process boundary or which
  artifacts are the actual handshake. A vertical "process boundary" rule between the
  SASE-core column and the `../sase-telegram` column, with explicit arrows from
  `notifications.jsonl` → outbound chop and inbound chop → response files / agent
  launcher, would make the contract obvious.
- **The bridge data files are not called out.** A reader cannot tell from the diagram
  that the contract between the two processes is just
  `~/.sase/notifications/notifications.jsonl` (read by outbound) and the
  per-notification `*.response.json` files plus `sase run` subprocess (written/spawned
  by inbound). Naming those bridge artifacts on the connecting arrows would replace the
  current generic "response files" / "agent launcher" boxes with precise hand-off
  points.
- **The state store strip looks like it belongs to OUTBOUND only.** In reality
  `pending_actions.json`, the rate limit, the update offset, and the awaiting-feedback
  file are read/written by both lanes, while only `outbound.lock` and `last_sent_ts` are
  outbound-specific. Move the state store box so it visually sits _below both lanes_ (or
  annotate per-file owners) instead of tucking it under OUTBOUND.
- **The Telegram side shows only one notification type.** The chat mock illustrates a
  Plan Approval card with two buttons. The integration actually delivers eight
  notification types (Plan Approval, HITL Request, User Question, Workflow Complete,
  Agent Launched, Agent Killed, Error Digest, Image Generated) and supports slash
  commands (`/list`, `/kill`, `/resume`, `/changes`, `/xprompts`, `/bead`, `/update`). A
  new user would not realise from this diagram that they can launch agents, run slash
  commands, or receive richer notification kinds. A small badge cluster ("Plan Approval
  · HITL · Question · Workflow Complete · Agent Launched · …") next to the chat mock
  would convey the breadth without re-drawing every card.
- **Step 3 of OUTBOUND is unreadable at the published 1672×941 size.** The third icon's
  caption looks like "Idle check + (something) chops" but the second half is illegible.
  Whatever it actually says, the real step is "Idle gate + rate-limit check + load
  unsent notifications since `last_sent_ts`" — three discrete checks compressed into one
  node. Either split into two clearly labelled nodes ("Idle / rate-limit gate" and "Load
  unsent notifications") or write the full caption at a font size that survives
  down-scaling.
- **Inbound step labels are vague.** The INBOUND row reads (approximately) "Pending
  chops via sase*telegram → Write response JSON or launch agent → Callbacks, text,
  photos, documents". The "Callbacks, text, photos, documents" node is actually the
  \_first* step (Telegram input types), not the last. Reorder so the lane reads input →
  poll/decode → dispatch (response file / agent launch / slash command) so the arrow
  direction matches causality.
- **No "off-page" hint for the sibling repo.** `../sase-telegram` is a
  separately-versioned plugin repo (`pip install sase-telegram`), not part of the SASE
  checkout. A reader seeing `../sase-telegram` may assume it's a subdirectory of the
  current repo. Add a small annotation like "separate package:
  `pip install sase-telegram`" on the column header.

## 2. Specific accuracy errors against current code

The grounding sources for accuracy are `../sase-telegram/README.md`,
`../sase-telegram/src/sase_telegram/`, and `~/.config/sase/sase_athena.yml`
(`axe.providers.telegram.chops`).

- **File name typos / wrong file names:**
  - The "SASE core" column shows `notifications.json`. The actual file is
    `~/.sase/notifications/notifications.jsonl` (JSON Lines, not JSON). Fix the
    extension and ideally show the full path so it's not confused with a per-project
    file.
  - The state store shows `last_send_ts`. The real file is `last_sent_ts` (past
    participle). See `../sase-telegram/README.md` State Files table and
    `~/.sase/telegram/last_sent_ts` on disk.
  - The state store appears to show `mailing_inbox.json` (or similar). No such file
    exists. The actual two-step-feedback file is `awaiting_feedback.json`.
  - The final OUTBOUND node reads "Telegrams Bot API". It is "Telegram Bot API"
    (singular).
- **State store omits real files.** The on-disk state under `~/.sase/telegram/` actually
  contains: `pending_actions.json`, `rate_limit.json`, `update_offset.txt`,
  `awaiting_feedback.json`, `last_sent_ts`, `outbound.lock`, `outbound_debug.log`,
  `commands_registered_ts`, `images/`, `project_context.json`, and
  `update_completions/`. The diagram shows only four. Either show the full set (grouped
  by purpose: rate/lock, offsets, pending, feedback, logs, attachments) or annotate
  "subset shown — see README".
- **OUTBOUND step 1 ("AXE lumberjack run chops") is correct in spirit but mis-scoped.**
  AXE schedules both `tg_outbound` and `tg_inbound`; in the diagram AXE only feeds
  OUTBOUND. Show AXE feeding both lanes (a single AXE node with two outgoing arrows, one
  to each lane).
- **OUTBOUND chop entry-point name is implicit.** The actual installed CLI scripts are
  `sase_chop_tg_outbound` and `sase_chop_tg_inbound` (defined in `pyproject.toml`
  `[project.scripts]`). The diagram uses "Outbound chop" / inbound paraphrases. Showing
  the real script names anchors readers who go look for them in the codebase.
- **Plan Approval keyboard is incomplete.** The chat mock shows roughly "Approve /
  Reject / Feedback / Custom". Per `formatting.py` the actual plan approval keyboard
  exposes five primary buttons — Tale / ✅ Approve / Epic / Reject / Feedback — plus
  dynamic option buttons for User Questions. A reader would conclude approvals are
  binary, which is wrong. Either redraw the keyboard or note "(buttons vary by
  notification type)".
- **Inbound dispatch outcomes are missing one branch.** Inbound writes a response file
  _or_ launches an agent _or_ runs a slash command (`/list`, `/kill`, `/resume`,
  `/changes`, `/xprompts`, `/bead`, `/update`). The diagram only shows "Write response
  JSON or launch agent". Add a "slash-command dispatch" branch.
- **`SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED` is invisible.** This env-var-gated mode
  (callbacks/feedback/slash-commands still process, but free-form text/photo messages no
  longer launch agents) is a deployment-relevant configuration. It does not need its own
  node, but a small footnote near the inbound "launch agent" arrow ("disabled when
  `SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED` is set") would prevent the diagram from
  misleading multi-host operators.
- **Outbound delivery controls are mis-attributed.** OUTBOUND no longer reads SASE TUI
  user-presence state. The diagram should show OUTBOUND step 3 as high-water mark /
  read-state / rate-limit filtering rather than a user-presence gate.
- **Outbound side-effects on attachments are not represented.** The outbound script
  materialises response-only Markdown extracts and converts attachments to PDF via
  SASE's shared renderer (`pdf_convert.py`). The diagram has a "generated images &
  artifacts" box on the SASE-core side but no arrow into OUTBOUND that represents
  attachment delivery to Telegram. Add an arrow
  `generated images & artifacts → OUTBOUND step 4 (format) → Telegram (sendPhoto / sendDocument)`.

## 3. Concrete suggested changes for the regenerated image

Apply in order — items 1–4 are accuracy fixes that cannot ship with the current image;
items 5–8 improve clarity for a first-time reader.

1. Rename: `notifications.json` → `notifications.jsonl`; `last_send_ts` →
   `last_sent_ts`; `mailing_inbox.json` → `awaiting_feedback.json`; "Telegrams Bot API"
   → "Telegram Bot API".
2. Expand state-store contents to include `rate_limit.json`, `update_offset.txt`,
   `outbound_debug.log`, `commands_registered_ts`, and `images/` (group as: _delivery_ —
   rate*limit, last_sent_ts, outbound.lock, outbound_debug.log; \_inbound* —
   update*offset, awaiting_feedback, pending_actions; \_attachments* — images/).
3. Replace the single "Approve / Reject" keyboard with the actual plan-approval row
   (Tale · ✅ Approve · Epic · Reject · Feedback) and add a small badge strip naming the
   eight notification types and the seven slash commands.
4. Show AXE feeding **both** lanes; show `generated images & artifacts` feeding the
   OUTBOUND format step.
5. Re-letter the lanes (`O1..O5`, `I1..I3`) so the two flows are visually independent.
6. Insert an explicit `SASE core | ../sase-telegram` process boundary, and label the
   cross-boundary artifacts (`notifications.jsonl`, `*.response.json`, `sase run`
   subprocess) on the arrows that traverse it.
7. Annotate `../sase-telegram` as a separate `pip install sase-telegram` package, and
   the chops as `sase_chop_tg_outbound` / `sase_chop_tg_inbound`.
8. Add a small footnote on the inbound "launch agent" arrow: "disabled when
   `SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED` is set".

The regenerated image should reference `docs/images/infographic-style-brief.md` for
visual consistency with the other architecture diagrams.
