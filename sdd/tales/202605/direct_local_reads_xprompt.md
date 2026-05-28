---
create_time: 2026-05-28 09:01:41
status: done
prompt: sdd/prompts/202605/direct_local_reads_xprompt.md
---
# Plan: Direct Local Helper Calls in `xprompts/reads.md`

## Goal

Remove the Jinja escape hack in `xprompts/reads.md` so the markdown-local helper can be called directly as
`#_article_search_agent`, while preserving the existing multi-runtime article-search workflow. Verify the change by
running the workflow through `sase run -d` for a fresh episodic agent memory reading request.

## Findings

- `xprompts/reads.md` defines `_article_search_agent` in markdown frontmatter and currently invokes it as
  `#{{ "_" }}article_search_agent` in the first three segments.
- The local runtime path already supports direct helper references:
  - markdown xprompt loading preserves `local_xprompts`;
  - `expand_single_xprompt()` expands owner-local helpers before multi-agent segment splitting;
  - `expand_multi_agent_xprompts()` produces the expected four segments when the file body is tested with direct
    `#_article_search_agent` calls.
- The hack therefore appears to be a source-level workaround that should be removed and covered by a file-specific
  regression, rather than a broad parser rewrite.
- In this workspace, repo-local xprompts are project-namespaced, so the checked command should use `#sase/reads(...)` or
  equivalent direct-reference syntax.

## Implementation

1. Update `xprompts/reads.md`.
   - Replace each `#{{ "_" }}article_search_agent` occurrence with `#_article_search_agent`.
   - Leave the local helper definition, per-agent `%name`, `%model`, and `%g:read` directives unchanged.

2. Add focused regression coverage.
   - Add a test that loads the checked-in `xprompts/reads.md`.
   - Assert the file uses direct `#_article_search_agent` references and no longer contains the Jinja escape.
   - Expand it through the multi-agent xprompt path and assert:
     - four segments are produced;
     - no `#_article_search_agent` helper reference remains;
     - the three research-agent segments contain the shared article-search instructions.

3. Verify locally.
   - Run the focused tests around markdown-local helpers and the new `reads.md` regression.
   - Run `just install` if the workspace install needs refreshing, then run `just check` per repo instructions because
     source files changed.
   - Run the requested workflow with `sase run -d` against the local installed CLI, using a topic about episodic agent
     memory, and inspect the launch output/status enough to confirm the workflow started.

## Risk

- The most likely failure mode is project namespacing: from this SASE workspace the prompt is `#sase/reads(...)`, while
  a non-project or home context may use a different visible name. The regression should exercise the loader object
  directly so it is not brittle to the current project name.
- The workflow launches real background agents. The validation step should confirm launch success and capture the
  started PID/name, but not block indefinitely on agent completion.
