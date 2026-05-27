---
create_time: 2026-05-27 16:44:03
status: done
prompt: sdd/prompts/202605/reads_xprompt_12.md
---
# Plan: `reads` Multi-Agent XPrompt

## Goal

Add `xprompts/reads.md`, a markdown-defined multi-agent xprompt for article discovery. It should launch three parallel
search agents using Gemini, Claude, and Codex, then launch a fourth consolidation agent after all three finish.

## Design

- Define a markdown multi-agent xprompt so it is invoked as `#!reads(...)`.
- Use typed inputs:
  - `topic`: free-text reading request.
  - `notes`: free-text list of reference-note paths, defaulting to the five `~/org/*.zo` files used by the existing
    `bas.gem`, `bas.cld`, and `bas.cdx` reference chats.
- Give each research agent the same task shape from the `bas.*` chats:
  - Read the requested reference note files first.
  - Treat URLs/titles already present in those notes as off-limits, including unread entries.
  - Search the current web for recent, medium-to-long articles matching the user's topic.
  - Return ranked recommendations with links, dates when available, and a short relevance rationale.
- Use the new indexed-agent-name syntax for durable, reusable names:
  - `%name:reads.gem-@`
  - `%name:reads.cld-@`
  - `%name:reads.cdx-@`
  - `%name:reads.final-@`
- Make the fourth segment wait on the latest concrete member of each first-agent family:
  - `%wait:reads.gem-@`
  - `%wait:reads.cld-@`
  - `%wait:reads.cdx-@`
- Use `{{ wait_chats }}` in the consolidation prompt, but emit it through a Jinja raw block in `reads.md`. This avoids
  dispatch-time xprompt rendering trying to resolve `wait_chats` before the waited-on agents exist. The child runner
  will render the literal `{{ wait_chats }}` after waits complete.

## Verification

1. Expand/list the xprompt enough to catch frontmatter or fan-out syntax errors.
2. Run focused parser/launcher tests if the xprompt stresses indexed waits or multi-agent expansion.
3. Run `just install`, then `just check` because this repo requires it after file changes.
4. Verify the real workflow with `sase run -d '#!reads(...)'` using a request for new articles about agent memory.

## Risks

- `wait_chats` must remain literal until the fourth agent starts; otherwise `StrictUndefined` will fail during xprompt
  expansion.
- Reusing a single indexed base for all three research agents would only let `%wait:reads-@` refer to the latest one, so
  the implementation should use separate indexed bases per runtime.
