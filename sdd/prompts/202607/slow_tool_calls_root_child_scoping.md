---
plan: sdd/tales/202607/slow_tool_calls_root_child_scoping.md
---
 I don't think that the "SLOW TOOL CALLS" section in the agent metadata panel on the "Agents" tab of the `sase ace` TUI is showing for the root agent entry. For example, the "04" sase agent is not showing this section, but the "04--plan" and "04--code" child agent rows are showing this section when selected. Can you help me make it so we only show the slow tool calls made by that agent when a child agent row is selected? Also, when the root agent entry is selected we should show slow tool calls from all child agents with an indicator as to what child made each tool call.

I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful! Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  