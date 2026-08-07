# Plans sidecar directory map

## Target

- Final asset: `src/sase/sdd/assets/plans-directory-map.png`
- Size: 1600×900 PNG
- Intended use: generated README for each plans sidecar repository
- Alt text:
  `Flow from sase plan propose through review and approval into monthly plan Markdown and provenance links in the auto-cloned plans sidecar, with SDD commit and push.`

## Final GPT Image Prompt

```text
Use case: infographic-diagram
Asset type: text-free structural base for a 1600x900 GitHub Markdown documentation infographic
Primary request: Create a clean 16:9 landscape architecture infographic base explaining a plans sidecar repository workflow. This will be post-processed with exact deterministic labels, so include absolutely no readable words, letters, numbers, pseudo-text, logos, or watermarks.
Scene/backdrop: warm off-white technical-documentation canvas with very subtle paper grain.
Composition/framing: left-to-right workflow with generous whitespace and crisp visual hierarchy. At upper left, a blank command/input card feeds a blank review gate card and then a blank approval gate card. Their arrows lead into a large central repository container. Inside that repository container, show one monthly folder containing a plan document and small link/provenance chips only; do not show nested prompt documents, prompt snapshot folders, artifacts folders, or bead-state/event-card groups. At right, show three clean workspace/window containers receiving clones from the central repository via a fan-out arrow; each workspace contains the same small blank repository-folder symbol. Along the bottom, show a distinct SDD machinery rail: a simple gear/automation node leading through a commit node and an upload/push arrow back into the repository, clearly communicating automated commit and push. Include a small empty badge near the workspace fan-out for the automatic-clone setting.
Style/medium: crisp flat vector-like software architecture diagram; light neutral background; thin dark-slate strokes; small-radius rounded panels; subtle soft shadows; restrained teal, blue, green, amber, and slate accents; polished but not marketing art; consistent with high-quality open-source technical docs.
Composition constraints: leave large clean blank label zones in every major card and group; all arrows must be obvious at 900px display width; repository contents and workspace clones must remain visually distinct.
Avoid: any generated text or text-like marks, decorative gradients, dark background, fake terminal screenshots, source-code glyphs, brand marks, dense textures, tiny details, excessive 3D, one-hue palette.
```

The 2026-08 refresh was rendered from a deterministic 1600×900 SVG composition instead
of reusing the prior generated base, because that base visually included obsolete
prompt-snapshot and bead-state groups. The same structural constraints and labels above
remain the source of truth for a future text-free generated base, but the checked-in PNG
contains only deterministic SVG shapes and text.

## Deterministic Labels

DejaVu Sans Bold/Book and DejaVu Sans Mono Bold/Book were used for every visible
character. The overlay uses dark slate `#17243a`, secondary slate `#536175`, opaque
white label panels, and light-gray `#d4dbe5` borders.

- Title: `PLANS SIDECAR`
- Subtitle: `Approved plans and provenance links - auto-cloned everywhere`
- Proposal flow: `PROPOSE`, `sase plan propose`, `capture intent`, `REVIEW`, `Human`,
  `review gate`, `APPROVE`, `Write`, `durable state`
- Repository: `PLANS REPOSITORY`, `sase-org/sase--plans`, `public linked sidecar`
- Monthly contents: `MONTHLY PLAN`, `<YYYYMM>/plan.md`, `header links`,
  `plan Markdown + provenance`
- Clone behavior: `AUTO-CLONE`, `auto_clone: true`, `EVERY WORKSPACE`,
  `under sase/repos/`, and three `sase--plans` workspace clones
- Persistence rail: `SDD machinery`, `commit`, `push`, `OWNING REPOSITORY`,
  `changes are committed and pushed`

## Post-Processing

1. Render a 1600×900 SVG using the fonts, colors, shapes, arrows, and deterministic
   labels above. Place proposal/review/approval cards on the left, repository/content
   labels in the center, auto-clone/workspace labels on the right, and commit/push
   labels along the bottom rail.
2. Convert the SVG to an 8-bit sRGB PNG and strip metadata.
3. Create a temporary 900px-wide reduction for visual review. Do not retain the SVG or
   preview in the repository.
4. Inspect both the full-size raster and the 900px-wide reduction. Confirm that
   `auto_clone: true`, `sase-org/sase--plans`, `<YYYYMM>/plan.md`, and `header links`
   remain legible, and that no `plans/.../prompts/`, `prompts/prompt.md`, or
   `beads/events/**` node is visible.

Equivalent ImageMagick pipeline:

```bash
magick -background none plans-directory-map.svg -strip \
  -colorspace sRGB -depth 8 PNG24:plans-directory-map.png
magick plans-directory-map.png -resize 900x -strip \
  -colorspace sRGB -depth 8 PNG24:plans-directory-map-preview.png
```

No model-rendered text is present in the final raster.
