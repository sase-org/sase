---
pdf: false
---

# Memory Directory Map Prompt

## Target

- Packaged source asset: `src/sase/memory/assets/memory-directory-map.png`.
- Canonical SASE project copy: `sase/memory/assets/memory-directory-map.png`.
- Generated project/home copies: `sase/memory/assets/memory-directory-map.png` below
  each canonical memory root.
- Embedded in generated `sase/memory/README.md` files immediately after the opening
  paragraph.
- Final size: 1600×900 PNG, sRGB.

## Intended Alt Text

Memory architecture showing canonical short and long notes, generated provider shims,
audited reads, agent context, and the generated `sase/memory/README.md`.

## Final Asset Status

The Phase 8 asset uses a freshly generated text-free GPT Image base with deterministic
local labels. The packaged image and every propagated generated copy must remain
byte-identical.

## Final GPT Image Prompt

The built-in GPT Image tool generated the structural base. It was instructed to leave
every label region blank so no model-generated text survives in the committed asset.

```text
Use case: infographic-diagram
Asset type: text-free structural base for a technical documentation memory-directory map; final deterministic labels will be added locally.
Primary request: Create a polished, completely text-free software architecture infographic base showing canonical markdown memory notes becoming agent context and generated documentation.
Scene/backdrop: light neutral warm-gray background with subtle paper-like panels, crisp flat vector-like geometry, strong contrast, generous whitespace.
Composition/framing: 16:9 landscape. Left: a tall source panel containing a stack of four offset blank markdown document cards, each with an empty frontmatter strip. Middle: two clearly separated horizontal swimlanes. Upper lane: one blank source card flows to one larger generated-document card, then fans out to four small blank output document cards. Lower lane: one blank reference card flows through one small audit/check gate into one blank context card. Right: one larger agent-working-context panel with two nested blank content cards, plus a separate generated README document panel. Bottom: a low horizontal freshness-loop band with two rounded blank command blocks, a circular-arrow motif, and a small blank checkpoint/output motif. Connect sources and lanes with clear arrows. Leave every panel and card blank and light enough for dark labels.
Style/medium: flat vector-like technical architecture illustration rendered as a high-resolution raster; crisp thin outlines; softly rounded rectangles; restrained teal, blue, amber, green, purple, and slate accents; minimal shadows; no dark mode; no decorative gradients.
Constraints: absolutely no readable text, pseudo-text, glyphs, letters, numerals, fake lorem ipsum lines, logos, watermarks, terminal screenshots, or code. Do not imply image generation occurs in the freshness loop. Keep all arrows unambiguous and fully within canvas. Preserve generous blank label zones. No cropping.
```

## Deterministic Labels

DejaVu Sans supplies prose labels and Fira Code supplies exact paths and commands. The
canonical path labels are:

- `sase/memory/*.md`
- `sase/memory/README.md`
- `sase memory read`
- `sase memory init`
- `sase validate`

The remaining labels describe frontmatter (`type: short | long`, `parent:`,
`description:`), core (short) notes, `AGENTS.md`, provider shims (`CLAUDE.md`,
`GEMINI.md`, `QWEN.md`, `OPENCODE.md`), reference (long) notes, audited reference
fetching, agent context, regeneration, and the drift gate.

## Post-Processing Record

The selected 1672×941 base was resized to 1600×900. A transparent SVG overlay added the
exact label groups and a white backing panel around the audited-read gate. ImageMagick 7
composited and stripped the final asset:

```bash
magick "$BASE_PNG" -resize 1600x900! -strip -colorspace sRGB "$RESIZED_BASE"
magick -background none "$LABELS_SVG" "$LABELS_PNG"
magick "$RESIZED_BASE" "$LABELS_PNG" -compose over -composite \
  -strip -colorspace sRGB src/sase/memory/assets/memory-directory-map.png
cp src/sase/memory/assets/memory-directory-map.png \
  sase/memory/assets/memory-directory-map.png
cmp src/sase/memory/assets/memory-directory-map.png \
  sase/memory/assets/memory-directory-map.png
```

The label anchors on the 1600×900 canvas are grouped as follows:

| Region                 | Anchor labels                                                                                      |
| ---------------------- | -------------------------------------------------------------------------------------------------- |
| Source documents       | `(85,106)`, `(85,244)`, `(85,385)`, `(85,525)`                                                     |
| Core memory lane       | lane tab `(540,49)`, source `(487,206)`, `AGENTS.md` `(789,187)`, provider shims near `x=1110`     |
| Reference memory lane  | lane tab `(535,472)`, source `(510,545)`, audited read gate near `(770,542)`, context `(1037,545)` |
| Agent context / README | context cards at `x=1417`; README path at `(1417,638)` and `(1417,670)`                            |
| Freshness loop         | tab `(303,727)`, init `(333,774)`, regenerate `(653,774)`, validate `(1110,766)`                   |

## Final Review

- Full-resolution inspection confirmed legibility, correct arrow direction, uncropped
  cards, and adequate contrast.
- No model-generated text, pseudo-text, logos, or watermarks remain.
- Both source and generated README labels use the canonical `sase/memory/...` paths.
- Final SHA-256: `e5abac51d20648d0c75f462c563ec15ddf59f0e03296b9341de3325dc625e172`.
