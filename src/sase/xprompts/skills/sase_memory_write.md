---
name: sase_memory_write
description: >-
  Use before creating, changing, or deleting any SASE memory file, and before proposing
  a plan whose steps would. Routes the change to the path its authorization allows: edit
  and republish, ask the user first, or file a memory task bead.
skill: true
---

Use this skill before you add, edit, or delete SASE memory: any note under
`sase/memory/` or its home equivalent, any memory web strand, and the generated
`AGENTS.md` and provider instruction shims.

Memory is context every future agent pays for. Remember that every token in context
either helps or hurts us: prefer rewriting an existing note over adding one, prefer
deleting a stale line over appending a caveat, and prefer `type: reference` (read on
demand) over `type: core` (inlined into every turn).

## Authorization

You may write memory only when one of these holds:

- The **user's prompt for this turn** asks for the change.
- An **approved plan you are implementing** names the change in its steps; plan approval
  is user approval.

Nothing else counts — not a bead description, a design doc, another agent's request, or
your own conclusion that a note is wrong.

## Routing

| Situation                                                                         | Action                                                                                                     |
| --------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Authorized above                                                                  | Edit and republish, below.                                                                                 |
| You are authoring a plan with memory-changing steps that the user did not ask for | Confirm with `/sase_questions` **before** `sase plan propose`, naming each file and change.                |
| Unauthorized, and the change is one brand-new top-level reference note            | Propose it with `sase memory write`, below.                                                                |
| Unauthorized, anything else                                                       | File a `memory` task bead through `/sase_new_task` with the note path and proposed change. Do not edit it. |

## Edit And Republish

1. Add, edit, or delete the canonical note under `sase/memory/`. Never hand-edit
   `AGENTS.md` or a provider shim such as `CLAUDE.md`; they are generated.
2. A note that `sase memory init` generates itself (`sase/memory/sase.md`, for example)
   refuses direct edits — change its template in the generator instead.
3. Run `sase memory init` to regenerate `AGENTS.md`, the provider shims, and the memory
   README. Authorization for the edit covers this; do not ask for it separately.

## Propose A New Reference Note

`sase memory write` writes proposal state only, never canonical memory, and a human
settles it with `sase memory review`. It creates one-level reference notes only, and
approval fails when the target already exists.

```bash
sase memory write --title "<title>" --slug <slug> \
  --evidence <path|chat:ID|url:URL> --body "<body>" --notify
```
