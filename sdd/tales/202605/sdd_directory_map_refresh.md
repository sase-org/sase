---
create_time: 2026-05-02 19:09:52
status: done
---
# Plan: Refresh SDD Directory Map Asset

## Goal

Regenerate the SDD directory map image with GPT image tooling so the visual documentation matches the current generated
SDD layout, including both `myths/` and `research/`.

The user referred to `assets/sdd-directory-map.png`; in this repository there is no repo-root `assets/` directory. The
checked-in asset exists in two places:

- `src/sase/sdd/assets/sdd-directory-map.png` is the packaged source asset.
- `sdd/assets/sdd-directory-map.png` is the generated copy used by this repository's SDD README.

Both should be replaced with the same final PNG so `sase sdd init` continues to copy the packaged asset into generated
SDD trees.

## Current State

- The current map is a 1600x900 PNG with a clean documentation style.
- It includes `prompts/`, `tales/`, `epics/`, `legends/`, and `beads/`.
- It omits the now-canonical `myths/` and `research/` directories.
- `src/sase/sdd/files.py` already lists `myths/` and `research/` in generated README content and canonical SDD-root
  detection.
- Existing tests verify the image resource exists and that `sase sdd init` copies an asset, but they do not validate the
  visual contents of the PNG.

## Product Direction

Keep the visual practical and README-friendly:

- Preserve the existing documentation-diagram tone: light background, high contrast, restrained colors, no fantasy-map
  styling.
- Keep the output at 1600x900 so the asset remains stable in GitHub Markdown and package data.
- Show seven canonical directories:
  - `prompts/` - user prompts and snapshots
  - `tales/` - task-level plans
  - `epics/` - multi-phase plans
  - `legends/` - roadmap and strategy
  - `myths/` - long-horizon context
  - `research/` - findings and options
  - `beads/` - executable work tracking
- Make the flow clear: `prompts/` feed planning, planning and research/context inform work, and `beads/` tracks
  execution.

## Image Strategy

Use the `imagegen` skill's default built-in GPT image path for the raster visual base. Do not depend on GPT-rendered
text for correctness.

Recommended approach:

1. Generate a clean, text-free diagram base with GPT image.
   - Ask for a 16:9 technical documentation diagram with seven empty labeled regions.
   - Request no rendered words, pseudo-text, watermarks, logos, or decorative fantasy elements.
   - Reserve simple blank panels or cards for labels.

2. Add final text deterministically with local image tooling.
   - Use ImageMagick, Pillow, or another available local tool to overlay crisp labels and short descriptions.
   - Keep text large enough to read when the README image is scaled down.
   - Use consistent label placement and accessible contrast.

3. If GPT image output already contains hallucinated or unreadable text, reject it and regenerate once with a stricter
   no-text prompt.

This satisfies the request to use GPT image while avoiding the known weakness of generated text in documentation assets.

## Implementation Steps

1. Confirm the two existing asset paths are byte-identical before replacement.
2. Generate one or more GPT image candidates using the built-in image generation tool.
3. Inspect the candidate visually and select the cleanest base.
4. Post-process to 1600x900 PNG and overlay deterministic labels for all seven directories.
5. Replace `src/sase/sdd/assets/sdd-directory-map.png`.
6. Copy the same final bytes to `sdd/assets/sdd-directory-map.png`.
7. Leave `src/sase/sdd/files.py` and README Markdown unchanged unless the generated asset reveals a concrete need for an
   alt-text update.

## Validation

Run these checks after asset replacement:

- Visually inspect the final PNG at full size.
- Confirm the source and generated copies match with `cmp`.
- Confirm dimensions and file type with `identify` or `file`.
- Run focused SDD tests:
  - `.venv/bin/pytest tests/main/test_sdd_handler.py tests/test_sdd_paths.py`
- Run `just install` first if the workspace editable install is stale.
- Run `just check` before finishing, because repo memory requires it after file changes.

## Risks

- GPT image may include fake text or visually busy panels. Mitigation: generate a text-free base and overlay labels
  locally.
- Seven directories can make the map crowded. Mitigation: use concise labels and a two-row or grouped layout instead of
  forcing all planning directories into the old three-lane composition.
- The generated image may not match the prior style exactly. Mitigation: preserve the existing 16:9 documentation style,
  color restraint, and deterministic text overlay.

## Non-Goals

- Do not change SDD directory semantics.
- Do not change `sase sdd init` copy behavior.
- Do not add runtime image generation.
- Do not modify tests unless validation reveals an existing test assumption tied to the old asset.
