---
plan: sdd/tales/202605/retry_suffix_and_keymap.md
---
 Can you help me improve sase's agent "retry" concept?

- We currently append a `.<N>` to an auto-generated agent-name. Let's start appending `.r<N>` instead.
- We currently use the `,r` keymap to trigger the retry prompt on the "Agents" tab of the `sase ace` TUI. Let's start
  using `r` instead.

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
