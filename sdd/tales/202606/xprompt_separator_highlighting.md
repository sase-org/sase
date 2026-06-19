---
create_time: 2026-06-19 07:25:36
status: wip
prompt: sdd/prompts/202606/xprompt_separator_highlighting.md
---
# Plan: Distinct LSP Syntax Highlighting for Multi-Agent xprompt `---` Separators

## Goal

When an xprompt markdown file (or any prompt buffer) defines a **multi-agent prompt**, the `---` lines that split the
body into per-agent segments should be rendered with their own beautiful, distinct color — visually announcing "this is
where the prompt splits into separate agents."

Today those lines get no special treatment: in a markdown buffer they render as a generic thematic-break /
setext-heading underline (dull grey, or worse, mis-colored as a heading), giving the author no signal that the line is a
_semantic_ boundary that fans out into multiple agents.

This is a **highlight-only** feature. It must not change splitting behavior, and the thing that is highlighted must be
_exactly_ the set of lines that actually cause a split — never more, never less.

## Product context & design principles

- **Highlight == real behavior.** The separator highlight must be driven by the _same_ code path that the launcher uses
  to split a multi-agent prompt. If a `---` is inside a fenced code block, inside YAML frontmatter, or otherwise not a
  real separator, it must **not** light up. This makes the highlight a trustworthy preview of fan-out, and prevents
  drift between "looks like a split" and "is a split."
- **Single source of truth in the Rust core.** Per `memory/rust_core_backend_boundary.md`, any behavior a future
  frontend (VS Code, web editor, etc.) would need to match belongs in `sase-core`. Separator detection is exactly that.
  We compute separator ranges in `sase_core` and surface them through the existing Rust LSP server (`sase_xprompt_lsp`)
  as **LSP semantic tokens**. Every LSP-speaking editor then gets this for free; the Neovim plugin only owns the
  _color_.
- **Uniform across runtimes / frontends.** Nothing here is editor-specific in the core; the only per-editor piece is
  mapping the token type to a color.
- **Beautiful & distinct.** The separator gets a dedicated, saturated color that does not collide with markdown defaults
  or with existing sase palette roles (see Color Design below).

## Why LSP semantic tokens (and not vim regex / tree-sitter)

- The user explicitly asked for **LSP** highlighting, and prompt buffers are `markdown` / `sase_prompt` filetypes
  already served by the Rust LSP (`sase_xprompt_lsp`).
- Semantic tokens layer on top of (and out-prioritize) tree-sitter/syntax highlighting in Neovim (LSP semantic-token
  priority > tree-sitter priority), so our color reliably wins over the default markdown thematic-break/heading
  rendering — which is the whole point of "distinct."
- A **custom token type** (`xpromptSeparator`) gives us a dedicated highlight group we fully control, instead of
  overloading a standard type (`keyword`/`operator`) that editors auto-color.
- It keeps detection logic in one place (the core) and reuses the splitter, satisfying the highlight-==-behavior
  principle. A regex/tree-sitter approach would duplicate (and inevitably drift from) the fence/frontmatter-aware
  splitting rules.

## Current state (verified during research)

- **Splitter (single source of truth):** `sase-core/crates/sase_core/src/agent_launch/mod.rs` —
  `split_multi_prompt_segments()` scans the body (after `prompt_body_after_frontmatter()`), treats a line as a separator
  when `line.trim() == "---"` and it is **not** inside a `fenced_block_ranges()` range. It already tracks the byte
  offsets internally but only returns the split _text_, not separator positions. These helpers are currently private.
- **Editor/position layer:** `sase_core/src/editor/` provides `DocumentSnapshot` with UTF-16-aware
  `byte_range_to_range(start, end) -> EditorRange` and `EditorPosition/EditorRange`. The LSP handlers build a
  `DocumentSnapshot`, call an `editor_*` function, and convert via `sase_xprompt_lsp/src/lsp_convert.rs`.
- **LSP server:** `sase-core/crates/sase_xprompt_lsp/src/server.rs` (tower-lsp-server 0.21.1, lsp-types 0.97).
  `initialize` advertises completion/hover/definition/code-action/execute-command; **no `semantic_tokens_provider`**.
  Handlers follow a clean pattern: look up the in-memory `OpenDocument`, bail on `!document.eligible`, then delegate to
  a helper. Eligible language IDs: `markdown` (gated to xprompt dirs / temp prompt files unless `allow_all_markdown`),
  `gitcommit`, `sase`, `sase_prompt`. Integration tests live in `crates/sase_xprompt_lsp/tests/jsonrpc_stdio.rs` (raw
  JSON-RPC over duplex streams).
- **Neovim plugin:** `sase-nvim/lua/sase/lsp.lua` launches the server (`sase lsp`, or `sase-xprompt-lsp`, or
  `$SASE_XPROMPT_LSP_CMD`) and builds client capabilities via `make_client_capabilities()` (which already includes
  semantic tokens). There is currently **no** `@lsp.type.*` mapping and **no** `nvim_set_hl` anywhere; the existing
  palette lives in `syntax/sase_gp.vim` (used for `.sase` files only).
