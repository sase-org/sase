---
plan: sdd/tales/202605/multi_prompt_xprompt_prompt_part.md
---
  We recently started treating multi-prompt xprompts as standalone workflows (see recent sase chats). Can you help me revert this change?  If one of these xprompts is used in a prompt that has other context (e.g. other xprompts or user text), then that context should just be rendered with the first prompt listed in the multi-prompt xprompt (except for the VCS x prompt workflow, if present, which is prepended to all prompts in the multi-prompt xprompt). In other words, the first prompt is the 'prompt_part' for that xprompt. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
