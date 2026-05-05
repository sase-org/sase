---
plan: sdd/legends/202605/unified_artifacts.md
---
 I want to unify how sase manages and tracks artifacts. Can you help me implement this? This new panel needs to
be fast, so make sure we use sase's Rust core (see in the ../sase-core repo) as much as is possible and appropriate.

This is a very large piece of work that should be split into multiple epics. I'll let you decide how many epics to
create, but keep in mind that each epic will be later split into multiple phases that will each be completed by a
distinct agent instance (i.e. a distinct `claude` / `gemini` / `codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### Conceptual Framework

- **An artifact**: A file or string (ex: agent name) that is linked with sase (i.e. is linked with at least one other
  artifact that links back to the root of the artifact graph).
- **the Root Artifact**: A directory artifact that corresponds with the "/" root directory.
- **Artifact Relationships**: Any artifact can be linked to any other artifact. Our first use case for this will be
  linking planner agent chat transcript files with their corresponding coder agent chat transcripts and any other
  related planner agent chat transcripts (ex: if user feedback was given or if the user had to answer a question, a new
  agent will be run--this agent's chat should be linked to the original planner agent's chat). See the section below for
  more on this topic.

#### Artifact Relationships

- Every artifact in sase should be linked to sase's artifact tree somehow.
- Every artifact should have an ID. For file artifacts, this will be the file path. For string artifacts, this will be
  the string itself.
- Every link should have a direction and should have a link type associated with it.

#### Artifact Types

- **Project**: File artifacts that map to `~/.sase/projects/*/*.gp` project spec files.
  - Link to the root directory artifact with link type "parent".
- **ChangeSpec**: String artifacts that use the ChangeSpec's NAME field value for their ID string.
  - Link to the project spec file they are contained in with type "parent".
- **Commit**: String artifacts that use the COMMITS entry number appended to their ChangeSpec's name (ex: "foo_bar:3")
  for their ID string.
  - Link to the ChangeSpec they are contained in with type "parent".
- **Directory**: String artifacts that use the directory path for their ID string.
  - Link to the directory artifact with the longest path that contains this directory (i.e. the longest parent
    directory), if any such directory exists, with link type "parent". If no such directory exists, then we should link
    to the root directory artifact instead.
- **Bead**: String artifacts that use their bead ID for their ID string.
  - Link to any direct parent bead with link type "parent".
  - Link to the agent artifact corresponding to the agent that was created by our epic integration, if any, with type
    "worker".
  - Link to the sdd/beads/ directory artifact they are defined in (using the absolute directory path).
- **Agent**: String artifacts that use their agent name for their ID string.
  - Link to their chat transcript file artifacts with link type "created".
  - Link to a diff file artifacts that are associated with file changes that agent made with link type "created".
  - Link to a plan file artifact, if they created a plan.
  - Link to one or more question file artifacts, if they asked any questions.
- **Agent Thoughts**: Individual agent thoughts that will likely be string artifacts, but I'm not sure how this will
  work. I want you to lead the design on this one. Just make sure it looks beautiful!
  - Link to the artifact associated with the agent that had this thought.

### TUI Changes

- We should add a new `A` keymap that works from every tab and triggers a new artifacts panel to pop up. Some
  requirements for this panel are listed below.
- The `A` keymap should launch the artifact panel with the root directory artifact open when launched from the AXE tab;
  it should open the current ChangeSpec's artifact when launched from the CLs tab; and it should open the current
  agent's artifact when launched from the Agents tab.
- This panel will be powered by tree-based navigation, where artifacts are the nodes of our tree. In other words, at any
  given point while navigating the artifacts panel, we are looking at either a artifact or an artifact.
- In addition to tree-based navigation, when viewing an artifact, we should be able to navigate to any artifact that
  artifact is linked to.
- We will likely have to handle string artifacts and file artifacts slightly differently (perhaps in a custom fashion
  that is specific to each supported string artifact).

### Things the New Artifacts Panel will Obsolete

- The "Agent Run Log" panel, triggered by the `A` keymap on the CLs tab, will be made obsolete since we should be able
  to use the NEW `A` keymap to open the current ChangeSpec in the artifacts panel.
- The file and thinking panels on the Agents tab.
- Make sure we make it very clear what artifacts are linked to ChangeSpec from the CLs and agents from the Agents tab to
  (MORE than) make up for these obsoleted features.

### The NEW `sase artifact` Command

- Should allow you to add,remove,list,show in detail, and graph (based on their relationships using some graph
  framework--you figure this out) artifacts.
- Should have a corresponding `/sase_artifact` xprompt skill associated with it. See how the `/sase_agent_status` skill
  works for inspiration.

### DYNAMIC MEMORY
- @.sase/memory/long-generated-skills.md (memory/long/generated_skills, matched: `xprompt skill`)