---
plan: sdd/epics/202603/custom_keymaps.md
---
Can you help me make ALL keymaps in the `sase ace` TUI configurable via sase's deep-merge configuration system?

- All keymaps defaults (the ones that are hard-coded currently) should be defined in the src/sase/default_config.yml
  file.
- For the new (see related git commits from the last few days) `(MxN.H)` tab title syntax, the `x` and `.` correspond
  with the keymaps that dismiss the `N` entries or show/hide the `H` entries, respectively. So make sure that these
  symbols in the tab title are also configured via the corresponding keymaps configuration.
- IMPORTANT: Note that I said ALL keymaps and not _some_ keymaps. It is VERY important that you not miss any!
- Groups like leader, copy mode, fold mode, and bang should be configurable. The user should not only be able to
  configure the prefix key that triggers the mode but should also be able to add new custom modes.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.
