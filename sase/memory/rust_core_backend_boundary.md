---
type: core
parent: AGENTS.md
---

# Rust Core Backend Boundary

Shared backend and domain behavior belongs in the `sase_core` crate of the linked
`sase-core` repo; open it with `sase repo open sase-core` and work in the printed path.
Python and TUI code in this repo should call through the Rust binding (`sase_core_rs`)
or a thin local adapter instead of reimplementing core logic here. A binding that sase
calls also needs sase's `sase-core-revision.txt` CI pin moved past its sase-core commit
(see `docs/rust_backend.md`).

Use this litmus test: if a web app, CLI, editor integration, or another frontend would
need the behavior to match the TUI, treat it as core backend logic.

Presentation-only Textual state, keybindings, layout, widget rendering, and Python glue
can stay in this repo. When a change crosses the boundary, update the Rust wire/API,
bindings, and tests in the linked `sase-core` checkout, then update the Python callers
or adapters here.
