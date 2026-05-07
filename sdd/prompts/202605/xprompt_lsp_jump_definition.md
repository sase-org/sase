---
plan: sdd/epics/202605/xprompt_lsp_jump_definition.md
---
 We recently implemented an LSP server for sase xprompts. Can you help me implement jump-to-definition so the user can jump to the file where the xprompt under the cursor is defined? This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

