---
create_time: 2026-05-11 20:58:47
status: wip
prompt: sdd/prompts/202605/review_prompt_widget_blog.md
---
# Plan: Review Prompt Widget Blog Post Follow-up

## Context

The previous change added `docs/blog/posts/prompt-widget-and-nvim.md` as Post 9 in the Agentic Software Engineering
series, renumbered the roadmap post to Post 10, and updated the blog index, series hub, and nearby navigation links. The
request is to review that work and make justified improvements.

I checked the new post against:

- `src/sase/ace/tui/widgets/prompt_text_area.py`
- `src/sase/ace/tui/widgets/prompt_input_bar.py`
- `src/sase/ace/tui/widgets/_file_completion.py`
- `src/sase/ace/tui/actions/agent_workflow/_editor.py`
- `src/sase/history/prompt.py`
- `src/sase/history/file_references.py`
- `docs/ace.md`
- `docs/xprompt.md`
- `../sase-nvim/README.md`
- `../sase-nvim/lua/sase/*.lua`
- `mkdocs.yml`

## Findings

1. `mkdocs.yml` still lists the old final post as `Post 9` and does not include the new prompt-widget/nvim post. This
   means the explicit MkDocs navigation is stale even though the blog index and series hub were updated.

2. The new Post 9 says both `~/.sase/prompt_history.json` and `~/.sase/file_reference_history.json` use a sidecar lock
   plus atomic tempfile replacement. `prompt_history.json` does use a lock and atomic replacement, but
   `file_reference_history.json` currently uses atomic replacement without a sidecar lock. The post should avoid
   overstating concurrency guarantees.

3. The renumbered Post 10 updated its opening list of existing systems, but its later "Throughline" sentence still lists
   the covered orchestration pieces without the prompt input widget / Neovim plugin. That makes the new Post 9 feel less
   integrated into the series arc.

4. The rest of the new post's core factual claims match the implementation and sibling plugin docs: `Ctrl+T` completion
   modes, xprompt argument hints, `#@`, `Ctrl+G` editor handoff, `%edit`, `sase-nvim` LSP fallback behavior, YAML schema
   registration, and normal LSP go-to-definition are all represented in code/docs.

## Implementation Plan

1. Update `mkdocs.yml` under `nav > Blog`:
   - Insert `Post 9: Where You Type — The Prompt Input Widget and sase-nvim` pointing at
     `blog/posts/prompt-widget-and-nvim.md`.
   - Rename the final roadmap entry to `Post 10: What's Next — Shared Memory, Mobile, and the Web Surface`.

2. Edit `docs/blog/posts/prompt-widget-and-nvim.md` narrowly:
   - Replace the shared-history concurrency sentence with a more accurate split: `prompt_history.json` is locked and
     atomically replaced; file-reference history is the recency store used by both ACE and the plugin and is updated
     through SASE's file-history commands / atomic replacement.
   - Keep the post structure and voice intact.

3. Edit `docs/blog/posts/whats-next-memory-mobile-web.md` narrowly:
   - Add the prompt input widget / Neovim plugin to the later "Throughline" list of covered pieces.

4. Verify:
   - Run targeted `rg` checks for stale `Post 9: What's Next` navigation references.
   - Run `just install` if needed for this ephemeral workspace.
   - Run `just check` because project instructions require it after changes in this repo.
