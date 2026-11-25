---
keyword: Prompt Composer
aliases:
  - composer
  - prompt bar
  - prompt input widget
---

A prompt composer is sase's bottom-docked TUI prompt-authoring widget (`PromptInputBar`)
whose vim-mode panes draft agent prompts, Plan Feedback, Coder Prompt replies, and bound
macro or snippet definitions (`✎ <ref>` chip; `gw` writes back). In prompt mode it holds
a **prompt stack**: one or more panes in top-to-bottom launch order, each holding one
agent segment (a `#name` macro swarm stays one pane until launch). Loaded text splits
into panes at top-level `---`; a typed `---` stays literal and `g-` adds a pane.
`gj`/`gk` move focus and `gJ`/`gK` reorder; `Enter` opens the submit chooser and
`g<enter>` launches only the active pane. Pane order alone never sequences agents — a
bare `%wait` waits on the pane above. `Ctrl+S` stashes a pane and `gs` the whole stack
to the [[glossary:prompt-stash]]. At most one pinned auxiliary pane (snippet `gt`,
mini-macro `gx`) edits a definition and never launches.

Its **property panel** (`FrontmatterPanel`; the border title and docs call it the
frontmatter panel; `g=` toggles it) sits above the stack and edits the stack's shared
YAML frontmatter as structured fields (`name`, `description`, `input`, `macros`, …) with
an `a` property picker and an `R` raw-YAML view. Local `_helper` macros declared there
complete in every pane, and a single-pane launch re-attaches the shared frontmatter; on
a mini-macro pane the panel switches to that macro's own frontmatter scope.

Distinct from the read-only Agents-tab prompt panel, the Prompts overlay, the
post-submit Prompt Inputs panel, and external `$EDITOR` sessions. Plan Feedback and
Coder Prompt reuse the widget as a single pane without a stack or property panel.
