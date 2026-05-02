---
create_time: 2026-03-29 12:52:51
status: done
prompt: sdd/prompts/202603/tg_agent_descriptions.md
---

# Plan: Add Agent Descriptions to Telegram /kill and /resume Buttons

## Problem

When a user sends `/kill` or `/resume` without arguments, the bot shows an inline keyboard with just agent names as
button labels. This gives the user no context about what each agent is doing — they have to remember or guess which
agent is which.

Meanwhile, the `/list` command already shows rich agent info (model, duration, prompt snippet), but users have to
mentally cross-reference `/list` output with `/kill` or `/resume` buttons.

## Approach

**Send a descriptive message above the buttons.** Rather than cramming info into button labels (which get truncated on
mobile), we replace the generic "Select an agent to kill/resume:" header with an HTML-formatted summary that describes
each agent. The buttons themselves stay simple and tappable.

This is the same pattern that `/list` and `/listx` already use for display — we're just pairing that info with the
existing button keyboards.

## Design

### Message format for `/kill`

Before:

```
Select an agent to kill:
[agent_a]
[agent_b]
```

After:

```
Select an agent to kill:

<b>agent_a</b>  claude-opus-4, 2h45m
<i>implement the login flow for...</i>

<b>agent_b</b>  gemini-2, 15m32s
<i>fix the flaky test in ci...</i>

[agent_a]
[agent_b]
```

### Message format for `/resume`

Same idea — a descriptive block for each agent, grouped by running vs done:

```
Select an agent to resume:

Running:
<b>agent_a</b>  claude-opus-4, 2h45m
<i>implement the login flow for...</i>

Done:
<b>agent_b</b>  gemini-2, 15m · FAILED
<i>fix the flaky test in ci...</i>

[🏃 agent_a]
[✅ agent_b]
```

- Section headers ("Running:" / "Done:") only appear when both sections have agents.
- Prompt snippets are truncated to ~80 chars (shorter than `/list`'s 120 since this message already has buttons
  competing for screen space).
- For done agents, show status only when non-DONE (FAILED, PLAN DONE) — same convention as `/listx`.

## Changes

### 1. `sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py`

**`_show_kill_selection()`** — Build an HTML description block from the running agents list (name, model, duration,
prompt snippet) and use it as the message text instead of the plain "Select an agent to kill:" string. Parse mode
switches to HTML.

**`_handle_resume_command()`** — Same treatment. Build description blocks for running agents (from `_RunningAgentInfo`)
and done agents (from `Agent` dataclass). Use section headers when both groups are present.

### 2. Extract a shared helper

Both `/kill` and `/resume` need to format agent descriptions. Extract a small helper function (e.g.,
`_format_agent_description()`) that takes a name, model, duration, and prompt snippet and returns an HTML block. This
avoids duplicating the formatting logic between the two commands and with the existing `/list` and `/listx` code.

Done agents use slightly different source fields (`agent.model`, `agent.duration_display`,
`agent.get_raw_xprompt_content()`) vs running agents (`a.model`, `a.duration`, `a.prompt`), but the output format is the
same — the helper just takes pre-extracted strings.
