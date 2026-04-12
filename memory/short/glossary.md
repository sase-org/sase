# Glossary

- **ChangeSpec**: Represents a single CL/PR. Stored in `.gp` files at `~/.sase/projects/<project>/`. Sections: NAME,
  DESCRIPTION, PARENT, CL/PR, STATUS, COMMITS, HOOKS, COMMENTS, MENTORS. Active specs in `<project>.gp`; terminal ones
  (Submitted, Archived, Reverted) in `<project>-archive.gp`. Status lifecycle: WIP → Draft → Ready → Mailed → Submitted.
- **ChangeSpec COMMITS Drawer**: A line of the form `| <NAME>: <FILE_PATH>` under a ChangeSpec COMMITS entry.
- **xprompt**: Triggered with `#foo` in agent prompts. Defined in an xprompts/ directory (.md or .yml file) or in
  ~/.config/sase/sase.yml (`xprompts` field).
- **xprompt Part**: .md file → single `prompt_part` step with the file's content.
- **xprompt Workflow**: .yml file → multiple steps (`prompt_part`, `python`, `bash`, etc.).
