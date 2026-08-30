---
keyword: The Rust Core Is Required
aliases: [no python fallback, rust core boundary]
summary:
  Shared backend behavior lives in sase-core with no Python fallback and no env-var
  backend switch.
metadata:
  status: accepted
  decided: 2026-05-01
---

**Claim.** Shared deterministic backend and domain behavior lives in `../sase-core` and
is consumed through the `sase_core_rs` PyO3 wheel. It is a hard runtime dependency: no
`SASE_CORE_BACKEND` switch, no dispatcher, no dual-run parity mode, and no Python
reimplementation of a ported operation.

**Why.** Before this boundary, a dispatcher allowed a Python fallback to run alongside
the Rust path, and shared behavior could quietly diverge between the two — a correctness
bug in one and not the other, discovered late. Rejected alternatives: keep everything in
Python (loses cross-frontend consistency as more frontends land), or move the whole
application into Rust (throws away Python's plugin dispatch, filesystem/process side
effects, and TUI presentation, none of which belong in a deterministic core). The
accepted boundary is the litmus test in [[rust_core_backend_boundary.md]]: if a web app,
CLI, editor integration, or another frontend would need the behavior to match the TUI,
it is core backend logic and belongs in Rust.

**Cost.** A strict PyO3 loader with no soft-fail path, a pinned dependency window
(`sase-core-rs>=0.31.0,<0.32.0`) that must be ratcheted forward deliberately, and every
core-affecting change requiring two coordinated commits — one in `sase-core`, one in the
Python adapter — released in order.

**Reopens when.** Boundary friction becomes the dominant cost, measured in duplicated
adapters or wire-version churn across releases — not from a general preference for
writing a given feature in Python.
