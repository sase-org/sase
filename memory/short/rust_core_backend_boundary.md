# Rust Core Backend Boundary

Shared backend and domain behavior belongs in the sibling Rust core repo at `../sase-core/crates/sase_core`. Python and
TUI code in this repo should call through the Rust binding (`sase_core_rs`) or a thin local adapter instead of
reimplementing core logic here.

Use this litmus test: if a web app, CLI, editor integration, or another frontend would need the behavior to match the
TUI, treat it as core backend logic.

Presentation-only Textual state, keybindings, layout, widget rendering, and Python glue can stay in this repo. When a
change crosses the boundary, update the Rust wire/API, bindings, and tests in `../sase-core`, then update the Python
callers or adapters here.
