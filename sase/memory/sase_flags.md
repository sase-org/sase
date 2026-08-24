---
type: reference
parent: AGENTS.md
description:
  Read before adding, deferring, or removing a SASE feature flag or flag bead.
---

# SASE Feature Flags

A SASE feature flag is a temporary boolean route for behavior that reaches users before
it is ready to become unconditional. Flags are a `sase`-project concern only. A flag
bead is a task bead of type `flag`, not a fourth issue type.

Kinds and their derived defaults:

- `beta`: default **off**. The behavior is unproven; a user opts in.
- `sunset`: default **on**. The behavior is already the default; the flag keeps the old
  branch reachable while callers migrate.

One removal rule covers both kinds: **removing a flag deletes the disabled (Off) branch
and makes the enabled (On) branch unconditional.** If users are meant to choose the
value forever, it was never a feature flag. Add a normal config field instead.

Create a flag only with `sase flag new <key>`. It creates the typed task bead, prints
the registry entry to paste, and prints the both-states test checklist. Do not hand-add
a registry member, do not use `sase bead create` or `/sase_new_task`, and do not reuse
the implementation epic as the removal bead. `sase bead create -T 'task(flag)'` is
refused because the type is not agent-creatable.

`sase flag new` requires three authored sentences and supplies the rest:

- `--when-enabled` — what the code does with the flag on.
- `--when-disabled` — what the code does with the flag off (the branch deleted at
  removal).
- `--remove-when` — the qualitative gate. The date and release say when to ask; this
  says how to answer.

The other four required fields are `key` (the positional argument), `kind` (`-k/--kind`,
default `beta`), `remove_by_date` (today + 90 days), and `remove_by_release` (current
minor + 2). `-d/--description` seeds the registry entry's one-line help and defaults to
`--when-enabled`. `-r/--remove-by` overrides both thresholds at create time. `-z/--size`
defaults to `small`. Each of the three prose options accepts `@<path>`.

The registry owns key, kind, description, and bead id. The default is derived from
`kind` and is not independently settable. The bead owns all seven fields. `kind` is
stored in both; `tools/check_feature_flags` lints that they agree. A flag is due only
after both thresholds have passed; the boolean value never changes because a deadline
passed. Extend a still-temporary flag with
`sase bead update <id> -b YYYY-MM-DD/release`.

Every flag needs tests for both enabled and disabled states. The Off branch must stay
explicit enough that a later worker can delete it in the same change that closes the
flag bead.

When `FlagTriage` asks about a due flag task bead:

- **Remove**: delete the Off branch, make the On branch unconditional, remove the
  registry entry, and close the flag bead in that change.
- **Extend**: push both thresholds out only when the flag is still temporary.
- **Keep**: the behavior is permanent. It was never a feature flag; make it a config
  field and close the bead.
- **Close**: abandon the removal. Use this when the flag was already removed or is
  intentionally orphaned; integrity checks catch a surviving definition.
