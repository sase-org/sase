---
plan: sdd/epics/202606/alt_brace_syntax.md
---
 Can you help me migrate the existing `%(A, B, ...)` short-hand syntax for `%alt(A, B, ...)` to `%{A | B | ...}`?

- Make sure that we add good syntax highlighting for this new syntax to both the prompt input widget and nvim (via treesitter or LSP or however we do it).
- Add some logic to the prompt input widget and nvim that auto-completes the `}` when `%{` is typed and auto-deletes it if the `{` (which is still directly to the left of the `}`) is removed.
- Also, we should expand `|` to ` | ` when it is typed inside of `%{}` and the character before the typed `|` was not a space.
- For example, if the user types `%{foo ,bar, and baz|` in the prompt input widget or in nvim, then the text that should actually be shown on the screen after the user stops typing is `%{foo, bar, and baz | }` with the user's cursor right before the `}`.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

