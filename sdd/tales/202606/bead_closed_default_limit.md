---
create_time: 2026-06-30 10:07:27
status: done
prompt: sdd/prompts/202606/bead_closed_default_limit.md
---
# Plan: Default Closed Bead Listings to 20 Results

## Goal

Make `sase bead list` behave as if `--limit 20` was supplied whenever the command's final status scope includes closed
beads and the user did not explicitly pass `--limit`.

User-provided limits must continue to win:

- `--limit N` prints the newest `N` matching beads.
- `--limit 0` remains explicit unlimited output.
- Omitted `--limit` remains unlimited for the default open/in-progress listing.

## Behavior Scope

Closed output means either:

- the user explicitly includes `closed` in the repeatable status filter, such as `--status closed` or
  `--status open --status closed`; or
- the existing no-status fallback switches an empty open/in-progress result to closed beads.

The new limit should apply after the same status, type, and tier filtering that `list` already performs. It should keep
the existing ordering semantics: list results are oldest-to-newest by creation time, and limiting keeps the newest
matching rows while preserving that display order.

This is a CLI presentation default, not a backend query contract. The Rust-backed read API should stay unchanged.

## Implementation Approach

1. Add a small bead-list default constant in the read-only bead CLI handler, for example
   `DEFAULT_CLOSED_LIST_LIMIT = 20`.
2. In `handle_bead_list`, compute the effective limit after the handler has resolved whether it is using explicit
   statuses or the implicit closed fallback.
3. Use the effective limit only when `args.limit is None` and the final status scope includes `Status.CLOSED`.
4. Preserve current explicit-limit behavior by applying the existing slice only when the effective limit is truthy. This
   keeps `--limit 0` unlimited.
5. Keep the existing implicit-status fallback notice. Do not add a new notice for explicit `--status closed`; instead,
   make the conditional default clear in help text and generated skill docs. If the implementation adds a truncation
   notice later, it should only appear when rows were actually omitted.

## Documentation Updates

Update all user-facing references that describe `sase bead list --limit`:

- parser help for `--limit`
- `sase bead` onboard/admin quick-start text
- source generated skill doc at `src/sase/xprompts/skills/sase_beads.md`

The docs should say that closed listings default to 20 when `--limit` is omitted, and that `--limit 0` prints all
matching closed beads.

After editing the skill source, regenerate deployed skill files with:

```bash
sase skill init --force
chezmoi apply
```

## Test Plan

Add or update focused coverage for:

- parser/docs contract examples for closed listing and explicit unlimited output
- explicit `sase bead list --status closed` with more than 20 closed beads prints only the newest 20 by default
- explicit `sase bead list --status closed --limit 0` prints all matching closed beads
- implicit closed fallback with more than 20 closed beads also defaults to newest 20
- implicit closed fallback with an explicit limit, such as `-n 1`, still honors the explicit limit
- mixed repeated status filters that include closed use the closed-output default when no explicit limit is supplied
- existing open/in-progress default listing remains unlimited when no closed status is in scope

The current closed-only golden fixture has only three rows, so the implementation should add a larger deterministic
golden fixture rather than relying on the existing fixture to prove truncation.

## Verification

Because this repository uses ephemeral workspaces, run:

```bash
just install
pytest tests/test_bead/test_cli_list.py tests/test_bead/test_cli_golden.py tests/main/test_bead_fast_path.py
just check
```

The fast-path test remains relevant because `bead list` must continue to route through the Python handler while this
presentation-only default lives there.
