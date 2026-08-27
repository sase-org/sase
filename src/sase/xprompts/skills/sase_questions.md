---
name: sase_questions
description:
  Ask the user questions. Use instead of {{ provider_native_ask_tool }} (which is
  disabled).
skill: true
---

<!-- prettier-ignore -->
Use this skill when you need user input. This replaces {{ provider_name }}'s native {{ provider_native_ask_tool }}{% if provider_native_ask_tool == "AskUserQuestion" %}.{% else %} tool.{% endif %}

## Usage

```bash
sase questions '<json>'
```

### JSON Schema

```json
[
  {
    "question": "Full question text (required)",
    "header": "Short sidebar label (optional)",
    "options": [
      { "label": "Option label (required)", "description": "Details (optional)" }
    ],
    "multiSelect": false
  }
]
```

### Examples

Single question with options:

```bash
sase questions '[{"question": "Which database should we use?", "options": [{"label": "PostgreSQL", "description": "Relational, mature"}, {"label": "SQLite", "description": "Embedded, simple"}]}]'
```

Multiple questions:

```bash
sase questions '[{"question": "Approach?", "header": "Approach", "options": [{"label": "A"}, {"label": "B"}]}, {"question": "Include tests?", "options": [{"label": "Yes"}, {"label": "No"}]}]'
```

## Handoff And Continuation

On success, `sase questions` writes a durable handoff marker and sends `SIGTERM` to the
current agent runner process group either way. What happens next depends on the
`gate_shell_handoff` beta flag.

**With `gate_shell_handoff` enabled**, the runner creates a **question gate shell** — a
named, non-LLM member of your agent family that publishes the questions, outlives you,
and hands the answer to the next family member. Your turn ends as `DONE`; there is
nothing after this for you to do. The family's status shows `QUESTION` until it is
answered, then `ANSWERED`. Answering it launches a follow-up agent whose prompt carries
the merged Q&A across every round asked so far, continuously numbered — the same
`## Your next action` shape a gate shell always composes. Do not create a question gate
shell yourself with `/sase_gate`; `sase questions` already does this for you when the
flag is on.

**With `gate_shell_handoff` disabled**, the runner recognizes the marker as an
intentional question handoff, creates a command-backed `UserQuestion` gate, yields its
runner slot while it waits, and reacquires a slot before continuing. The answer is added
to the Q&A history and reconstructed follow-up prompt in-process; the interrupted
provider turn does not return normally.

Do not poll question request or response files. ACE, mobile, and Telegram submit the
complete validated form through the same write-once gate command, and the runner (or,
with the flag enabled, the gate shell's settlement) observes the terminal response
mechanically.