- **No coupling blocker:** the primary `sase` repo splits via the Rust core and discovers the LSP binary at runtime
  (falling back to building the sibling `sase-core` crate). The Python binding (`sase_core_rs`) exposes an explicit
  subset that does **not** include `editor` functions, so a new Rust function used only by the LSP needs **no**
  Python-binding change. ⇒ **No code changes in the primary `sase` repo.**

## Scope of change (which repos)

1. **`sase-core` (Rust)** — the substance:
   - Detect separator spans (reuse the splitter).
   - Editor-layer wrapper returning `EditorRange`s.
   - Add the `semanticTokens/full` capability + handler to the LSP server.
   - Tests + CHANGELOG.
2. **`sase-nvim` (Lua)** — presentation only:
   - Map the custom token type to a beautiful highlight group; re-apply on colorscheme change.
   - README + a small test.
3. **`sase` (primary)** — **no code changes**; only the plan/bead artifacts under `sdd/`.

## Detailed design

### A. Core detection — `sase_core` (`agent_launch`)

Introduce a single public(-in-crate) function that returns the separator spans, derived from the _same_ line scan the
splitter uses, so the two can never disagree:

```rust
/// Byte spans (start, end), in ORIGINAL-document coordinates, of every `---`
/// line that acts as a multi-prompt separator: outside fenced code blocks and
/// after any YAML frontmatter. Each span covers only the trimmed `---` glyphs.
pub(crate) fn multi_prompt_separator_spans(prompt: &str) -> Vec<(usize, usize)>
```

Implementation notes:

- Reuse `prompt_body_after_frontmatter()`, `fenced_block_ranges()`, and the existing `line.trim() == "---"` +
  `position_in_ranges(...)` predicate. To map body-relative offsets back to the original document, add a tiny
  `prompt_body_offset_after_frontmatter()` (returns the byte offset where the body begins) so we avoid pointer
  arithmetic; have `prompt_body_after_frontmatter` remain the slice accessor.
- The highlighted span is the run of dashes only: leading whitespace excluded (compute via `len - trim_start().len()`),
  length is always 3 bytes since `trim() == "---"`. This keeps the highlight tight and clean even for `  ---  `.
- **Refactor for zero drift:** factor the per-line classification so `split_multi_prompt_segments` and
  `multi_prompt_separator_spans` share the exact same "is this a separator line?" decision (e.g. a shared inner scan, or
  a shared predicate). Existing splitter tests must continue to pass unchanged.
- Correctly handles CRLF (the `.trim()` predicate already does) and multibyte content before a separator (offsets are
  byte offsets, converted to UTF-16 later by `DocumentSnapshot`).

### B. Editor-layer wrapper — `sase_core` (`editor`)

Add the public API the LSP consumes (mirrors `editor_hover_at_position` etc.), and re-export it from `lib.rs` alongside
the other editor functions:

```rust
/// LSP-ready ranges of multi-prompt `---` separators in this document.
pub fn multi_prompt_separator_ranges(document: &DocumentSnapshot) -> Vec<EditorRange>
```

It reads the snapshot text, calls `multi_prompt_separator_spans`, and converts each byte span via
`document.byte_range_to_range(...)`, dropping any that fail to convert. (Add a small `pub(crate) fn text(&self) -> &str`
accessor on `DocumentSnapshot` if one is not already available.) This keeps the LSP crate thin and unaware of
`agent_launch` internals.

### C. LSP server — `sase_core` (`sase_xprompt_lsp`)

- **Legend (single source of truth):** define a module-level constant for the token type string `"xpromptSeparator"` and
  a `semantic_tokens_legend()` helper so the capability and the handler share the same type→index mapping (index 0, no
  modifiers). This avoids index drift.
- **Capability:** in `initialize`, add
  `semantic_tokens_provider: Some(SemanticTokensServerCapabilities::SemanticTokensOptions(...))` with that legend,
  `full: Some(Bool(true))`, `range: Some(false)`.
- **Handler:** implement `semantic_tokens_full(params) -> Result<Option<SemanticTokensResult>>` following the
  established pattern: look up the document, return `Ok(None)` if missing or `!document.eligible`, otherwise build a
  `DocumentSnapshot`, call `multi_prompt_separator_ranges`, and return `SemanticTokensResult::Tokens`. A document with
  zero separators returns an empty token set (clears stale tokens) rather than `None`.
- **Encoder:** add `lsp_convert::semantic_tokens(ranges: Vec<EditorRange>) -> SemanticTokens` that sorts ranges by
  `(line, start)` and produces the LSP delta encoding (`delta_line`, `delta_start`, `length`, `token_type = 0`,
  `token_modifiers_bitset = 0`). Each separator span is single-line by construction, satisfying the LSP "tokens are
  single-line" rule.

### D. Neovim presentation — `sase-nvim`

- Neovim's default client capabilities already include semantic tokens, and Neovim core auto-starts semantic-token
  highlighting on attach when the server advertises the provider — so the tokens will flow without changing the client
  capability negotiation. The **only required** piece is giving the custom token type a color: define highlight group
  `@lsp.type.xpromptSeparator`.
