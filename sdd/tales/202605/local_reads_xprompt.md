---
create_time: 2026-05-28 08:23:32
status: done
prompt: sdd/prompts/202605/local_reads_xprompt.md
---
# Plan: Local Helpers for `xprompts/reads.md`

## Goal

Deduplicate `xprompts/reads.md` by factoring the repeated prompt used by the Gemini, Claude, and Codex research agents
into a local xprompt defined in that markdown file's frontmatter. The resulting `reads` xprompt must still launch the
same multi-agent research workflow and be runnable for a fresh article request about episodic agent memory.

## Current State

`xprompts/reads.md` is a markdown-defined multi-agent xprompt: its body has four `---`-separated segments. The first
three segments only differ by `%name` and `%model`; each repeats the same article-search instructions.

SASE already supports frontmatter-defined local xprompts for user-submitted multi-prompts and workflow-local xprompts
for YAML workflows. Markdown xprompt file loading, however, currently strips frontmatter and preserves only fields such
as `input`, `tags`, `description`, and `skill`; it does not attach frontmatter `xprompts:` definitions to the loaded
`XPrompt`.

## Implementation Approach

1. Extend the `XPrompt` model to carry markdown-file-local xprompts.
   - Add a `local_xprompts` field with an empty-dict default.
   - Preserve it when namespacing or converting an `XPrompt` into a `Workflow`.
   - Include it in local-xprompt serialization if needed by existing launch plumbing.

2. Teach markdown xprompt loaders to parse frontmatter `xprompts:`.
   - Reuse `parse_xprompt_entries` so local helpers support the same structured syntax as existing local xprompts.
   - Enforce the existing local-name rule that local names start with `_`.
   - Apply the same behavior to file-backed and plugin-backed markdown xprompts so the model is consistent across
     markdown xprompt sources.

3. Expand markdown-local helper references inside the owning xprompt's rendered content.
   - After the owning xprompt's normal argument substitution, resolve references to its `local_xprompts` before the
     multi-agent body is split into segments.
   - Keep the helper scope local: do not add `_...` helper names to the global catalog.
   - Preserve existing behavior for global xprompt references and multi-agent `---` splitting.

4. Refactor `xprompts/reads.md`.
   - Define one local helper, likely `_article_search_agent`, in frontmatter.
   - Replace the duplicated first-three-agent prompt bodies with `#_article_search_agent`.
   - Leave the per-agent `%name`, `%model`, and `%g:read` directives in each segment unless testing shows the group
     directive belongs inside the helper.

5. Add focused tests.
   - Loader test: a markdown xprompt file with frontmatter `xprompts:` loads local helpers.
   - Expansion test: a markdown/global xprompt with a local helper expands that helper without leaking it globally.
   - Multi-agent test: local helpers inside a multi-agent xprompt expand before segment splitting.

6. Verify.
   - Run the focused pytest tests.
   - Per repo instructions, run `just install` before checks if needed, then `just check` after file changes.
   - Run the `reads` xprompt with a request for recent medium-to-long articles about episodic agent memory and confirm
     the launch succeeds.
