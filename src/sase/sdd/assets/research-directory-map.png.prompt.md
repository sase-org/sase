# Research sidecar directory map

## Target

- Final asset: `src/sase/sdd/assets/research-directory-map.png`
- Size: 1600×900 PNG
- Intended use: generated README for each research sidecar repository
- Alt text:
  `Research swarm branches consolidate a monthly report and infographic in the research sidecar, which is lazily materialized with sase sdd path research --ensure.`

## Final GPT Image Prompt

```text
Use case: infographic-diagram
Asset type: text-free structural base for a 1600x900 GitHub Markdown documentation infographic
Primary request: Create a clean 16:9 landscape architecture infographic base explaining a research swarm and lazy research sidecar repository workflow. This will be post-processed with exact deterministic labels, so include absolutely no readable words, letters, numbers, pseudo-text, logos, or watermarks.
Scene/backdrop: warm off-white technical-documentation canvas with very subtle paper grain.
Composition/framing: left-to-right flow with generous whitespace. At left, show one blank workflow-trigger card fanning out into three distinct small agent/research nodes arranged vertically, each with an abstract icon and a large blank label space. Connect all three branches into one clear merge/consolidation node in the center. From the merge, feed a large central-right repository container. Inside the repository, show one monthly folder group holding two visually distinct blank artifacts: a report/document stack with small citation/source marks and a landscape image/infographic thumbnail. At far right, show a separate on-demand materialization area: a blank command card with a hand/cursor or activation icon leading into exactly one workspace clone window containing the repository folder. Include a small empty badge near this path for the lazy or disabled-auto-clone setting. Use a dashed dormant connector before activation and a solid connector after activation so lazy cloning is visually obvious.
Style/medium: crisp flat vector-like software architecture diagram; light neutral background; thin dark-slate strokes; small-radius rounded panels; subtle soft shadows; restrained purple, teal, blue, amber, green, and slate accents; polished open-source technical documentation style, not marketing art.
Composition constraints: leave large clean blank label zones in every major card and group; fan-out, consolidation, monthly output, and on-demand clone must remain distinct and legible at 900px display width.
Avoid: any generated text or text-like marks, decorative gradients, dark background, fake terminal screenshots, source-code glyphs, brand marks, dense textures, tiny details, excessive 3D, one-hue palette.
```

The built-in image-generation tool produced the text-free 1672×941 base. The original generation was saved at
`$CODEX_HOME/generated_images/019f53c3-ff03-7990-9ab3-ffe08fb3e131/exec-bee0a271-4e26-4c1f-b450-262ffd0735c1.png`.

## Deterministic Labels

DejaVu Sans Bold/Book and DejaVu Sans Mono Bold/Book were used for every visible character. The overlay uses dark slate
`#17243a`, secondary slate `#536175`, opaque white label panels, and light-gray `#d4dbe5` borders.

- Title: `RESEARCH SIDECAR`
- Subtitle: `Parallel research becomes a report + infographic — cloned on demand`
- Fan-out: `RESEARCH SWARM`, `#research_swarm`, `FAN-OUT`, `Researcher A`, `Researcher B`, `Image agent`, `Consolidate`
- Repository: `RESEARCH REPOSITORY`, `sase-org/sase--research`, `public linked sidecar`
- Monthly contents: `MONTHLY OUTPUT`, `<YYYYMM>/`, `REPORT`, `report.md`, `sources + citations`, `INFOGRAPHIC`,
  `*_infographic.png`, `beside the report`
- Lazy clone: `ON DEMAND`, `Ensure clone`, `LAZY`, `auto_clone: false`, `WORKSPACE CLONE`, `sase/repos/`,
  `sase--research`
- Resolver: `LAZY MATERIALIZATION`, `sase sdd path research --ensure`,
  `materializes the linked clone when research is needed`

## Post-Processing

1. Resize the generated base to exactly 1600×900.
2. Render a transparent 1600×900 SVG overlay using the fonts and labels above. Place the swarm/fan-out labels on the
   left, consolidated monthly outputs in the repository panel, and the on-demand clone labels on the right.
3. Composite the overlay over the resized base and strip metadata. Keep the output 8-bit sRGB.
4. Inspect both the full-size raster and a 900px-wide reduction. Confirm that `auto_clone: false`,
   `sase-org/sase--research`, `<YYYYMM>/`, `report.md`, `*_infographic.png`, and `sase sdd path research --ensure`
   remain legible.

Equivalent ImageMagick pipeline:

```bash
magick generated-base.png -resize '1600x900!' -depth 8 base-1600.png
magick -background none labels.svg -depth 8 labels.png
magick base-1600.png labels.png -compose over -composite -strip -depth 8 research-directory-map.png
magick research-directory-map.png -resize 900x research-directory-map-preview.png
```

No model-rendered text is present in the final raster.
