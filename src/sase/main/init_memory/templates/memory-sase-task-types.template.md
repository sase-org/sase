# Task Bead Types

Every task bead can carry a `task_type` drawn from this project's catalog. `sase bead task-type list` always shows the live catalog; read `sase memory read task_types:<slug> -r "<why>"` for one generated type in full. This note is the generated, always-current snapshot of the agent-creatable types below.

<!-- sase:strands -->

<!-- /sase:strands -->

## File Discovered Work As Task Beads

Unless your prompt explicitly forbids creating beads (epic phase workers, for example, must record `PROPOSED FOLLOW-UP:`
notes on their own bead instead), you can and SHOULD capture discovered follow-up work as sase task beads. Before
creating any task bead, you MUST use `/sase_new_task`.
