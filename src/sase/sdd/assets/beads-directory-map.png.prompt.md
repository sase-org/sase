# Beads sidecar directory map

## Target

- Final asset: `src/sase/sdd/assets/beads-directory-map.png`
- Size: 1600×900 PNG
- Intended use: generated README for each beads sidecar repository
- Alt text:
  `Append-only bead event streams feeding a generated projection and local cache in an isolated, auto-cloned beads sidecar, with separate plans storage and automated commit and push.`

## Final GPT Image Prompt

```text
Use case: infographic-diagram
Asset type: text-free structural base for a 1600x900 GitHub Markdown documentation infographic
Primary request: Create a clean 16:9 landscape architecture infographic base explaining a beads sidecar repository workflow. This will be post-processed with exact deterministic labels, so include absolutely no readable words, letters, numbers, pseudo-text, source-code glyphs, logos, or watermarks.
Scene/backdrop: warm off-white technical-documentation canvas with very subtle paper grain.
Composition/framing: left-to-right workflow with generous whitespace and crisp visual hierarchy. At upper left, a blank command/input card points into a large central repository container. Inside the repository, show three clearly separated blank artifact groups: an append-only event-stream stack feeding a derived projection document and a faded local cache chip. At right, show three clean workspace/window containers receiving clones from the repository through an obvious fan-out arrow; each workspace contains the same small blank repository-folder symbol. Along the bottom, show a distinct automation rail with a gear/machinery node, a commit node, and an upload/push arrow returning into the central repository. At upper right, show a separate sibling repository container that is visibly disconnected from the central repository, with spacing and boundary treatment communicating isolation and separate locking. Include a small empty badge near the workspace fan-out for the automatic-clone setting.
Style/medium: crisp flat vector-like software architecture diagram; thin dark-slate strokes; small-radius rounded panels; subtle soft shadows; restrained teal, blue, green, amber, and slate accents; polished open-source technical documentation, not marketing art.
Composition constraints: leave large clean blank label zones in every major card and group; all arrows must be obvious at 900px display width; repository contents, workspace clones, automation rail, and disconnected sibling repository must remain visually distinct.
Avoid: any generated text or text-like marks, decorative gradients, dark background, fake terminal screenshots, dense textures, tiny details, excessive 3D, one-hue palette.
```

The built-in image-generation tool produced the text-free 1672×941 base. The original generation was saved at
`$CODEX_HOME/generated_images/019fa528-52a4-7622-ba2b-5558a515a3a2/call_J6n7UUtuKTOVTt9p6xmR3rZ1.png`.

## Deterministic Labels

DejaVu Sans Bold/Book and DejaVu Sans Mono Bold/Book were used for every visible character. The overlay uses dark slate
`#17243a`, secondary slate `#536175`, opaque white label panels, and light-gray `#d4dbe5` borders.

- Title: `BEADS SIDECAR`
- Subtitle: `Append-only bead state — isolated, auto-cloned everywhere`
- Repository: `BEADS REPOSITORY`, `sase-org/sase--beads`, `public linked sidecar`
- Event store: `EVENT STORE`, `events/streams/*.jsonl`, `append-only source of truth`
- Projection: `PROJECTION`, `issues.jsonl`, `generated`
- Local cache: `LOCAL CACHE`, `beads.db (gitignored)`
- Clone behavior: `AUTO-CLONE`, `auto_clone: true`, `EVERY WORKSPACE`, `under sase/repos/beads`
- Isolation: `PLANS REPOSITORY`, `sase-org/sase--plans`, `separate repo, separate lock`
- Persistence rail: `SDD machinery`, `commit`, `push`

## Post-Processing

1. Resize the generated base to exactly 1600×900.
2. Render a transparent 1600×900 SVG overlay using the fonts and labels above. Place the title and subtitle at upper
   left, repository and content labels in the center, auto-clone and workspace labels on the right, isolation labels in
   the disconnected upper-right repository, and commit/push labels along the bottom rail.
3. Composite the overlay over the resized base and strip metadata. Keep the output 8-bit sRGB.
4. Inspect both the full-size raster and a 900px-wide reduction. Confirm that `auto_clone: true`,
   `events/streams/*.jsonl`, `issues.jsonl`, and `sase-org/sase--beads` remain legible.

Equivalent ImageMagick pipeline:

```bash
magick generated-base.png -resize '1600x900!' -depth 8 base-1600.png
magick -background none labels.svg -depth 8 labels.png
magick base-1600.png labels.png -compose over -composite -strip -depth 8 beads-directory-map.png
magick beads-directory-map.png -resize 900x beads-directory-map-preview.png
```

No model-rendered text is present in the final raster.
