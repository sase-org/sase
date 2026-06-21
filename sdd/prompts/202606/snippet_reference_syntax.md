---
plan: sdd/tales/202606/snippet_reference_syntax.md
---
 Can you help me add support for a new `#[<snippet>]` syntax that can be used in sase snippet definitions to re-use another existing sase snippet named `<snippet>`? `<snippet>` should be able to accept xprompt-style arguments (if the snippet has placeholders like `$1`). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Arg syntax

> Where should arguments go in the new snippet-reference syntax?

- [x] **Inside brackets: #[name(a, b)] / #[name:a]** — The whole reference (name + xprompt-style args) is bracketed. Reuses the existing xprompt arg parser on the bracket body verbatim. Cleanest/most consistent. (Recommended)
- [ ] **Outside brackets: #[name](a, b) / #[name]:a** — Brackets wrap only the name; args trail after, mirroring #name(args) more literally.

#### Q2: Scope

> What scope should this plan cover? Snippets are resolved in BOTH Python (the ACE TUI + editor helper-bridge) and Rust (sase-core, served to editors via the LSP). The Rust-core boundary rule says shared behavior must stay in parity.

- [x] **Both Python and Rust now (full parity)** — Implement the resolution pass in src/sase (TUI + helper bridge) AND in sase-core (LSP), with mirrored tests. Honors the boundary rule; one coherent change. Larger plan. (Recommended)
- [ ] **Python (TUI) first, Rust as a tracked follow-up** — Ship the TUI behavior now; file a follow-up bead for LSP/editor parity. Editors would lag until the follow-up lands.

#### Q3: Missing ref

> When a #[ref] points at a snippet that does not exist (or forms a cycle), what should happen?

- [x] **Leave the #[ref] text literal** — Mirrors existing xprompt behavior for unknown #refs (see test_get_xprompt_snippets_leaves_unknown_nested_references_literal). Non-destructive, visible. (Recommended)
- [ ] **Drop the reference (expand to empty)** — Silently remove unresolved references from the template.
- [ ] **Skip the whole snippet** — Exclude any snippet that contains an unresolved reference from the catalog.

%xprompts_enabled:true