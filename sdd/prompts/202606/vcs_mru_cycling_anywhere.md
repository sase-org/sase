---
plan: sdd/tales/202606/vcs_mru_cycling_anywhere.md
---
 Can you help me make the `<ctrl+p/n>` keymaps in the prompt input widget work in more cases to change the
current VCS xprompt workflow that is invoked in the prompt (ex: `#gh:sase`) to the next/previous one from the VCS
xprompt workflow stack (i.e. list of VCS xprompt workflow invocations that were previously used in prompts)?

- We should support these keymaps anytime it is possible to replace a current VCS xprompt workflow with the
  next/previous one OR we are able to prepend the proper next/previous VCS xprompt workflow to the prompt (in other
  words, we should pretty much always support these keymaps in the prompt input widget).
- Make sure that only the current VCS xprompt workflow in the prompt (if any) is edited (by being replaced with the
  next/previous one).

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
