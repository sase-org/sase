# Rust Backend Boundary Infographic Prompt

## Target

- Document: `docs/rust_backend.md`
- Insertion point: at the start of `## Architecture`, before the existing ASCII diagram.

## Intended Alt Text

Layered diagram showing Python host responsibilities, the `sase.core` facade and wire records, the required
`sase_core_rs` PyO3 extension, Rust-owned backend operations in `../sase-core`, and the health/test contract loop.

## Final GPT Image Prompt

```text
Use case: infographic-diagram
Asset type: GitHub Markdown documentation infographic, 16:9 landscape PNG
Primary request: Create a clean architecture infographic background for the SASE Rust backend boundary and ownership
model. It should be a polished technical diagram foundation, not marketing art.
Composition: four horizontal layers stacked vertically with generous spacing and crisp rounded rectangles: top layer for
Python UI/CLI/TUI/workflow host, second layer for sase.core Python facade and stable wire records, third layer for
required sase_core_rs PyO3 extension, bottom layer for sibling ../sase-core Rust workspace. Add a vertical boundary
connector between the facade and extension, plus two side panels for ownership groups and a small bottom-right
contract/health loop.
Text policy: do not render any words, letters, numbers, code snippets, logos, watermarks, terminal screenshots, or fake
UI text. Use only abstract shapes, short blank label placeholders, arrows, lanes, and icon-like marks. Leave clear empty
space inside every block and panel for deterministic labels to be added later.
Visual style: neutral light background, high contrast outlines, subtle depth, restrained palette with distinct accents
(teal for Python facade/host, blue for Rust extension/workspace, amber for contracts, muted gray for shared wire
boundary). Crisp arrows and swimlanes, clean documentation style, readable at GitHub Markdown width.
Avoid: dark background, dense paragraphs, tiny text, fake terminal windows, third-party logos, optional fallback
symbolism, one-hue purple/blue gradient theme.
```

## Post-Processing Notes

The generated image was used as the no-text architecture background. Final labels were added deterministically with
ImageMagick so the committed PNG uses exact doc terminology and avoids generated-text misspellings. Phase 7 QA adjusted
overlapping layer, ownership, and contract-loop labels for GitHub Markdown readability.
