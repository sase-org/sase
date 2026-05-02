---
plan: sdd/epics/202605/pyvision_alias_pragmas.md
---
 There are a lot of pyvision pragmas throughout this codebase that exist only because pyvision doesn't detect symbol usage in outside files when they use imports like `from foo import bar as b`
and then reference the symbol like `b.some_symbol`. Run the `rg "# pyvision: tests/"` command for context. Can you help me fix pyvision (in my chezmoi repo and then vendor back into this repo) and, while
we are improving pyvision, also disallow pragmas to reference test files in the future.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`)