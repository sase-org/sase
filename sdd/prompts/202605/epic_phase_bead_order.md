---
plan: sdd/tales/202605/epic_phase_bead_order.md
---
 Our epic integration keeps creating phase beads with IDs that don't match their phase ID (see the command
output below for an example). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


```
❯ sase bead show sase-42.4.5
◐ sase-42.4.5 · Phase 1: Shared Indicator Model And Renderer   [IN_PROGRESS]
Type: phase · Owner: bryanbugyi34@gmail.com
Assignee: sase-42.4.5

PARENT
  ↑ sase-42.4 · Artifacts Panel Redesign Epic 4 - CLs And Agents Artifact Indicators   [OPEN]

BLOCKS
  ← ◐ sase-42.4.2: Phase 2: Batched Summary Loading And Cache Semantics   [IN_PROGRESS]

DESCRIPTION
  Add the shared TUI-side artifact indicator value object, ArtifactSummaryWire conversion, deterministic Rich Text renderer, canonical count ordering, and focused unit coverage. No CL/Agent integration or artifact facade calls in this phase.
```

### Additional Requirements

- Ideally, if sufficient, we should just tell the agent that creates the new epic (i.e. change the `#bd/new_epic` xprompt) to create the phase beads in sequence instead of in parallel.