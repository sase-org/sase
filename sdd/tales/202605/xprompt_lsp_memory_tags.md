---
create_time: 2026-05-24 10:04:55
status: done
prompt: sdd/prompts/202605/xprompt_lsp_memory_tags.md
---
# Plan: Make xprompt LSP diagnostics honor implicit memory/long tags

## Context

Opening `memory/long/generated_skills.md` in Neovim currently reports:

`Xprompt keywords are only matched dynamically when tags include `memory``

That warning is correct for ordinary xprompt markdown, because frontmatter `keywords` only participate in dynamic memory
matching when the xprompt has the `memory` tag. It is a false positive for `memory/long/*.md`: both Python and Rust
catalog loading already treat those files as memory xprompts and synthesize `tags: memory` when a `keywords` frontmatter
field is present.

The diagnostic is produced in `sase-core` by `crates/sase_core/src/editor/frontmatter.rs`. Today that validation only
sees document text, so it cannot distinguish a normal `xprompts/foo.md` file from a `memory/long/foo.md` file. The LSP
server already has the URI at publish time.

## Goal

Make the xprompt LSP aware that markdown documents opened from a `memory/long` directory have an implicit `memory` tag,
while preserving the existing `missing_xprompt_memory_tag` warning for all other xprompt markdown files with `keywords`
and no explicit `tags: memory`.

## Design

1. Add source-path awareness to the editor document model in `sase-core`.
   - Keep `DocumentSnapshot::new(text)` as the default text-only constructor for existing callers and tests.
   - Add a path-aware constructor, likely `DocumentSnapshot::with_source_path(text, path)`.
   - Expose a small predicate on `DocumentSnapshot` for implicit memory-tag context, backed by exact path components: a
     markdown file whose parent path contains `memory/long`.

2. Teach frontmatter keyword validation about implicit memory tags.
   - Keep `tags_contain_memory(mapping)` unchanged for explicit YAML tags.
   - Suppress `missing_xprompt_memory_tag` when either explicit tags include `memory` or the document source path is a
     `memory/long/*.md` path.
   - Continue validating keyword shape errors regardless of path.

3. Pass URI file paths from the LSP server into diagnostics.
   - Add a URI-aware diagnostics helper in `crates/sase_xprompt_lsp/src/server.rs`.
   - For `file://` URIs, construct the document with the URI path.
   - For non-file URIs, keep text-only behavior so warnings remain conservative.
   - Use the URI-aware path from `publish_document_diagnostics`; keep existing text-only helper behavior for unit tests
     that do not model a file.

4. Add targeted tests.
   - Core editor test: text-only markdown with `keywords` and no `tags: memory` still warns.
   - Core editor test: the same text with a `memory/long/foo.md` source path does not warn.
   - LSP/server or JSON-RPC test: publishing diagnostics for `file:///.../memory/long/foo.md` does not include
     `missing_xprompt_memory_tag`, while publishing the same content for a non-memory path still does.

5. Verify.
   - Run focused Rust tests for the editor diagnostics and LSP server tests.
   - Run formatting checks for touched Rust files.
   - If the primary Python repo receives any non-plan changes, run its required `just install` and `just check`; this
     change is expected to be in the sibling `sase-core` repo plus this submitted plan file only.
