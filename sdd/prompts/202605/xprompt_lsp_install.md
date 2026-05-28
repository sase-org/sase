---
plan: sdd/tales/202605/xprompt_lsp_install.md
---
 I'm still seeing the following nvim LSP errors in the xprompts/reads.md file even after our recent attempts to fix these. Can you help me diagnose the root cause of this issue and (finally) fix it? I think the problem is that we depend on a local target/debug/ binary path, but we should be installing `sase-xprompt-lsp` locally (e.g. when the `install_sase_github` script is run. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


```
Unknown xprompt `_article_search_agent`
Unknown xprompt frontmatter field `xprompts` will be ignored
```