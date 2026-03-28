---
status: obsolete
---

Can you help me add beads support to `sase axe`? This is a large piece of work that should be split into phases. I'll
let you decide how many phases to create, but keep in mind that each phase will be completed by a distinct `claude`
instance.

### `/bd:*` slash commands

- We should migrate all of the `/bd:*` claude slash commands from the chezmoi repo to this repo.
- We should do something (you figure this out) to make sure that the `/bd:new_epic` slash command is invokable by both
  users and claude (I'm not sure if you need to create a skill for this or if claude can just invoke the slash command
  directly).
- We should inform claude, in the CLAUDE.md file, that:
  - When writing plans, if the plan seems large enough to benefit from multiple phases (each implemented by a distinct
    claude instance) and it is not already associated with an epic bead (i.e. we are not working a child bead), then it
    should break the plan into phases.
  - When asked to implement a plan, if the plan has multiple distinct phases, claude should use the `/bd:new_epic` slash
    command , which will create a new epic bead, child beads for each phase, and set up the bead dependencies correctly.
    It should then terminate the session WITHOUT implementing any of the work.

### `sase axe` Integration

- We should add a periodic check to `sase axe` that runs once per minute and iterates over the primary workspace
  directory for all known git projects and checks for a .beads/ directory. If not found, we do nothing.
- If found, we should run the new `#work_epics:<project_dir>` workflow (that you create) in that directory.

### `#work_epics` workflow

- This workflow should accept a project directory (`path` type) as an input argument.
- The `bd ready` command should be run in that directory. If any child beads (make sure the bead ID has a `.<N>` suffix)
  exist in the output, then each one should be iterated over and (after marking the bead as in-progress) a new agent
  should be created (in a claimed workspace directory). Each of those agents should be asked to do all of the work
  associted with that bead and then close it (WITHOUT closing the epic bead, even if this is the last child bead to be
  completed).
- If an epic bead with no visible children is found, then the `bd list` command should be run to check for any
  in-progress child beads. If any exist, we do nothing. Otherwise, we mark the epic bead as in-progress and run a new
  agent with the `/bd:land_epic <epic_bead_id>` prompt.
