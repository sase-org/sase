---
plan: sdd/tales/202607/install_mode_switch.md
---
 Can you help me make it easy for users to switch to/from the published PyPI versions (of sase, sase-core, and sase's plugins) and the dev/editable versions? 

- This functionality should be made available from the CLI (maybe via the `sase update` command somehow?) and the TUI via the "Updates" tab on the "SASE Admin Center" panel.
- When the user switches from published versions to dev/editable versions, we should clone the repos for sase, sase-core, and all of sase's plugins to a consistent set of local directories and reinstall sase using the editable/dev versions of all of those packages.
- Make sure it is clear what the version change will be for every one of these packages.
- The user should have to confirm via a y/n prompt in the TUI and the CLI (which should have a `-y|--yes` option to bypass this).
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful! 

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 