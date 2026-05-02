---
plan: sdd/tales/202603/fix_embedded_env_injection.md
---
I don't think the new unified `#commit`, `#propose`, and `#pr` xprompt workflows are working right. Can you help me
diagnose the root cause of this issue and fix it by first running an E2E test with the sonnet model (use the
`%model:sonnet` directive) using the `sase run -d` command? Once you've done that search the logs (use `sase logs` if
you need to). Think this through thoroughly and create a plan using your `/sase_plan` skill.

### Commit instructions

Use `ccommit` to commit changes in each repo after validation passes. Make sure to add this to your plan file.
