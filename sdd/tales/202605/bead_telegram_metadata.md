---
create_time: 2026-05-02 18:59:21
status: done
prompt: sdd/prompts/202605/bead_telegram_metadata.md
---
# Fix Telegram Bead Commands and Bead Metadata Display

## Context

The Telegram screenshot shows `/bead` returning `No open beads.` even though the user expects open beads. A local trace
shows the command path is:

`sase-telegram` inbound text handling -> `_handle_command()` -> `_handle_bead_command()` -> `_show_bead_selection()` ->
`_run_bead_command(["list"])` -> `sase bead list`.

From this workspace, `sase bead list --status=open` also returns no issues. However, sibling workspaces still contain
live open beads in legacy `.sase_beads/` stores, for example `sase_106/.sase_beads/issues.jsonl` has open beads. The
newer source resolver enumerates `sdd/beads` and `.sase/sdd/beads`, while older installed/workspace code enumerates
`.sase_beads`. That migration gap explains why Telegram can report no open beads while open bead records still exist.

The missing bead descriptions in both Telegram completion messages and the TUI metadata panel share the same root
helper:

`send_completion_notification()` and TUI header rendering -> `format_agent_bead_display_for_name()` ->
`_lookup_bead_issue()` -> `get_read_view()` / bead-store resolution.

When the bead issue cannot be found in the resolved stores, the helper falls back to rendering only the bead id, so
descriptions disappear without an obvious error.

## Goals

1. Make bead read paths resolve all relevant project bead stores during the migration period:
   - current version-controlled stores: `sdd/beads`
   - current non-VC stores: `.sase/sdd/beads`
   - legacy stores: `.sase_beads`
2. Keep write behavior conservative:
   - preserve existing current-store write selection rules
   - allow legacy writes only when the selected writable store is already legacy and no current-format store is
     available
   - avoid silently creating new legacy stores
3. Make `/bead` and `/beads` from Telegram use the same working directory and command behavior.
4. Make bead description lookup robust for agent completion notifications and TUI metadata.
5. Add focused regression tests for store resolution, Telegram command dispatch, and bead-display lookup.

## Plan

1. Update core Python bead-store resolution in `src/sase/bead/workspace.py`.
   - Enumerate sibling workspace bead stores across current and legacy layouts.
   - Prefer current non-VC `.sase/sdd/beads` as a primary-only store when present, matching existing semantics.
   - In VC/read mode, merge `sdd/beads` and legacy `.sase_beads` stores from the primary workspace and numbered sibling
     workspaces.
   - Deduplicate paths while preserving deterministic ordering.

2. Update the fast-path resolver in `src/sase/main/bead_fast_path.py`.
   - Feed the Rust `bead_cli_execute` binding with the same read-dir set used by `get_read_view()`.
   - Preserve current write-dir preference: local `sdd/beads`, then primary `sdd/beads`, then existing legacy
     `.sase_beads` only as fallback.
   - Keep write commands disabled for non-VC `.sase/sdd/beads` as they are today unless the existing code explicitly
     supports them.

3. Verify and harden bead metadata display.
   - Keep `format_agent_bead_display_for_name()` as the shared formatter for Telegram notifications and TUI.
   - Add tests proving a bead description is found when the issue lives only in a legacy sibling store.
   - Keep the existing fallback to bead id when lookup fails, but avoid broad behavior changes in the presentation
     layer.

4. Update `sase-telegram` command handling.
   - Treat `/beads` as an alias for `/bead`, since the user caption and common usage naturally use the plural.
   - Ensure `/bead` still lists picker buttons and `/bead <id>` still renders details.
   - Add tests for the plural alias and for the resolved cwd being passed through to `sase bead list`.

5. Test and validate.
   - Run targeted SASE tests for bead workspace resolution, fast-path behavior, and agent bead display.
   - Run targeted `sase-telegram` inbound tests.
   - Run `just check` in each modified repo after `just install`, per repo instructions.

## Risks and Mitigations

- Mixing migrated and legacy bead stores can surface duplicate issue IDs. This is already handled by merged read views
  using the most recent `updated_at`; tests should cover deterministic ordering and duplicate handling.
- Write operations must not fork state into the wrong store. The implementation should keep writes pointed at current
  stores whenever they exist, using legacy stores only when that is the only existing project store.
- The Rust core boundary matters for shared behavior. This change should keep Rust as the read/mutation engine and limit
  Python edits to path discovery and caller wiring.
