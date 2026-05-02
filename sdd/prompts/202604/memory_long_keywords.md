---
plan: sdd/tales/202604/memory_long_keywords.md
---
Can you help me add support for the `keywords` field in the frontmatter of memory/long/ files, which might live in the
top-level directory of a project directory or in a global or project-local .claude/, .gemini/, or .codex/ directory?

- When this keyword is found in one of these files, we should automatically make memory xprompts available for use (and
  dynamic injection) of the form `#memory/long/<name>` where `<name>` is the basename of the memory/long/ markdown file
  and the xprompt expands to the full contents (using `cat` with xprompt shell substitution)
- Get rid of the existing `#memory/` xprompts defined in the src/sase/default_config.yml file in favor of adding this
  new `keywords` field to the memory/long/ markdown files in this repo.

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

DYNAMIC MEMORY: @/home/bryan/tmp/sase/sase*dynamic_memory_ghsbpnu*.md
