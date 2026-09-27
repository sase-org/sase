---
keyword: Prompt Stash
aliases:
  - stash
---

A prompt stash is the per-user draft pile where sase's TUI parks prompt panes outside
prompt history: manual `Ctrl+S`/`gs` captures, restart stashes, and failed-launch
recovery rows. Stash rows keep their bundled pane order, frontmatter, cursor, project,
source, creation time, and pin. The stash surfaces as the Stash tab of the Prompts
overlay (`@`, `,@`, `Ctrl+G p`, the stash chip, empty `Ctrl+S`); on the Stash tab `@`
restores the newest draft, so `@@` pops the most recently stashed prompt. Rows
deliberately discarded from it move to [[glossary:stash-trash]] for bounded recovery
instead of permanent deletion.
