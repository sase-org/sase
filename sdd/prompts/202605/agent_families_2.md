---
plan: sdd/epics/202605/agent_families_2.md
---
 I want to improve and formalize the way that we handle creating new and renaming old agents when plans are
approved, feedback is made on a plan, or a question is answered. Can you help me implement this new concept of "agent
families" that I have described in the sections below?  

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### Current State

This is the current state as far as I know:

- When an agent creates a plan, that agent is renamed to `<old_name>.plan`. The name of the root and child agent entries
  are the same.
- If the user approves that plan, a new coder agent is created under the same root entry that is named
  `<old_name>.code`. The root entry is still named `<old_name>.plan`.
- We use the `.q` suffix for agents that ask questions and the `.<N>` suffix for agents that run after the user answers
  questions or after the user leaves feedback on a plan.

### Desired New State

- We should use `-` instead of `.` to separate `<old_name>` from its suffices.
- We should NEVER change the name of the root entry (i.e. it should always stay `<old_name>`). If the plan is approved
  we should rename the planner agent step `<old_name>-plan`.
- The root entry status (example agent row statuses: PLAN, RUNNING, etc...) should **ALWAYS** be equal to the last (most
  recently launched) child agent entry.
- We will refer to all agents with names of the form `<name>-<some_subname>` as agents in the `<name>` "agent family".
- User-specified agent names (e.g. with the `name` directive) should forbid the agent name to contain a "-" character.

### `%wait` and `#resume`

- Since the route entry name will never change, that means that when the root entry is selected and we use the `w`
  keymap to get a prompt with `%wait:<name>` inserted in it or the `r` keymap to get a prompt with `resume:<name>`
  inserted in it, we should use the root entry name for `<name>`, which will not have a `-<some_subname>` suffix.
- Waiting for a root entry that is not associated with one entry, but many, should mean that the agent launched from
  with that prompt should not be launched until all agents in the `<name>` agent family have completed successfully.
- Resuming a root entry (with the `resume:<name>` directive) that is not associated with one entry, but many, should be
  equivalent to resuming the most recent agent to complete in the `<name>` agent family (for example, this is likely
  `<name>-code` if the first agent in the family proposed a plan that was approved).