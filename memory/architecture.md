## Architecture

- **Project overview**: sase (Structured Agentic Software Engineering) is a Python toolkit for orchestrating AI agents.
- **Layout**: `src/sase/` (src layout with hatchling build backend)
- **Entry point**: `sase.main.entry:main` → `sase` CLI command
- **Config**: All tool config in `pyproject.toml` (ruff, mypy, pytest, coverage)
- **Testing**: `tests/` directory, mirrors `src/sase/` structure

### Glossary

- **ChangeSpec**: A structured specification that represents a single code change list (CL) or pull request (PR). Stored
  in `.gp` files at `~/.sase/projects/<project>/`, ChangeSpecs track what code changes are being made, why, their
  dependencies (via PARENT), and their lifecycle status. Key sections include NAME, DESCRIPTION, PARENT, CL/PR, STATUS,
  COMMITS, HOOKS, COMMENTS, and MENTORS. Active ChangeSpecs live in `<project>.gp`; terminal ones (Submitted, Archived,
  Reverted) are moved to `<project>-archive.gp`. Status lifecycle: WIP → Draft → Ready → Mailed → Submitted.
- **ChangeSpec COMMITS Drawer**: A line of the form `| <NAME>: <FILE_PATH>` that goes underneith a ChangeSpec COMMITS
  entry. There can be one or more of these.
- **xprompt**: Triggered with strings like `#foo` in agent prompts, where foo must be in an xprompts/ directory (several
  location supported) or in a ~/.config/sase/sase.yml file (see the `xprompts` field). If definded in an xprompts/
  directory, it must be a .md file or a .yml file.
- **xprompt Part**: If defined by a .md file, an xprompt is considered to be an "xprompt part" and is equivalent to
  defining the same prompt in a .yml file in a xprompts/ directory where the only step is a `prompt_part` step that has
  the same content as the .md file.
- **xprompt Workflow**: If defined by a .yml file, an xprompt is considered to be an "xprompt workflow" and can have
  multiple steps of any (ex: `prompt_part` allows you to expand `#foo` into some pre-defined content, `python` or `bash`
  let you run code, etc.).
