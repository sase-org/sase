---
create_time: 2026-05-02 21:40:06
status: wip
prompt: sdd/prompts/202605/telegram_beads_all_projects.md
---
# Fix Telegram `/beads` All-Project Listing

## Context Reviewed

- Recent SASE chats:
  - `sase-ace_run-zc_plan-260502_211543` planned a previous fix for Telegram `/beads` resolving the wrong single
    project.
  - `sase-ace_run-260502_211543` implemented that fix in `../sase-telegram` as chat-scoped project context.
  - `sase_org-tmp_260502_211545-main-260502_211849` diagnosed the earlier symptom as `zorg` beads being hidden because
    the command ran in `sase`.
- Current code in `../sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py` still runs `/bead` and `/beads`
  through `_run_bead_command(["list"], message=...)`, which resolves exactly one cwd and parses exactly one project’s
  `sase bead list` output.
- Current local reproduction:
  - `sase bead list --status=open` in this `sase_100` workspace returns `No issues found.`
  - The known `zorg` workspace returns open beads: `zorg-1`, `zorg-2`, and `zorg-1.8`.

## Root Cause

The prior fix treated `/beads` as a context-sensitive command: find the best project for this Telegram chat, then list
beads in that one project. That conflicts with the current product requirement: `/beads` should show all open beads
across all known projects.

Because the command uses a single cwd, it can still legitimately render `No open beads.` whenever the chosen cwd has no
open beads, even though another known project does. The bead CLI itself is project-local by design; the aggregation
needs to happen in the Telegram slash command layer unless/until there is a core all-project bead query.

## Goals

1. Make `/beads` and bare `/bead` list open beads across every known SASE project under `~/.sase/projects`.
2. Keep `/bead <id>` and bead picker callbacks able to show the selected bead’s details.
3. Preserve `SASE_TELEGRAM_BEAD_PROJECT` as an explicit narrowing override for users who want one project.
4. Keep existing chat-scoped project context as a fallback for detail lookup, not as the default list scope.
5. Add focused tests that reproduce the current failure: one known project with no beads and another known project with
   open beads must render the open beads.

## Design

Add a small all-project bead listing path in `../sase-telegram`:

- Discover known project workspaces by scanning `~/.sase/projects/*/<project>.gp` and reading `WORKSPACE_DIR:`.
- Validate each workspace exists.
- For `/beads` and `/bead` with no argument:
  - If `SASE_TELEGRAM_BEAD_PROJECT` is set, keep current single-project behavior.
  - Otherwise run `sase bead list --status=open` once per known workspace.
  - Parse each result with `parse_bead_list_output`.
  - Ignore successful empty projects (`No issues found.`).
  - Include project metadata with each entry so the picker can route detail lookup to the same project.
- Render labels as `<icon> <id>: <title>` when IDs are already globally distinctive. If a future collision appears,
  include the project name in the label and route by project-aware callback data.
- For picker callbacks, encode the project in callback data when possible, for example `bead:<project>/<bead-id>:show`.
  Decode that token and run `sase bead show <id>` in the matching project workspace.
- For manual `/bead <id>`:
  - Continue honoring `SASE_TELEGRAM_BEAD_PROJECT` first.
  - If the id contains an encoded project prefix, use it.
  - Otherwise search known projects for the bead id by running `sase bead show <id>` until one succeeds, preferring the
    chat-scoped context first to keep common manual lookups fast.

## Files to Change

In `../sase-telegram`:

- `src/sase_telegram/scripts/sase_tg_inbound.py`
  - Add known-project workspace discovery helpers.
  - Add all-project open bead listing helper.
  - Update `_show_bead_selection()` to aggregate by default.
  - Update bead callback/detail routing to carry or resolve project scope.
- `tests/test_inbound.py`
  - Add tests for all-project `/beads` listing when the current/resolved project has no beads.
  - Add tests for project-aware callback routing.
  - Keep existing single-project override/context tests.
- `README.md` and `docs/inbound.md`
  - Update `/bead` documentation from “remembered project” default to “all known projects” default.

No `sase_100` source changes are expected unless a reusable core helper is needed during implementation.

## Verification

1. In `../sase-telegram`, run focused inbound tests around bead behavior.
2. Run `just check` in `../sase-telegram`.
3. Since this issue is expected to be fixed in the sibling plugin repo, run `just check` in `sase_100` only if source
   files here change.
4. Manual smoke:
   - Ensure `sase` has no open beads and `zorg` has open beads.
   - Send `/beads`.
   - Expected: Telegram shows the `zorg-*` open bead picker, not `No open beads.`
