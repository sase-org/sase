---
plan: sdd/plans/202604/ctrlt_file_history_completion.md
---
Can you help me make the `<ctrl+t>` keymap in the prompt input widget, which currently handles xprompt / file completion
depending on the context, have a unique file completion behavior when there is no text before the cursor (e.g. at the
beginning or end of a line)?

- In this case, we should only show full file paths for file paths that have been referenced in other prompts.
- This means we are going to have to start storing a history of all referenced file paths to disk somewhere.
- We should store all file references in prompts that had an `@` prefix and all absolute file path references (i.e.
  starts with either `/` or `~/`).
- These file paths should be sorted by how recently they were used in other prompts. There should be no duplicates.

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
