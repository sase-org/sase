---
plan: sdd/tales/202605/init_memory_static_sibling_paths.md
---
 Can you help me improve the `sase init memory` command so that we only generate the `sase workspace open` instruction when at least one of the sibling repos in that sase.yml file does NOT use the `none` value for the `workspace.strategy` configuration field? Also, make sure that we clearly show which siblings should use a static path (make sure to include the path that should be used for each of these siblings) instead of a numbered workspace directory. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
