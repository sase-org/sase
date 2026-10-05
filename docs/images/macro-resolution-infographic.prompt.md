---
pdf: false
---

# Macro Resolution Infographic Prompt

## Target

- Document: `docs/macros.md`
- Insertion point: after the introductory use-case list and before the authoritative
  text pipeline.
- Final asset path: `docs/images/macro-resolution-infographic.png`
- Final size: 1672×941 PNG, sRGB.
- Status: regenerated, edited to remove legacy paths, deterministically labeled,
  reviewed, and embedded.

## Intended Alt Text

SASE macro inputs flowing through workspace dispatch, first-wins discovery, iterative
expansion, and directive extraction into runtime outcomes.

## Initial GPT Image Prompt

The built-in GPT Image tool generated a completely text-free structural base. All
visible labels in the committed PNG were added locally afterward.

```text
Use case: infographic-diagram
Asset type: text-free structural base for a technical documentation infographic; final deterministic labels will be added locally.
Primary request: Create a polished, completely text-free landscape architecture infographic base showing a software prompt-resolution system flowing left to right from inputs, through a resolver, to outcomes.
Scene/backdrop: very light neutral warm-gray background, crisp flat vector-like panels, thin slate outlines, subtle paper texture, high contrast, generous whitespace.
Composition/framing: 16:9 landscape. Three zones. Left: one tall rounded input panel with exactly four spacious blank card rows, plus one separate protected-content callout card below. Center: one large resolver panel with a blank workspace-dispatch pre-stage at top, a short two-step horizontal prelude, then a large dashed iterative-loop group containing exactly five stacked blank processing rows and a narrow sidebar with seventeen small blank priority rungs. Below the loop, exactly three blank post-processing rows arranged cleanly. Right: one tall outcomes panel with exactly three runtime outcome cards plus one visually separate dashed developer-tool card. Show arrows connecting the zones and a loop-back arrow around the five central rows. Leave every panel and card blank and light enough for dark labels.
Style/medium: flat vector-like technical architecture illustration rendered as a high-resolution raster; softly rounded rectangles; restrained teal, blue, amber, green, purple, and slate accents; minimal shadows; no dark mode; no decorative gradients.
Constraints: absolutely no readable text, pseudo-text, glyphs, letters, numerals, logos, watermarks, terminal screenshots, code snippets, fake UI lines, or decorative icons resembling letters. Preserve wide blank label zones. Keep arrows unambiguous and fully within canvas. No cropping.
```

## Legacy-Path Removal Edit

The built-in GPT Image tool then cleared the discovery inset so its legacy rows could be
removed without regenerating the surrounding infographic. Only the edited inset was
composited back into the original canvas; its replacement title, cards, and canonical
path labels were added locally.

```text
Use case: precise-object-edit
Asset type: technical documentation infographic base edit
Input image: Image 1 is the edit target.
Primary request: Remove all content inside the small rounded rectangle titled “Discovery priority · first wins” in the center-right of the blue dashed iterative-expansion group. Clear its title, all numbered mini-cards, and every path label. Replace that inset region with a single clean blank very-light-blue rounded rectangle matching the same footprint, border radius, thin pale-blue outline, and subtle paper texture. Keep the surrounding dashed loop, the five processing rows on the left, all arrows, every other panel, and every other visible label exactly unchanged.
Constraints: Change only the discovery inset. No new text, numbers, glyphs, icons, lines, cards, or pseudo-text inside the cleared inset. Do not crop, resize, recolor, restyle, or alter any other part of the image. Preserve the full 1672×941 landscape composition.
```

## Deterministic Post-Processing Record

The initial 1672×941 base was kept at full opacity. The cleared GPT Image output was
normalized to the final canvas size, then a rounded mask limited it to the discovery
inset. A transparent SVG overlay supplied the replacement canonical discovery panel and
its exact labels. ImageMagick 7 rendered the overlay using DejaVu Sans for prose and
Fira Code for paths and commands, then composited and stripped the final PNG:

