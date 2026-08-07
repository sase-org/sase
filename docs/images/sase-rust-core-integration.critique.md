---
pdf: false
---

# Critique: `docs/images/sase-rust-core-integration.png`

Reviewed against `docs/architecture.md` (Rust Core Boundary section), `docs/rust_backend.md`,
`src/sase/core/`, the top-level `Justfile`, and `memory/rust_core_backend_boundary.md`. No
`sase-rust-core-integration.prompt.md` sidecar exists, so original intent is inferred from the
embedding-doc claims in `sdd/epics/202605/diagram_review.md` and the image itself.

## Subject and Embedding

The file shows three column groups — **Python App Layer**, **Python Façade Layer
(`src/sase/core`)**, and **Rust Package & Sibling Repo** — over a bottom row that walks
`pip install sase → just rust-install → sase core health`. Its purpose is to communicate how SASE
Python code reaches Rust-implemented operations.

**Embedding gap (meta-issue):** The plan in `sdd/epics/202605/diagram_review.md` lists this image as
appearing in `docs/architecture.md` / `docs/index.md`, but `rg "sase-rust-core-integration" docs/`
returns zero hits. The architecture page and index embed `sase-component-communication.png`, and
`docs/rust_backend.md` embeds `rust-backend-boundary-infographic.png`. (The stale TUI-tabs
infographic was retired from the index.) The regen phase should decide whether to (a) wire the
regenerated PNG into one of those pages (architecture.md's "Rust Core Boundary" section is the
natural home), or (b) treat it as an orphan we keep for future use. Either way the current state is
misleading because critiques and regens of an unreferenced image cannot be validated by the
"embedding doc still renders" check the plan calls for.

## Clarity

1. **Façade list reads as exhaustive but isn't.** The middle column shows five chips —
   `parser_facade`, `query_facade`, `status_facade`, `agent_facade`, `git_query` — with no ellipsis
   or "examples include" framing. The current `src/sase/core/` tree contains 27 `*_facade.py`
   modules (see Accuracy §1). Some call Rust directly and others are Python-owned host adapters, a
   distinction the diagram also needs to preserve. A new reader will otherwise infer both that the
   façade surface is much smaller than it is and that every façade crosses the Rust boundary.

2. **`agent_facade` is not a real module.** No file by that name exists in `src/sase/core/`. The
   closest matches are `agent_scan_facade.py`, `agent_cleanup_facade.py`, `agent_launch_facade.py`,
   `agent_identity_facade.py`, and `agent_runtime_facade.py`; related boundaries include
   `agent_launch_claims.py`, `artifact_file_facade.py`, and `dismissed_agents_facade.py`. Picking
   one invented composite label hides distinct identity, runtime, scan, launch, cleanup,
   artifact-file, and archive responsibilities.

3. **Bottom-row arrows imply a sequence, but the steps are alternatives.** `pip install sase` and
   `just rust-install` are not sequential — per `docs/rust_backend.md` line 6 and the `Justfile`
   `_setup` recipe, a normal `pip install sase` (or `uv tool install sase`) pulls a prebuilt
   `sase-core-rs` wheel automatically with no Rust toolchain required. `just rust-install` is the
   source-build alternative for contributors with a checkout of `../sase-core`. `sase core health`
   is a verification any user can run after either path. Drawing the three as a left-to-right chain
   misrepresents the user journey.

4. **The label "host-owned text logic flows: Python files, subprocesses, TUI, plugins" floats
   between columns.** It's visually attached to the façade column but conceptually describes
   responsibilities that _stay in Python and never cross into Rust_. New readers cannot tell whether
   it labels what's above the line or what's below.

5. **The "missing or stale wheel fails fast" annotation has no clear anchor.** It corresponds to
   `require_rust_extension` / `require_rust_binding` in `src/sase/core/rust.py`, but the diagram
   doesn't tie the phrase to a specific arrow or component. A reader doesn't know whether the
   failure happens in the façade, the binding, or the install step.

