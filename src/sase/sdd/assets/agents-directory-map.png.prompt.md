# Agents sidecar directory map

## Target

- Final asset: `src/sase/sdd/assets/agents-directory-map.png`
- Size: 1600×900 PNG
- Intended use: scaffold and manifest-derived root README for each agents sidecar repository
- Alt text:
  `Project-scoped agent hoods pass through explicit privacy consent into an owner-sharded agents sidecar, where deterministic sync publishes prompts, chats, commits, states, and browsable owner, machine, hood, family, and agent pages.`

## Final GPT Image Prompt

```text
Use case: infographic-diagram
Asset type: text-free structural base for a 1600x900 GitHub Markdown documentation infographic
Primary request: Create a clean 16:9 landscape architecture infographic base explaining a private-by-consent, owner-sharded agents sidecar publication workflow. This will be post-processed with exact deterministic labels, so include absolutely no readable words, letters, numbers, pseudo-text, source-code glyphs, logos, or watermarks.
Scene/backdrop: warm off-white technical-documentation canvas with very subtle paper grain.
Composition/framing: clear left-to-right story with generous whitespace and a dedicated header area. Below the header, show five visually distinct stages connected by unambiguous right-pointing arrows. Stage 1 at far left is a compact consent gate: one blank command card enters a shield-and-gate motif and fans into exactly three small outcome chips with empty label zones. Stage 2 is a large complete agent-hood panel showing five small status nodes around a central hood hub, plus recognizable but text-free artifact icons for a prompt document, optional chat bubble, commit branch, and relationship tree. Stage 3 is an owner/machine publication shard with a user icon over a computer icon, a prominent blank manifest document, and a nested hood snapshot document. Stage 4 is a clearly enclosed hidden repository vault separated from workspaces, with a closed-eye or privacy icon and a repository folder; below it show three faint workspace-window silhouettes crossed by a clear prohibition mark so the repository is unmistakably not cloned there. Stage 5 at far right is a browsing tree flowing top-to-bottom through four small page/folder levels, ending in two parallel page cards. Along the bottom, show a separate sync/refresh rail starting with a commit and outbox tray, flowing to circular sync arrows, then looping cleanly back to the owner-shard/hood-snapshot stage to convey refreshing the same run.
Style/medium: crisp flat vector-like software architecture diagram; thin dark-slate strokes; small-radius rounded panels; subtle soft shadows; restrained teal, blue, purple, amber, coral, and slate accents; polished open-source technical documentation style, not marketing art.
Composition constraints: leave large clean blank label zones in every major panel and beside key icons; keep all five stages and the bottom rail clearly distinct; privacy gate must be visually prominent; every arrow must remain obvious at 900px display width; the hidden repository must never appear inside or connected as a clone to any workspace; use icons only where their meaning is structurally clear.
Avoid: any generated text or text-like marks, decorative gradients, dark background, fake terminal screenshots, brand marks, dense textures, tiny details, excessive 3D, one-hue palette, ambiguous arrows, a repository shown inside workspace windows.
```

The built-in GPT Image tool produced the text-free 1672×941, 8-bit sRGB base on 2026-07-28. The source generation was
saved at `$CODEX_HOME/generated_images/019fa9a4-a702-7bb3-992e-913f419ce490/call_xHlKogtBrhqV4HFp3SAnAST4.png`. The
first composition was selected because it made consent, the complete hood, owner authority, the hidden repository, the
workspace-clone prohibition, deterministic browsing, and the refresh loop distinct at a glance.

## Deterministic Labels

Every visible character was added after generation with DejaVu Sans Bold/Book or DejaVu Sans Mono Bold/Book. The overlay
uses dark slate `#17243a`, secondary slate `#536175`, opaque white label panels, and light-gray `#d4dbe5` borders.

- Header: `AGENTS SIDECAR`, `Complete project hoods → consented owner shards → deterministic browsing`, and
  `PRIVACY · PUBLICATION · BROWSING`
- Consent: `EXPLICIT CONSENT`, `sase repo init`, `PUBLIC · PRIVATE · DISABLED`, `PUBLIC`, `PRIVATE`, and `DISABLED`
- Hood: `COMPLETE HOOD`, `active · waiting · failed · terminal · dismissed`, `prompt · optional chat`, and
  `commits · relationships`
- Owner shard: `OWNER SHARD`, `<username>/<machine>`, `one owner authority`, `manifest.json`, and `hood snapshot`
- Repository: `HIDDEN REPOSITORY`, `<project>--agents`, and `not cloned to workspaces`
- Browsing: `DETERMINISTIC BROWSING`, `root → owner → machine → hood`, and `agent + family pages`
- Refresh rail: `commit / outbox`, `sase agent sync`, and `refresh the same run`

## Post-processing

1. Resize the generated base to exactly 1600×900.
2. Render a transparent 1600×900 SVG overlay with the fonts, colors, and exact labels above.
3. Composite the overlay over the base, strip metadata, force sRGB, and retain an 8-bit RGB PNG.
4. Create a temporary 900px-wide reduction for visual review. Do not retain the base, overlay, or preview in the
   repository.

Equivalent ImageMagick pipeline:

```bash
magick generated-base.png -resize '1600x900!' -colorspace sRGB -depth 8 base-1600.png
magick -background none labels.svg -colorspace sRGB -depth 8 labels.png
magick base-1600.png labels.png -compose over -composite -strip \
  -colorspace sRGB -depth 8 PNG24:agents-directory-map.png
magick agents-directory-map.png -resize 900x -strip \
  -colorspace sRGB -depth 8 PNG24:agents-directory-map-preview.png
```

## Inspection checklist

- Full-size and 900px-wide renders have correct 16:9 geometry, crisp hierarchy, and sufficient contrast.
- Every deterministic label is spelled exactly as listed; generated document lines are icon details, not readable or
  pseudo-readable text.
- All stage arrows point left to right, while the sync rail visibly returns to the same owner-shard snapshot.
- The consent gate and public/private/disabled outcomes are prominent before any publication stage.
- Active, waiting, failed, terminal, and dismissed states belong to one complete hood.
- `manifest.json` and the hood snapshot are visibly contained by the owner shard.
- The vault and crossed-out workspace windows cannot be read as an auto-clone relationship.
- Root-to-hood browsing ends in distinct agent and family pages.
- No model-generated text, logo, watermark, metadata, alpha channel, or discarded candidate remains in the final
  repository asset.
