---
plan: sdd/epics/202605/episode_v2_explorer.md
---
 Can you help me rewrite and re-conceptualize sase's episodes in preparation for supporting sdd/events/?

- See the research performed by previous agents in the
  sdd/research/202605/memory_episode_connected_components_and_events.md file for context.
- Do not attempt to implement sase events (I will do that later), but make sure that sase episodes are rock solid.
- More important than the implementation or architecture (both of which are VERY important) is the user visibility / the
  user's ability to see what episodes exist for a given time period and to drill down further into an episode of his/her
  choosing for a great visual depiction of the episode (make sure this is useful for users and agents--provide multiple
  views if necessary).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

