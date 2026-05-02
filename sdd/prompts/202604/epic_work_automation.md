---
plan: sdd/epics/202604/epic_work_automation.md
---
 Can you help me add direct integration into sase for working epics (i.e. running one agent per phase bead and then running one agent to land the epic)?

- We will need to add a new 'is_ready_to_work' boolean field to epic beads that should start out as `false` and be set to true only when the new `sase bead work <epic_bead_id>` command is run. We should update the prompt we use when
  creating epics to tell that agent to run this command after committing.
- I currently use the `#bd/next` and `#bd/land_epic` xprompts to run sase agents manually for this. Namely, I run N `#bd/next` agents, where N is the number of phase beads, and have each of these agents run in sequence (using the
  `%w` directive). I also run a `#bd/land_epic` agent at the same time, which waits for the last `#bd/next` agent to complete (using the `%w` directive).
- We should start running a very similar process automatically whenever an epic bead is marked as ready to work. The main difference should be that, since we can figure out the dependencies deterministically, we will potentially
  launch multiple phase agents at the same time. Also, we will claim the bead associated with an agent before launching that agent and give the agent that bead ID explicitly.
- All of these new agents that run in the background should be powered by new, builtin xprompts, but these xprompts should be overridable by the user using new xprompt tags (ex: "create_epic_bead", "work_phase_bead", "land_epic",
  etc...).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

