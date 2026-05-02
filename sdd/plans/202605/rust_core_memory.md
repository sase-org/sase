---
create_time: 2026-05-01 16:37:24
status: done
prompt: sdd/prompts/202605/rust_core_memory.md
---
# Plan: Short-Term Memory for Rust Core Backend Boundary

## Goal

Add always-loaded agent memory that makes the backend ownership boundary explicit: backend logic that a future web app
would need in order to replicate TUI behavior should live in the sibling Rust core repo (`../sase-core`) instead of
being implemented only inside Python TUI code or duplicated for each frontend.

## Context

The current short-term memories cover build/run commands, glossary, gotchas, and workspace layout. None of them states
the architectural rule that shared backend/domain behavior belongs in the Rust core. `AGENTS.md` is the always-loaded
index for short-term memory, so a new file under `memory/short/` must also be added to that Tier 1 list to be effective.

The sibling `../sase-core` repo already positions `crates/sase_core` as the pure-Rust backend consumed through
`sase_core_rs`. It contains shared logic for ChangeSpec parsing, query evaluation, agent artifact scanning, status
behavior, notifications, cleanup, launch, and git-query helpers. The new memory should reinforce this direction without
claiming every UI action belongs in Rust.

## Implementation

1. Create a concise `memory/short/rust_core_backend_boundary.md` file.
2. State the default rule: shared backend/domain logic belongs in `../sase-core/crates/sase_core`; Python/TUI code
   should call through the Rust binding or thin adapter rather than reimplementing the logic.
3. Define the litmus test: if a web app, CLI, editor integration, or another frontend would need the behavior to match
   the TUI, treat it as core backend logic.
4. Clarify exceptions: presentation-only Textual UI state, keybindings, layout, widget rendering, and Python glue can
   stay in this repo.
5. Mention expected cross-repo workflow at a high level: update Rust wire/API/bindings/tests in `../sase-core`, then
   update Python callers/adapters in this repo.
6. Add the new file to the Tier 1 short-term memory list in `AGENTS.md`.

## Verification

- Read the new memory and `AGENTS.md` to confirm the wording is clear and always loaded.
- Run `just check` because the repo instructions require it after file changes in this repo.
