---
plan: sdd/epics/202603/epic_approval.md
---
Can you help me add support for a new `E` (epic) option on the TUI plan approval popup and a corresponding Telegram
"Epic" inline keyboard button?

- This keymap (and that button) should only be shown when a .beads/ directory exists at the root of the project's (the
  one associated with the agent that created this plan) primary (#1) workspace directory AND that repo has opted in
  using `sdd.version_controlled` config field (see recent, related git commits for context on this field).
- If this keymap is used / this Telegram button is pressed, we should create the local specs/ and plans/ markdown files
  as if the plan had been approved. But, instead of starting a coder agent to implement the plan, we should launch a new
  epic agent (use the `.epic` suffix and make sure this agent shows in the same workflow on the "Agents" tab) that runs
  the `#<vcs>:<name> #bd/new_epic:plans/<plan_name>.md` prompt, where `#<vcs>:<name>` is the same VCS xprompt used in
  the planner agent's prompt.
  - RELATED BUG: I don't think `#<vcs>:<name> ` is prepended to the coder (`.code`) agent's prompt is it? If not, can
    you fix that too!
- Since we will be using the `#bd/*` xprompts in sase's core now, we should move their definitions from the local
  sase.yml file to the src/sase/default_config.yml file (this is also required so the `#sase/` prefix isn't auto-added).
