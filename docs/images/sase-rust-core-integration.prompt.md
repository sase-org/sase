---
pdf: false
generated: 2026-05-10
source_critique: docs/images/sase-rust-core-integration.critique.md
---

# Prompt: `docs/images/sase-rust-core-integration.png`

## Target

- Target doc: `docs/architecture.md`
- Insertion point: under `## Rust Core Boundary`, after the opening paragraph that
  summarizes Rust-backed areas.
- Intended alt text: Layered diagram showing how SASE Python host code reaches Rust
  through `src/sase/core` facades, stable wire records, the required `sase_core_rs`
  extension, and the `../sase-core` source workspace, with default and contributor
  install paths converging on `sase core health`.

## Final Prompt

```text
Use case: infographic-diagram Asset type: documentation architecture infographic, 16:9 PNG, landscape, light background,
crisp vector-like blocks, readable at GitHub Markdown width. Primary request: Create a revised SASE Rust core
integration diagram that answers: "How SASE Python reaches Rust: facades, wire records, and the required sase_core_rs
extension".

Visual style: clean technical architecture infographic, neutral off-white background, thin rounded rectangles,
restrained shadows, blue for Python, teal for wire records, green for Rust, orange for install/verify paths. No
decorative gradients, no logos, no terminal screenshots, no paragraphs. Use clear arrows and exact short labels.

Layout: Top title centered: "How SASE Python Reaches Rust" Subtitle below title: "facades -> wire records -> required
sase_core_rs extension"

Main architecture flow, left to right, three columns:

1. Left column header: "Python host layer" Large box label: "sase CLI / TUI / workflows" Include two groups inside:
   - "Rust-backed callers" with chips: "ChangeSpec parsing", "queries", "status planning", "git parsing",
     "notifications", "agent scan", "agent launch", "beads"
   - "Host-owned, stays in Python" with chips: "TUI rendering", "xprompt expansion", "workflow orchestration",
     "plugins", "subprocesses", "file locks"

2. Middle column header: "src/sase/core facades" Large box label: "stable Python facade API" Show grouped chips, not an
   exhaustive fake module list: "parser_facade", "query + corpus", "status", "notification_store", "agent_scan",
   "agent_cleanup", "agent_launch + claims", "bead_read / bead_mutation", "git_query" Add a loader call arrow from this
   box toward Rust labeled: "require_rust_extension / require_rust_binding" Add a small warning badge anchored to this
   loader arrow: "missing or stale extension fails fast"

3. Between middle and right, add a horizontal teal band labeled exactly: "stable wire records: *_wire.py +
   *_wire_conversion.py" Small sublabel: "Python <-> Rust serialization contract"

4. Right column header: "Required Rust extension + sibling repo" Top box: "sase_core_rs" with sublabels "import name"
   and "PyO3 extension" Adjacent or footnote box: "sase-core-rs" with sublabel "PyPI wheel, hard runtime dependency, no
   Python fallback" Below, sibling repo box: "../sase-core" with two crate boxes:
   - "crates/sase_core" sublabel "pure Rust logic, reusable by future frontends"
   - "crates/sase_core_py" sublabel "PyO3 bindings -> wheel" Arrow from ../sase-core up to sase_core_rs labeled: "built
     from". Do NOT label this arrow as the Python/Rust boundary.

Bottom install and verification row separated from the architecture flow by a dotted rule: Show two parallel paths that
merge into verification, making OR explicit:

- "Default install" -> "pip install sase" -> "prebuilt sase-core-rs wheel"
- "Contributor install" -> "just rust-install" -> "builds from ../sase-core checkout" Both arrows merge into "sase core
  health" with sublabel "verifies extension import + expected bindings". Add a small note near contributor path: "setup
  can rebuild stale local wheel before dependency resolution".

Text constraints: render only the labels specified above, with exact spelling for code identifiers: sase_core_rs,
sase-core-rs, src/sase/core, ../sase-core, crates/sase_core, crates/sase_core_py, *_wire.py, *_wire_conversion.py.
Make code identifiers monospace-like. Keep text large, high contrast, and horizontal. Avoid tiny footnotes except the
single required note. No extra invented labels. No watermarks.
```

## Post-Processing Notes

- Generated with the built-in GPT image generation tool.
- Generated image copied from the Codex image cache to
  `docs/images/sase-rust-core-integration.png`.
- No deterministic relabeling was needed; the generated text was legible enough for
  documentation use.
