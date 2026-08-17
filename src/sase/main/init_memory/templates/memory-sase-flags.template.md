---
type: long
parent: AGENTS.md
description: Read before adding, deferring, or removing a SASE feature flag or flag bead.
---

# SASE Feature Flags

A SASE feature flag is a temporary boolean route for behavior that reaches users before
it is ready to become unconditional. Kinds are:

- `beta`: disabled by default while a user-visible feature proves out.
- `wip`: shields a partially landed path that must not be the default yet.
- `sunset`: keeps an old branch reachable while users migrate.
- `ops`: a permanent operational switch; it needs a rationale and no flag bead.

Create a flag only with `sase flag new <key>`. It creates the dedicated `flag` removal
bead and prints the registry entry and both-states test checklist. Do not hand-add a
registry member, and do not reuse the implementation epic as the removal bead.

The registry owns key, kind, default, scope, description, and bead id. The flag bead owns
`remove_by_date` and `remove_by_release`. A flag is due only after both thresholds have
passed; the boolean value never changes because a deadline passed.

Every non-ops flag needs tests for both enabled and disabled states. The branch that
will lose at removal time must still be explicit enough that a later worker can delete
it in the same change that closes the flag bead.

When `FlagTriage` asks about a due flag:

- **Remove**: choose the winning branch, delete the losing branch, remove the registry
  entry, and close the flag bead in that change.
- **Extend**: set a new date and release only when the flag is still temporary.
- **Keep**: use when the behavior is permanent; promote it to `ops` or an ordinary
  config field with the rationale recorded.
- **Close**: close only when the flag was already removed or is intentionally orphaned.

If users are meant to choose the value forever, it was never a feature flag. Add a
normal config field instead.
