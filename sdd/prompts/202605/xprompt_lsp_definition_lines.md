---
plan: sdd/tales/202605/xprompt_lsp_definition_lines.md
---
 Jump-to-definition is finally working for our new LSP server and nvim. I have one last problem: When we jump to YAML files that are not xprompt workflows (ex: sase.yml or default_config.yml files), we currently jump to line 1 of the file. Instead, we should be jumping to the exact line that the xprompt in question is defined on. Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