6. **`sase-core-rs` (PyPI dist) vs `sase_core_rs` (Python module name) distinction is collapsed.**
   The PyPI package and the importable Python module have different separators (`-` vs `_`). The
   diagram uses `sase_core_rs` only, while the install step text says "pulls sase-core-rs". A reader
   can't tell whether these are two artifacts or one typo.

7. **No mention of wire records.** "dict / wire-shaped results" appears as a tiny mid-column label,
   but the underlying concept — that `wire.py`, `*_wire.py`, and `*_wire_conversion.py` modules are
   the _stable contract_ between Python and Rust — is the whole reason the boundary is interesting.
   New users who read only this diagram will not know wire records exist.

8. **Title is generic.** "SASE Rust Core Integration" doesn't tell a new user what question this
   diagram answers ("how does SASE call Rust?", "what's in the Rust crate?", "what are the install
   paths?"). It tries to answer all three at once and ends up giving each only one row.

## Accuracy

1. **Façade coverage is significantly understated and the suffix alone does not prove Rust
   ownership.** The current tree has 27 `*_facade.py` modules. Direct or mixed Rust boundary
   families include project parsing, lifecycle, query, and status; notifications and prompt/snippet
   stores; agent identity/runtime/scan/launch/cleanup; bead reads, mutations, and conflicts;
   Git/VCS/commit helpers; axe chop; and Rust-backed artifact-file index queries. Artifact-file
   storage and default synthesis remain Python-owned behind `artifact_file_facade.py`, while facades
   such as `graph_index_facade.py` and `dismissed_agents_facade.py` are host adapters. The diagram
   should use representative grouped examples and mark which route reaches Rust instead of
   presenting five chips as the complete boundary.

2. **`agent_facade` does not exist.** Search `src/sase/core/` — there is no `agent_facade.py`.
   Should be at minimum `agent_scan_facade`, with the other agent-related facades shown explicitly
   or grouped under a labeled cluster.

3. **The arrow between `sase_core_rs` and `../sase-core` is mislabeled "Python ↔ Rust boundary".**
   The Python ↔ Rust boundary is _inside_ `sase_core_rs` (the PyO3 extension itself), not between it
   and the sibling crate. The relationship between `sase_core_rs` and `../sase-core` is
   **build-time**: the wheel is produced from `crates/sase_core_py` (PyO3 bindings) linked against
   `crates/sase_core` (pure Rust logic). The right label is "built from" or "source repo for the
   wheel".

4. **"PyPI wheel" + "Cargo workspace" framing leaves out the required-extension property.** The
   current `pyproject.toml` declares `sase-core-rs>=0.12.17,<0.13.0` as a **hard runtime
   dependency**. There is no supported Rust-free mode or backend-selection environment variable.
   Most ported operations fail fast when a binding is missing or stale; the agent-cleanup planner
   and mutation wrappers retain narrow compatibility fallbacks. The diagram should say the extension
   is required without incorrectly implying that every individual call lacks a fallback.

5. **"missing or stale wheel fails fast" undersells what `tools/validate_sase_core_rs` does in
   `_setup`.** The `Justfile` `_setup` recipe (lines 22–29) actively rebuilds `sase_core_rs` from
   `../sase-core` when validation fails _before_ dependency resolution. The runtime fail-fast in
   `core/rust.py` is a separate, later check. The diagram conflates the two.

6. **`crates/sase_core` and `crates/sase_core_py` labels need a one-word qualifier.** The image
   labels them "for pure Rust logic" and "for PyO3 bindings" which is correct, but a new reader sees
   two crates and wonders why bindings are split out. A note like "split so the pure crate is
   reusable from non-Python frontends (CLI, future web)" matches the rationale in
   `memory/rust_core_backend_boundary.md` ("reused by non-Python frontends") and would justify the
   split.

7. **The `sase core health` chip says "verifies import + binding".** That's correct
   (`src/sase/core/health.py` runs `require_rust_extension` + a binding probe), but readers who
   don't already know what "binding" means in PyO3 context get no help. Recommend: "verifies the
   `sase_core_rs` extension imports and exposes the expected functions".

8. **Wire records are entirely absent.** The current codebase has the shared `wire.py`, 15
   `*_wire.py` modules, and 3 `*_wire_conversion.py` modules. Per `docs/rust_backend.md` they are
   the **stable** part of the contract. A boundary diagram that omits them misstates what stability
   means here.

9. **Python App Layer chips are slightly off-target.** "ChangeSpec workflows", "agent scans",
   "status + git helpers" are all real, but the diagram chooses three areas that happen to all be
   Rust-backed, omitting the purely-host areas (TUI rendering, xprompt expansion, workflow
   orchestration, VCS plugin dispatch). That makes the façade look like it sits under _all_ Python
   work, when in fact most of `sase` (TUI, axe, xprompt) bypasses it entirely.
   `docs/rust_backend.md` lines 31–58 enumerate the host-owned surfaces that never cross the
   boundary; the diagram should at least name them as a sibling box.

## Concrete Suggestions for the Regenerated Image

The regen phase should retain the three-column structure (App → Façade → Rust) but rebalance content
so accuracy matches the docs. Specific edits:

- **Title**: change to something like "How SASE Python reaches Rust: facades, wire records, and the
  `sase_core_rs` extension" so the diagram's question is explicit.
- **Façade column**: replace the five chips with representative grouped families —
  project/query/status, notifications/prompts, agent identity/runtime/scan/launch/cleanup, beads,
  VCS/commits, axe chop, and artifact-file queries. Keep the `_facade` suffix in at least one real
  example so the naming convention is visible. Label the list as examples rather than attaching a
  fixed family count, and distinguish Rust-backed boundaries from host-only adapters.
- **Add a wire-record band** between the façade column and `sase_core_rs`, labeled "stable wire
  records (`*_wire.py`, `*_wire_conversion.py`) — Python ↔ Rust serialization contract".
- **Add a sibling "Host-owned (never crosses boundary)" box** in the App Layer with chips like "TUI
  rendering", "xprompt expansion", "workflow orchestration", "subprocess + signalling", "plugin
  dispatch". This sets the scope honestly.
- **Rust column**: keep the `sase_core_rs` ↔ `../sase-core` pairing but relabel the arrow "built
  from" (not "Python ↔ Rust boundary"). Add a "required runtime dependency" annotation on the wheel
  chip; if fallback behavior is mentioned, preserve the current cleanup-only compatibility
  exception.
- **Crate split**: keep `crates/sase_core` (pure Rust, reusable by future non-Python frontends) and
  `crates/sase_core_py` (PyO3 bindings → ships as the `sase-core-rs` wheel). Add a small "future:
  web/CLI from pure crate" hint to justify the split.
- **Naming**: render `sase-core-rs` (PyPI dist) and `sase_core_rs` (Python module / PyO3 extension)
  explicitly with a small "(`pip` ↔ `import` names)" footnote so readers don't think one is a typo.
- **Bottom row**: replace the linear three-step chain with two parallel paths plus a verification:
  - **Path A (default)**: `pip install sase` → prebuilt `sase-core-rs` wheel from PyPI
  - **Path B (contributors)**: `just rust-install` → builds wheel from `../sase-core` checkout
  - **Verify (either path)**: `sase core health` The visual should make the OR explicit (forking
    arrows or two horizontal tracks).
- **Fail-fast annotation**: anchor it to the `require_rust_extension` / `require_rust_binding`
  loader, and separately call out that `_setup` rebuilds stale wheels before dependency resolution
  when `../sase-core` is present.
- **Embedding decision**: regen phase should also resolve where this image is embedded.
  Recommendation: insert it into `docs/architecture.md` under "Rust Core Boundary" (currently
  text-only) so the verification check in the plan ("embedding doc still renders the image
  correctly") becomes meaningful.

Out of scope for this critique (per phase definition): no edits to the PNG, no prompt sidecar
creation, no embedding-doc edits. Those belong to the regen phase (`sase-2s.15`).
