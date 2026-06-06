---
plan: sdd/tales/202606/prompt_completion_project_root.md
---
 Can you help me fix the way the `<ctrl+t>` and/or `<ctrl+r>` keymaps from the prompt input widget work?

- Namely, when used for file path completion and a relative directory is found to the left of the cursor, we should be
  searching the main/primary directory (or `<dirname>` if `#cd:<dirname>` was included in the prompt instead) for the
  project associated with the prompt, which is determined by the VCS xprompt workflow that is invoked from the prompt.
- We should NOT be searching the directory that `sase ace` was run from.
- For example, if the user were to type `#gh:bob-cli sdd/<ctrl+t>` they should see completion results from the
  `~/projects/github/bbugyi200/bob-cli/sdd/` directory.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
