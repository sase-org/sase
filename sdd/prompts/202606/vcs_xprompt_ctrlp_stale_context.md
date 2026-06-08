---
plan: sdd/tales/202606/vcs_xprompt_ctrlp_stale_context.md
---
 The prompt input widget supports the `<ctrl+n/p>` keymaps to pre-fill the prompt input bar with the next/previous VCS xprompt workflow invocation that was made (by looking at what VCS xprompt workflow were invoked in previous prompts). This works, but has some problems. Namely:

- When I use `<ctrl+p>` to select the previous VCS xprompt workflow, type out my prompt, and then press `<enter>` (to launch the agent), the TUI receives a toast informing the user that an agent was launched but in the wrong workspace (the toast shows the project that corresponded with the VCS xprompt workflow that was shown in the initial prompt---e.g. `sase` if the user used the `<ctrl+space>` keymap, `#gh:sase ` was shown in the prompt input, and they pressed `<ctrl+p>` to pre-fill the previously used VCS xprompt workflow).
- Also (and I think this problem is probably related), if the user presses `<ctrl+space>` after launching an agent whose VCS xprompt workflow was pre-filled using `<ctrl+p>`, the VCS xprompt workflow that was just used should be populated in the prompt input widget, but the previously logged VCS xprompt workflow is used instead.

Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
 