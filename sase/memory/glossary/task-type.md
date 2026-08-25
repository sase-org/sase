---
keyword: Task Type
aliases:
  - task type
---

A task type is the required, plugin-extensible flavor of a task bead — `bug`, `ci`,
`feature`, `flake`, `memory`, the project-local `flag` type, and plugin slugs such as
`github`. It is distinct from the bead's issue type (`plan`, `phase`, `task`). New tasks
take `-T "task(<slug>)"` plus `-f/--field` values; the type is immutable after create.
The catalog is assembled from builtins, `sase_task_types` plugins, and `bead.task_types`
project config, then snapshotted to `sase/task_types.json` so generated instructions
stay a function of committed files and Required Plugin entries rather than whichever
optional plugins happen to be installed.
