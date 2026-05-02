---
plan: sdd/tales/202603/fix_insert_mode_prettier_freeze.md
---
It looks like prettier can still crash the prompt input widget, but now (see recent, related git commits) it happens
when typing text (not in NORMAL) mode. Can you help me diagnose the root cause of this issue and fix it? I think it only
seems to happen when the prompt is large. Think this through thoroughly and create a plan using your `/sase_plan` skill
before making any file changes.
