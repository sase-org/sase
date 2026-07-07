---
plan: sdd/epics/202607/vcs_ref_colon_completion.md
---
  We recently added support for `/` completion for the `#gh` VCS xprompt workflow (see the sase-5h epic bead). Can you now help me add support for another type of VCS xprompt workflow completion?

- Namely, I want to start triggering completion for all known `#gh` / `#git` project/ChangeSpec names when the `:` key is pressed.
- For VCS types that support organizations (like `#gh`), we should also show any organizations that correspond with existing, active sase projects. For example, on this machine we should always show the `bbugyi200` and `sase-org` GitHub organizations when the user types `#gh:`.
- Make sure it is clear which entries in the completion menu are projects vs ChangeSpecs vs organizations.
- We should trigger this type of completion from the prompt input widget and the user's editor via LSP support.
- We already have logic that loads the correct completion sources. See the TUI's `+` keymap for context.
- For example, if the user types `#git:` in the prompt input widget, they should trigger a completion menu for all known bare-git projects/ChangeSpecs.
- Make sure we add support in a VCS-agnostic (remember that new VCS system support is likely to be added via a sase plugin repo that we might never have access to) way so future VCS systems get support automatically or at the very least easily. 
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful!

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  
