---
create_time: 2026-05-07 14:46:41
status: wip
prompt: sdd/prompts/202605/xprompt_lsp_dedup_snippets.md
---
# Plan: Deduplicate xprompt LSP completion rows

## Context

The Python `sase lsp` command is a launcher. The completion behavior lives in the sibling Rust repo at `../sase-core`,
mainly:

- `crates/sase_core/src/editor/completion.rs` builds filtered xprompt completion candidates from catalog entries.
- `crates/sase_xprompt_lsp/src/server.rs` converts those candidates into LSP completion items and currently appends
  extra xprompt snippet items when the client advertises snippet support.

The duplicate menu rows in Neovim come from that second step: for each xprompt with inputs, the server returns the base
text candidate plus separate `(...)` and `:` snippet candidates. The desired behavior is one completion row per xprompt,
and that row should be a snippet with the correct insertion skeleton.

## Desired Expansion Rules

For xprompt completion candidates in snippet-capable clients:

- No required inputs: insert `#foo `, leaving the cursor after the trailing space.
- One required input whose type is not `text`: insert `#foo:`, leaving the cursor after the colon.
- One required input whose type is `text`: insert `#foo::`, leaving the cursor after the second colon.
- Multiple required inputs: insert `#foo($0)`, leaving the cursor inside the parentheses.

Optional inputs do not force an argument skeleton.

## Implementation Plan

1. Keep the catalog filtering and token matching in `sase_core` as the source of truth for which xprompts match. Do not
   duplicate ranking or prefix logic in the LSP layer.
2. Change the xprompt completion branch in `crates/sase_xprompt_lsp/src/server.rs` so that, when snippet support is
   enabled and the context is `Xprompt`, it returns exactly one snippet completion item per filtered candidate instead
   of first returning normal text items and then appending snippet variants.
3. Add a small helper in the LSP server that maps an `XpromptAssistEntry` to the requested single snippet skeleton using
   required inputs only. This avoids changing TUI snippet skeleton behavior, code actions, or argument assist.
4. Preserve non-xprompt completion behavior: directives may still append directive snippets, file completions remain
   text/folder items, argument completions remain unchanged, and non-snippet clients can continue to receive the plain
   fallback completion items.
5. Add focused Rust tests in `crates/sase_xprompt_lsp/src/server.rs` for the four xprompt skeleton cases and for the
   one-row-per-xprompt invariant. The tests should assert `CompletionItemKind::SNIPPET`, `InsertTextFormat::SNIPPET`,
   and the replacement `new_text`.
6. Run the targeted Rust tests for the LSP crate first. Then run the repo-level Python check required by this workspace
   instructions after any changes in `sase_100`; if only the plan file changed there, `just check` is still required by
   the local instruction unless it proves unavailable or blocked.

## Risks

The main compatibility question is snippet support. The requested Neovim behavior depends on snippet-capable completion
clients, so the implementation should optimize that path while keeping the existing plain completion fallback for
clients without snippet support. Another risk is changing shared `sase_core` skeleton helpers that the TUI and code
actions use; keeping the new single-row snippet policy in the LSP server avoids that blast radius.
