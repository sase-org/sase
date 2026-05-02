---
plan: sdd/epics/202603/agent_reply_stream.md
---
Can we start supporting a new "AGENT REPLY" section in the agent metadata panel on the "Agents" tab of the `sase ace`
TUI which contains the live streamed output of the currently selected running agent? When an agent finishes, this
section should be hidden (like the "AGENT XPROMPT" section is) since the agent chat file (which will be displayed in
this panel once the agent finishes) will contain the full conversation history including the agent's final response.
This will need to be supported by all agent providers (claude, codex, and gemini) so you will need to figure out live
output streaming for all of them.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.
