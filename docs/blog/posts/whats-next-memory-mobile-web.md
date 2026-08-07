---
title: "[09] What's Next — Shared Memory, Mobile, and the Web Surface"
date: 2026-05-23
draft: true
description: >-
  SASE today is the orchestration layer. The next horizon is shared memory across
  agents, a mobile control surface, and a web frontend that doesn't require a terminal.
categories:
  - Agentic Software Engineering
  - Roadmap
slug: whats-next-memory-mobile-web
links:
  - Mobile Gateway: mobile_gateway.md
  - "[08] Where You Type — The Prompt Input Widget and sase-nvim": blog/posts/prompt-widget-and-nvim.md
  - View on GitHub: https://github.com/sase-org/sase
---

# [09] What's Next — Shared Memory, Mobile, and the Web Surface

SASE today is the orchestration layer. The next horizon is the things that horizon-line
doesn't quite reach yet — durable shared memory across agents, a phone you can drive
from, and a browser the team can open without learning a TUI.

<!-- more -->

The previous nine posts walked through what exists: XPrompts, AXE, SDD and beads, commit
workflows, ChangeSpecs, the Telegram mobile control surface, and the prompt input widget
with its Neovim plugin. This one is shorter and more speculative. It names three threads
that are in motion but not yet shipped, and points at the artifacts where the design
work is happening.

## Shared Memory Across Agents

The gap today: short-term memory (`type: short` notes loaded through `AGENTS.md`) and
audited long-term memory (`type: long` notes read on demand with `sase memory read`)
both work per-session. There is no canonical cross-agent store. Every agent reconstructs
context from scratch.

The direction, sketched in
[`sdd/research/202605/zettel_sase_shared_memory.md`](https://github.com/sase-org/sase/blob/master/sdd/research/202605/zettel_sase_shared_memory.md),
is a two-layer system:

1. **Canonical zettel** — curated, human-readable, linked knowledge objects with stable
   IDs.
2. **SASE memory projections** — generated views of those zettel for agents: flat
   `sase/memory/` notes, audited read indexes, skills, project plans, review checklists.

Agents propose facts via an inbox (`.sase/memory/inbox/`) and humans (or distillation
workflows) promote them into canonical zettel. Agent-initiated retrieval
(`sase memory search`, `sase memory show`, `sase memory related`) lets a mid-task agent
ask the memory layer for context it didn't get pre-loaded. Today's agents reconstruct
context every time; tomorrow's should be able to _ask_.

## Why This Isn't Shipping Yet

Three problems keep this on the research shelf for now:

- **Memory poisoning.** A bad inbox promotion could silently rewrite older zettel.
  SASE's planned defense is append-and-supersede (a new zettel that links
  `supersedes: @old`) rather than in-place mutation, and required human review for inbox
  promotions.
- **Projection cost.** Generating projections on every read is wasteful; generating them
  on every write doesn't scale either. The first version stays read-only and uses
  existing audited long-memory reads so nothing in the runtime has to change.
- **Retrieval determinism.** Vector search is the wrong first abstraction. Existing
  zettel are already link-rich and ID-rich; deterministic structure (IDs, links, note
  types, triggers, applies-to paths, provenance) goes further before embeddings start to
  matter.

The proposal lists a four-phase rollout: read-only projections first, project-local
zettel store next, then the agent proposal flow, and finally agent-initiated retrieval.
Each phase ships something usable on its own; the whole stack does not have to land at
once.

## Mobile

[\[07\]](telegram-mobile-agents.md) covered the Telegram chop that ships today and gives
you a working mobile control surface right now. The native mobile path is the
longer-term answer.

The mobile gateway already exists. `sase mobile gateway start` runs a Rust gateway in
the foreground on `127.0.0.1:7629`, prints a one-time pairing challenge, and waits for a
mobile client to finish pairing via `POST /api/v1/session/pair/start` then
`/session/pair/finish`. Loopback by default; Tailscale Serve for remote access without
exposing a public bind.

Today's gateway is a tightly-scoped HTTP API: list agents, launch text, launch image,
kill, retry, ChangeSpec tag operations, an XPrompt catalog, beads list, and an SSE event
stream. Push hints are opt-in (FCM HTTP v1, or a local test provider) and carry only
safe IDs, categories, and short display text — never tokens, prompt bodies, response
text, attachment contents, or host paths. The mobile client always fetches authenticated
state after a wake.

What's missing on the phone side is richer interactions, push hints that feel native to
the OS, and a story for non-loopback deployments that isn't "wire up Tailscale
yourself." The [mobile MVP runbook](../../mobile_mvp_runbook.md) covers debug APK
install, signed releases, Firebase-configured internal builds, Tailscale Serve setup,
the threat model, and rollback steps for the path that exists today.

## Web

Web is the analogous shape: an HTTP surface that doesn't require terminal-native ACE.
The unresolved design question is whether the web frontend reuses the mobile gateway
(which would mean carrying the gateway's product-shaped APIs into a different client) or
stands up its own, browser-aware backend (which would mean a second control surface to
keep aligned with the TUI). Either way, the goal is the same: code review and agent
supervision should be reachable without learning a TUI first.

## The Throughline

Every horizon in this list trades terminal-native context for context that lives outside
one developer's head. Shared memory moves intent across agents; mobile and web move the
control surface to wherever the operator is. The orchestration layer the series has
covered — XPrompts, AXE, SDD, beads, commit workflows, ChangeSpecs, and the Telegram
chop — is what makes that move possible. Those pieces are how agent work becomes a
durable object in the first place; memory, mobile, and web are how that durable object
stays reachable.

## What To Read Next

- [Mobile gateway](../../mobile_gateway.md) — pairing, push hints, host-bridge commands,
  events, notifications, agents, contract snapshot.
- [Shared memory research](https://github.com/sase-org/sase/blob/master/sdd/research/202605/zettel_sase_shared_memory.md)
  — the full proposal, including external research notes, design decisions, and open
  questions.
- [SASE Blog](../index.md) — launch posts and longer essays as they publish.
