---
pdf: false
---

# Rust Backend Boundary Infographic Prompt

## Target

- Document: `docs/rust_backend.md`
- Insertion point: at the start of `## Architecture`, before the existing ASCII diagram.
- Final asset: `docs/images/rust-backend-boundary-infographic.png` (1600x900 PNG)

## Intended Alt Text

Layered diagram showing Python host responsibilities, the `sase.core` facade and wire records, the required
`sase_core_rs` PyO3 extension, Rust-owned backend operations in `../sase-core`, and the health/test contract loop.

## Final GPT Image Prompt

```text
Use case: infographic-diagram
Asset type: GitHub Markdown documentation infographic background, 16:9 landscape PNG
Primary request: Create a clean no-text architecture infographic background for the SASE Rust backend boundary and
ownership model. This will be post-processed with exact deterministic labels, so the generated image must contain no
readable words, letters, numbers, logos, watermarks, or fake UI text.
Composition: 1600x900 landscape. Four wide horizontal architecture layers stacked vertically with generous spacing: top
host layer, second facade/wire layer, a strong amber horizontal boundary divider between layer 2 and layer 3, third
extension layer, bottom Rust workspace layer. Include a single clear downward arrow crossing the amber boundary divider,
plus a modest bottom-right contract loop panel and a left-side legend panel. In the bottom Rust workspace layer, show a
neat 3x3 grid of small blank operation cards with ample empty interior space. Add a small blank badge between the
extension and Rust workspace layers for a wheel/distribution label. Include an adjacent small sidecar box near the
bottom Rust layer for a secondary gateway surface. Keep all boxes blank inside for later labels.
Visual style: neutral light background, crisp documentation-diagram aesthetic, high contrast outlines, subtle depth,
restrained palette with distinct accents: teal for Python host/facade, blue for Rust extension/workspace, amber for the
required boundary and contract, muted gray for wire records. Rounded rectangles may be used but keep radius small and
professional. Clean swimlanes, readable at GitHub Markdown width.
Avoid: any rendered text, any letters or numerals, fake terminal windows, code snippets, company logos, optional
fallback symbolism, dark background, dense decorative gradients, purple-blue dominant palette, tiny placeholders that
look like text.
```

## Post-Processing Notes

The generated base was used as a washed, no-text architecture background. Final labels, cards, dividers, arrows, and
side panels were composited deterministically with ImageMagick using DejaVu Sans fonts so the committed PNG uses exact
documentation terminology and avoids generated-text misspellings.

The regenerated diagram addresses the 2026-05-10 critique by:

- promoting `REQUIRED RUST BOUNDARY - NO PYTHON FALLBACK` to the dominant divider between the Python facade and
  `sase_core_rs`;
- showing a one-way `Python -> Rust` call arrow labeled as wire-record flow;
- replacing the left annotation column with the four Python host responsibilities from `docs/rust_backend.md`;
- naming Python-owned facade examples: `parse_project_file`, `evaluate_query*`, and `transition_status`;
- naming concrete `sase core health` probes: `parse_query`, launch schema/fanout, and `bead_cli_execute`;
- expanding the Rust workspace layer into current operation categories: project parsing, project lifecycle helpers,
  query parse/corpus, agent artifact scan/index, status helpers/planner, git query parsers, notification JSONL store,
  agent cleanup, agent launch/RUNNING claims, and bead data operations;
- adding the PyPI wheel badge `sase-core-rs >=0.1.1,<0.2.0`;
- adding a sidecar `crates/sase_gateway` box so the `../sase-core` workspace framing stays honest.