```bash
magick "$EDIT_PNG" -resize '1672x941!' "$EDIT_RESIZED_PNG"
magick -size 1672x941 xc:black -fill white \
  -draw 'roundrectangle 825,310 1161,652 14,14' "$EDIT_MASK_PNG"
magick "$ORIGINAL_PNG" "$EDIT_RESIZED_PNG" "$EDIT_MASK_PNG" \
  -composite "$UNLABELED_PNG"
magick -background none "$LABELS_SVG" "$LABELS_PNG"
magick "$UNLABELED_PNG" "$LABELS_PNG" -compose over -composite \
  -strip -colorspace sRGB docs/images/macro-resolution-infographic.png
```

The deterministic label groups are:

- Inputs: `#name / #name(args)`, `#!name`, `%directives`, and `#cd / #gh / #git refs`;
  the obsolete keyword-trigger and dynamic-memory rows are absent.
- Launch setup: workspace dispatch occurs before macro expansion; bare prompts default
  to `#git:home`.
- Expansion: alias substitution → protected-text masking → iterative parse, lookup,
  argument/`$(cmd)` processing, typed-input validation, and Jinja2/legacy rendering →
  unmask → directive extraction → expanded prompt text.
- Discovery: the 11 canonical project, home, config, plugin, and package sources from
  `docs/macros.md`, retaining their relative first-wins order while omitting all legacy
  compatibility paths.
- Outcomes: inline expansion, standalone workflow launch, depth-capped multi-agent
  fan-out, and a visually separate developer-tools card for `sase macro graph` /
  `sase macro explain`.

## Macro-Spelling Relabel (Deterministic Overlay)

All 13 retired-spelling labels were replaced in place with macro-spelling text taken
from the current `docs/macros.md` (Discovery Order table, `sase macro graph` /
`sase macro explain` spellings), preserving position, size, weight, numbering, and the
original `<pkg>` abbreviation of `<sase_package>`. Canvas kept at 1672×941 sRGB.

- Inputs: `inline xprompt · embeddable workflow` → `inline macro · embeddable workflow`;
  `· xprompt swarm` → `· macro swarm`.
- Iterative title: `Iterative xprompt expansion · ≤100 passes` →
  `Iterative macro expansion · ≤100 passes`.
- Discovery rows: `1 <project>/sase/xprompts/` → `1 <project>/sase/macros/`;
  `2 ~/sase/xprompts/` → `2 ~/sase/macros/`; `3 ~/sase/xprompts/{project}/` →
  `3 ~/sase/macros/{project}/`; `(sase_xprompts EPs)` → `(sase_macros EPs)`;
  `10 <pkg>/default_xprompts/` → `10 <pkg>/default_macros/`; `11 <pkg>/xprompts/` →
  `11 <pkg>/macros/`.
- Fences callout: `protected while xprompt references expand` →
  `protected while macro references expand`.
- Extract line: `after full xprompt expansion` → `after full macro expansion`.
- Devtools card: `sase xprompt graph` → `sase macro graph`; `sase xprompt explain` →
  `sase macro explain`.

Method: local-bg cover of each label's ink span (per-column neighbor-clipped fill,
borders/arrows untouched), then single-draw full-line overlay rendered locally with PIL
using Inter for prose/bold titles and Fira Code for paths/commands (matched to the
committed raster by template comparison), tinted from each label's own darkest-core
pixels. Verified: full-PNG OCR reports zero `xprompt` residuals (base reported 6), all
pixel changes lie inside the 13 label windows, borders/arrows/loop intact:

```bash
magick patched.png -colorspace sRGB -strip \
  docs/images/macro-resolution-infographic.png
sha256sum docs/images/macro-resolution-infographic.png
```

## Final Review

- Full-resolution inspection confirmed legible labels, uncropped panels, high-contrast
  text, and no generated pseudo-text.
- The protected-content callout points to the mask stage, the iterative stages flow
  downward with a loop-back arrow, and developer tooling is visually separate from
  runtime outcomes.
- Every technical label was compared with the launch/expansion pipelines and canonical
  entries in the discovery table in `docs/macros.md`.
- Final SHA-256: `7529a15d0c2a77f0144d3804cef156b315949de0bf0ac59872ad5ccdd63f314e`.