- Add a tiny highlights module (e.g. `lua/sase/highlights.lua`) invoked from plugin setup that calls
  `vim.api.nvim_set_hl(0, "@lsp.type.xpromptSeparator", { fg = "#D75FFF", bold = true, ctermfg = 171 })` and re-applies
  it on a `ColorScheme` autocmd (so it survives colorscheme switches). Make the color overridable via a plugin config
  option so users can theme it.
- **Verification fallback:** confirm via the test (below) that tokens auto-apply; if a given Neovim setup does not
  auto-start them for this client, add an explicit `vim.lsp.semantic_tokens.start(...)`/capability nudge in the existing
  attach flow. (Expected unnecessary, but called out so implementation doesn't get stuck.)

### Color design (the "beautiful & distinct" decision)

I'm choosing a **luminous violet**: GUI `#D75FFF`, cterm `171`, **bold**.

- **Distinct from markdown defaults:** markdown thematic breaks/headings render as grey/comment, white, blue, or yellow
  — violet shares none of those, so the separator unmistakably pops.
- **Distinct within the sase palette:** the only nearby purples are muted/desaturated (`#AF87D7` timestamps, `#D7AFFF`
  reword, `#AF87AF` reserved). `#D75FFF` is markedly brighter and more saturated, so it won't be confused with them —
  and it deliberately avoids the pink family (`#FF87AF` entry-ref, `#FF87D7` pinned) so the separator isn't misread as a
  "reference."
- **Reads as structural/special:** a saturated violet signals "boundary / special construct," and bold ensures the short
  3-glyph token has visual weight.

This is a one-line, config-overridable choice — trivial to retune if you'd prefer the pink (`#FF5FD7`) or a cooler cyan;
violet is my lead recommendation for the best balance of beautiful + distinct + non-colliding.

## Testing strategy

- **`sase_core` unit tests (`agent_launch`):** `multi_prompt_separator_spans` returns correct spans for: two/three
  segments; separator inside a fenced block excluded; YAML frontmatter `---` excluded; leading/trailing whitespace on
  the separator line (`  ---  `); trailing separator; no separators ⇒ empty; CRLF line endings; multibyte (non-ASCII)
  text before a separator so the later UTF-16 conversion is exercised. Confirm existing splitter tests still pass after
  the shared-scan refactor.
- **`sase_core` editor test:** `multi_prompt_separator_ranges` yields the expected `EditorRange`s (correct 0-based line,
  UTF-16 character offsets, length 3).
- **`lsp_convert` unit test:** delta encoding for multiple, out-of-order separators across lines.
- **LSP integration test (`jsonrpc_stdio.rs`):** `initialize` advertises the semantic-tokens capability with the
  `xpromptSeparator` legend; `textDocument/semanticTokens/full` on a multi-agent prompt returns the expected encoded
  data; an ineligible document (e.g. non-xprompt markdown without `allow_all_markdown`) returns null/empty.
- **`sase-nvim` test (plain Lua, matching `tests/lsp_config.lua`):** the highlight group `@lsp.type.xpromptSeparator` is
  defined after setup; (smoke) a multi-agent prompt buffer yields a `textDocument/semanticTokens/full` response via
  `vim.lsp.buf_request_sync`.

## Validation / commands

- `sase-core`: `cargo fmt`, `cargo clippy`, `cargo test -p sase_core -p sase_xprompt_lsp` (run from the sase-core
  workspace).
- `sase-nvim`: run the repo's Lua test harness.
- Primary `sase` repo: no code changes ⇒ no `just check` required (plan/bead files under `sdd/` are exempt per
  `memory/build_and_run.md`).
- Manual smoke: open a multi-agent xprompt in Neovim (built/located LSP) and confirm the `---` lines render in violet
  while `---` inside a code fence and YAML frontmatter delimiters do not.

## Docs & housekeeping

- Update `sase-core/crates/sase_core/CHANGELOG.md` (Keep-a-Changelog) noting the new LSP `semanticTokens` capability for
  multi-prompt separators. Conventional-commit messages so release-plz bumps the version; the primary repo's
  `sase-core-rs>=0.1.1,<0.2.0` pin is unaffected (binary is discovered at runtime).
- Update `sase-nvim/README.md` to document the new highlight group `@lsp.type.xpromptSeparator`, its default color, and
  how to override it.

## Out of scope

- No change to splitting semantics or to what counts as a separator.
- No new highlighting for single-agent prompts (they have no separators).
- No `range`/`delta` semantic-token requests (full-document only is sufficient for these files).
- No changes to the primary `sase` Python package.

## Risks & mitigations

- **Drift between highlight and splitter** → mitigated by sharing one scan/predicate and testing both against the same
  fixtures.
- **Frontmatter offset mapping** → handled with an explicit body-offset helper (no pointer math).
- **Neovim not auto-starting tokens** → covered by the nvim test and a documented explicit-start fallback.
- **Color collisions / accessibility** → chosen to avoid existing palette roles; exposed as a config-overridable option.
