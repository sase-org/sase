---
plan: sdd/epics/202605/agents_sibling_keymap.md
---
 Can you help me add a new `~` keymap to the "Agents" tab of the `sase ace` TUI?

- This keymap is similar to the `~` keymap on the "CLs" tab, but should jump to sibling agents (instead of sibling
  ChangeSpec).
- There is no room for a sibling side-panel on the Agents tab, so you will need to create a new TUI panel that pops up
  when an agent has more than one sibling (if an agent has only one sibling, pressing `~` should just trigger a jump to
  that agent row). I want you to lead the design on this one. Just make sure it looks beautiful!
- Also, f the currently selected agent has sibling agents that are showing on the "Agents" tab (i.e. have not been
  killed/dismissed), we should show some visual indication in the TUI which shows the number of siblings that agent has.
- The concept of "agent siblings" should be defined as follows: For any agent named `foo.bar`, that agent is siblings
  with every other agent named `foo.<name>` for ANY `<name>` (note that `<name>` can contain periods).
- IMPORTANT: Make sure that the TUI's performance is not harmed by any of these changes.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

