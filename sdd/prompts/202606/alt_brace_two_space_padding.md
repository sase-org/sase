---
plan: sdd/tales/202606/alt_brace_two_space_padding.md
---
 In the prompt input widget and in nvim (via our LSP support and sase-nvim plugin) currently, we support adding spaces around the `|` characters used for the alternation short-hand syntax automatically. Can you help me make it so we also add two spaces in-between the `{}` when the user types the first `{}` for an alternation? The cursor should be placed after the first space. Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 

### Additional Requirements

- We should not add the trailing "}" in nvim since there are other Neovim plugins that do that.