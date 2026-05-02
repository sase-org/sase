---
plan: sdd/epics/202603/unified_agent_entries.md
---
Can you help me start showing all agents run by `sase axe` using the same `[agent]` entries on the "Agents" tab of the
`sase ace` TUI (with all the same fields, diffs, files in the file panel, etc.) that we use for manually run agents?

- Right now we use entries like `[crs]`, `[fix_hook]`, and `[mentor]` for these and hide them by default (unless shown
  using the `.` keymap).
- These agents should still be hidden by default, but this should be supported using a new `hidden` boolean property
  that every agent should support.
- Agent's running with this `hidden` property set to `true` should be hidden by default, but can be shown using the `.`
  keymap (just like we do for `[crs]`, `[fix_hook]`, and `[mentor]` agents right now).
- Manually created agents should also be able to be marked as hidden using a new `%hide` directive.
- Hidden agents should be auto-dismissed when they reach DONE or FAILED status (just like `[mentor]`, `[crs]`, and
  `[fix_hook]` agents are now — they simply disappear from the list rather than sitting in a dismissable state).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.
