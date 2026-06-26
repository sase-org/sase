---
plan: sdd/epics/202606/inline_short_term_memory.md
---
 Not all LLM providers support using the @ symbol as a prefix for file paths to include the contents of those files. Can you help me start inlining the contents of short-term memory files instead of using the `@` symbol?

- Memory Markdown files will be expected to have an H1 section and zero or more H2 sections. Each H2 section may have zero or more H3 sections. No sections of level H4, H5, or above should be allowed. 
- The H1 section contents should be used in an H3 section header that is added to the AGENTS.md file (in the short-term memory section) by the `sase memory init` command. This section header should be of the form `### memory/foobar.md (<foobar_h1_header_title_goes_here>)`.
- The contents of the memory file should be inserted in this H3 section. Every H2 header that was in the memory file should be converted to an H4 header. Every H3 header that was in the memory file should be converted to an H5 header.
- Also, make sure that the `sase memory init` command now ensures that all LLM providers have the same exact file contents for their AGENTS.md file equivalent (e.g. CLAUDE.md). No more `@AGENTS.md` file references.
- Once you finish your work, you should run the `sase memory init` command to initialize your changes (do the same for the `~/projects/github/bobs-org/bob-cli/` repo--i.e. run the `sase memory init` command in that directory too).

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 