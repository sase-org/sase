---
pdf: false
---

# XPrompt Resolution Infographic Prompt

## Target

- Document: `docs/xprompt.md`
- Insertion point: after the introductory use-case list and before the authoritative text pipeline.
- Final asset path: `docs/images/xprompt-resolution-infographic.png`
- Final size: 1672×941 PNG, sRGB.
- Status: regenerated, deterministically labeled, reviewed, and embedded.

## Intended Alt Text

SASE xprompt inputs flowing through workspace dispatch, first-wins discovery, iterative expansion, and directive
extraction into runtime outcomes.

## Final GPT Image Prompt

The built-in GPT Image tool generated a completely text-free structural base. All visible labels in the committed PNG
were added locally afterward.

```text
Use case: infographic-diagram
Asset type: text-free structural base for a technical documentation infographic; final deterministic labels will be added locally.
Primary request: Create a polished, completely text-free landscape architecture infographic base showing a software prompt-resolution system flowing left to right from inputs, through a resolver, to outcomes.
Scene/backdrop: very light neutral warm-gray background, crisp flat vector-like panels, thin slate outlines, subtle paper texture, high contrast, generous whitespace.
Composition/framing: 16:9 landscape. Three zones. Left: one tall rounded input panel with exactly four spacious blank card rows, plus one separate protected-content callout card below. Center: one large resolver panel with a blank workspace-dispatch pre-stage at top, a short two-step horizontal prelude, then a large dashed iterative-loop group containing exactly five stacked blank processing rows and a narrow sidebar with seventeen small blank priority rungs. Below the loop, exactly three blank post-processing rows arranged cleanly. Right: one tall outcomes panel with exactly three runtime outcome cards plus one visually separate dashed developer-tool card. Show arrows connecting the zones and a loop-back arrow around the five central rows. Leave every panel and card blank and light enough for dark labels.
Style/medium: flat vector-like technical architecture illustration rendered as a high-resolution raster; softly rounded rectangles; restrained teal, blue, amber, green, purple, and slate accents; minimal shadows; no dark mode; no decorative gradients.
Constraints: absolutely no readable text, pseudo-text, glyphs, letters, numerals, logos, watermarks, terminal screenshots, code snippets, fake UI lines, or decorative icons resembling letters. Preserve wide blank label zones. Keep arrows unambiguous and fully within canvas. No cropping.
```

## Deterministic Post-Processing Record

The selected 1672×941 base was kept at full opacity. A transparent SVG overlay supplied the exact labels, backing
panels, loop arrow, stage arrows, and protected-content connection. ImageMagick 7 rendered the overlay using DejaVu Sans
for prose and Fira Code for paths and commands, then composited and stripped the final PNG:

```bash
magick -background none "$LABELS_SVG" "$LABELS_PNG"
magick "$BASE_PNG" "$LABELS_PNG" -compose over -composite \
  -strip -colorspace sRGB docs/images/xprompt-resolution-infographic.png
```

The deterministic label groups are:

- Inputs: `#name / #name(args)`, `#!name`, `%directives`, and `#cd / #gh / #git refs`; the obsolete keyword-trigger and
  dynamic-memory rows are absent.
- Launch setup: workspace dispatch occurs before xprompt expansion; bare prompts default to `#git:home`.
- Expansion: alias substitution → protected-text masking → iterative parse, lookup, argument/`$(cmd)` processing,
  typed-input validation, and Jinja2/legacy rendering → unmask → directive extraction → expanded prompt text.
- Discovery: all 17 rows from `docs/xprompt.md`, in first-wins order, with canonical project/home paths preceding their
  corresponding legacy compatibility paths and package/plugin sources kept distinct.
- Outcomes: inline expansion, standalone workflow launch, depth-capped multi-agent fan-out, and a visually separate
  developer-tools card for `sase xprompt graph` / `sase xprompt explain`.

## Final Review

- Full-resolution inspection confirmed legible labels, uncropped panels, high-contrast text, and no generated
  pseudo-text.
- The protected-content callout points to the mask stage, the iterative stages flow downward with a loop-back arrow, and
  developer tooling is visually separate from runtime outcomes.
- Every technical label was compared with the launch/expansion pipelines and discovery table in `docs/xprompt.md`.
- Final SHA-256: `a2b5e5e55e8af32966cb59e6806982c15d7fc19ff70583e327d6a8a280b19174`.
