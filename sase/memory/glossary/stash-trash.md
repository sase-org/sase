---
keyword: Stash Trash
---

Stash Trash is the bounded, transactional recovery bin for drafts deliberately discarded
from the [[glossary:prompt-stash]]. It surfaces as the Stash tab's Trash view in the
Prompts overlay (the 🗑️ chip on the Stash tab, or `t`; `t`/`Esc` return to Stash),
newest-deleted-first with the deletion age visible, and restores move rows back to Stash
while the overlay stays open. It holds at most `ace.prompt_stash.trash_limit` entries
(default 100, an entry-count limit; zero disables recovery). Overflow evictions and
lowered-limit reconciliations permanently delete oldest-first and are always surfaced.
Successful unpinned stash restores never enter Trash, and history deletion remains
outside the overlay.
