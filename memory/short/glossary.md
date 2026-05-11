# Glossary

**ChangeSpec**  
Represents a single CL/PR. Stored in `.gp` files at `~/.sase/projects/<project>/`. Sections: NAME, DESCRIPTION, PARENT,
CL/PR, STATUS, COMMITS, HOOKS, COMMENTS, MENTORS. Active specs in `<project>.gp`; terminal ones (Submitted, Archived,
Reverted) in `<project>-archive.gp`. Status lifecycle: WIP → Draft → Ready → Mailed → Submitted.

**ChangeSpec COMMITS Drawer**  
A line of the form `| <NAME>: <FILE_PATH>` under a ChangeSpec COMMITS entry.

**Multi-agent xprompt**  
An xprompt whose body contains `---` segment separators (outside fenced blocks). Normal user prompts can also use `---`
to create multi-agent prompts (i.e. prompts that result in the prompt being split in order to launch one agent for each
part of the prompt).

**Root Agent/Workflow Entry**  
Any agent row entry on the "Agents" tab of the `sase ace` TUI that has child entries.

**xprompt**  
Triggered with `#foo` in agent prompts. Defined in an xprompts/ directory (.md or .yml file) or in
~/.config/sase/sase.yml (`xprompts` field).

**xprompt Part**  
.md file → single `prompt_part` step with the file's content.

**xprompt Workflow**  
.yml file → multiple steps (`prompt_part`, `python`, `bash`, etc.).
