---
create_time: 2026-06-26 15:09:14
status: done
prompt: sdd/prompts/202606/sase_5a_remaining.md
---
# Finish sase-5a Verification And Closure

## Context

The `sase-5a` epic moved ACE project management from the retired `,p` standalone modal into the SASE Admin Center
Projects tab. All child beads are closed and the live code implements the new pane, but verification found one remaining
user-facing documentation mismatch: `docs/configuration.md` still shows the retired `leader_mode.keys.projects: "p"`
example.

## Plan

1. Update the ACE keymap configuration documentation so the sample leader-mode keys no longer advertise the retired
   `projects: "p"` shortcut.
2. Re-run focused source checks for stale live references to the removed modal/action/keymap, treating historical SDD
   plans/prompts as archival unless they are the active `sase-5a` plan file.
3. Run the relevant test/verification commands for the migrated Projects tab and overall tree health.
4. Update the active epic plan frontmatter at `sdd/epics/202606/projects_admin_center_tab.md` to `status: done`.
5. Close the `sase-5a` epic bead with `sase bead close`.
