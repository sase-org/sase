---
plan: sdd/tales/202606/prompt_history_ctrl_k_rebind.md
---
 The `<ctrl+.>` keymap that we recently added to the prompt input widget (see recent, related git commits) isn't working. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Fix approach

> Ctrl+. only works under the kitty keyboard protocol (CSI-u). In tmux without extended-keys, macOS Terminal.app, and other legacy setups it arrives as a plain ".", so the trigger silently inserts a period instead of opening history. How should we fix it?

- [x] **Rebind to a portable Ctrl+<letter>** — Replace Ctrl+. with a key that works in every terminal incl. tmux/legacy. Most robust; loses the "." mnemonic.
- [ ] **Keep Ctrl+. + add portable fallback** — Both keys open history: Ctrl+. still works on kitty-protocol terminals, the fallback covers everything else.
- [ ] **Keep Ctrl+. only; fix environment** — No code key change. Enable kitty protocol / tmux extended-keys instead. Wont help users on terminals that lack the protocol.

#### Q2: Portable key

> If we rebind or add a portable key, which Ctrl+<letter> should trigger prompt history? (These are currently free inside the prompt input.)

- [ ] **ctrl+o** — Mnemonic: Open history. Used elsewhere at app-level for fast-jump, but free while the prompt input is focused.
- [x] **ctrl+k** — Free in the prompt input.
- [ ] **ctrl+x** — Free in the prompt input.
- [ ] **N/A (chose keep-environment)** — Pick this if you selected the keep-Ctrl+.-only option above.

%xprompts_enabled:true