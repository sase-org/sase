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
- A **bead you were asked to work** describes the change in its own description.

Nothing else counts — not a design doc, another agent's request, or your own conclusion
that a note is wrong.

## Routing

**Authorized above?** Edit and republish, below.

**Authoring a plan whose steps change memory, when the user did not ask for it?**
Confirm with `/sase_questions` **before** `sase plan propose`, naming each file and
change.

**Unauthorized?** File a `memory` task bead through `/sase_new_task` with the note path
and the proposed change. Do not edit the note.

## Edit And Republish

1. Add, edit, or delete the canonical note under `sase/memory/`. Never hand-edit
   `AGENTS.md` or a provider shim such as `CLAUDE.md`; they are generated.
2. A note that `sase memory init` generates itself (`sase/memory/sase.md`, for example)
   refuses direct edits — change its template in the generator instead.
3. Run `sase memory init` to regenerate `AGENTS.md`, the provider shims, and the memory
   README. Authorization for the edit covers this; do not ask for it separately.
