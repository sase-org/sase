---
plan: sdd/epics/202604/agents_tab_nested_groups.md
---
 Can you help me add support for much better organization of agents on the "Agents" tab of the `sase ace` TUI by adding support for nested groups?

- We should support 3 levels of nesting, in this order (i.e. the former levels contain the latter levels):
  1. Agent Tags (NEW)
  2. Project / ChangeSpec that the agent was run against
  3. The root part of an agent's name (ex: all agent's with names that start with `foo.` should be grouped together at this level).
- We will need to add support for agent tags that will look like `@foobar`. The user should be able to add and remove tags from agents on the Agents tag.
- The `l`/`L` and `h`/`H` keymaps should collapse/expand these levels (one at a time). Unlike workflow steps, there should be no indentation involved. Other than that, I want you to decide how this looks. Just make sure it is
  beautiful!
- When collapsed, each visible group should be selectable (as an entry in the side-panel) and I should be able to kill/dismiss all agents in that group using the `x` keymap.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

