---
create_time: 2026-05-02 00:13:44
status: done
prompt: sdd/prompts/202605/sdd_directory_map_redesign.md
---
# Plan: Replace SDD Directory Map With a Practical Diagram

## Goal

Replace the current mythic SDD directory map image with a clearer, more useful documentation graphic generated with GPT
image tooling. Preserve the existing package and generated-tree mechanics unless the new image needs a small README text
adjustment for clarity.

The current image succeeds as a playful visual, but it does not teach the user enough. The replacement should help a
reader understand what each SDD directory is for and how information moves through the system at a glance.

## Current Shape

- The packaged source asset is `src/sase/sdd/assets/sdd-directory-map.png`.
- `sase sdd init` copies that source asset to `<sdd-root>/assets/sdd-directory-map.png`.
- `SDD_README_CONTENT` in `src/sase/sdd/files.py` links to it with `![SDD directory map](assets/sdd-directory-map.png)`.
- The generated repo copy lives at `sdd/assets/sdd-directory-map.png`.
- Tests already cover asset creation, idempotence, README reference text, path resolution, and package-resource
  visibility.

This means the likely implementation should replace the two PNG copies and only touch code/tests if the README alt text
or nearby explanatory Markdown changes.

## Product Direction

Create a documentation-first visual, not a fantasy map:

- Overall style: clean technical/product documentation illustration, light background, high contrast, minimal ornament.
- Composition: horizontal 16:9 or near-16:9, readable when embedded in GitHub Markdown at typical README widths.
- Core message: `prompts/` are source inputs; `tales/`, `epics/`, and `legends/` are planning artifacts at increasing
  scope; `beads/` tracks executable work.
- Relationship model:
  - `prompts/` flows into planning artifacts.
  - `tales/` covers task-sized plans.
  - `epics/` covers larger multi-phase plans.
  - `legends/` covers broad roadmap or strategy context.
  - `beads/` is the execution tracker that can be linked from plans.
- Tone: polished and approachable, but restrained. No castles, parchment maps, magical towers, heavy storybook framing,
  or joke-driven visuals.

## Image Generation Strategy

Use the `imagegen` skill's default built-in GPT image path for the base image.

Prompt GPT image for a clean, text-free infographic base with five clearly separated zones, simple document/folder/board
metaphors, and reserved empty label areas. The prompt should explicitly request no rendered words, no pseudo-text, no
watermarks, and no decorative fantasy elements.

Do not rely on generated text. After selecting the best base, add all final labels and explanatory text
deterministically with local tooling. This keeps the final image readable and avoids model hallucinated labels.

Preferred final diagram structure:

- Left: `prompts/` input inbox or document stack.
- Center: three planning lanes/cards, visually ordered by scope: `tales/` = task plan, `epics/` = multi-phase plan,
  `legends/` = roadmap/strategy.
- Right or bottom-right: `beads/` execution tracker board/list.
- Arrows:
  - `prompts/` -> each planning scope.
  - planning scopes -> `beads/`.
- Optional small title inside the image: `SDD directory map`.

## Technical Implementation Plan

1. Generate two or three GPT image candidates.
   - Keep the prompt narrowly focused on documentation utility.
   - Prefer a base image with strong layout, empty label zones, and minimal visual clutter.
   - Reject candidates with incorrect text, pseudo-text in prominent areas, excessive decoration, or unclear flow.

2. Post-process the selected candidate.
   - Resize or crop to a stable README-friendly dimension, likely around 1600x900.
   - Overlay crisp labels and short descriptions using deterministic local tooling such as ImageMagick.
   - Keep text concise enough to remain readable when scaled down:
     - `prompts/` - user prompts and snapshots
     - `tales/` - task-level plans
     - `epics/` - multi-phase plans
     - `legends/` - roadmap and strategy
     - `beads/` - executable work tracking
   - Use accessible contrast and avoid placing text over busy image regions.

3. Replace project assets.
   - Write the final image to `src/sase/sdd/assets/sdd-directory-map.png`.
   - Copy or regenerate the repo README asset at `sdd/assets/sdd-directory-map.png` so it matches the packaged source
     byte-for-byte.
   - Keep the filename and relative README path unchanged unless there is a clear reason to change them.

4. Consider README copy only if needed.
   - If the new image is self-explanatory, leave `SDD_README_CONTENT` untouched.
   - If changing the alt text or adding one sentence materially improves accessibility, update the README content and
     the existing tests that assert the Markdown image line.
   - Avoid broader README rewrites.

5. Keep packaging behavior unchanged.
   - No `pyproject.toml` changes are expected because the current wheel already includes the PNG under `src/sase`.
   - Rebuild or inspect a wheel after replacement to verify the binary asset still ships.

## Validation

Run visual and technical checks:

- Inspect the final PNG locally at full size.
- Confirm the generated repo copy matches the package asset, for example with `cmp`.
- Run focused SDD tests: `.venv/bin/pytest tests/main/test_sdd_handler.py tests/test_sdd_paths.py`
- Build a wheel and verify it contains `sase/sdd/assets/sdd-directory-map.png`.
- Run `just install` if this workspace needs refreshed dependencies.
- Run `just check` before finishing because this repo requires it after file changes.

## Risks and Mitigations

- GPT image may still include fake text or clutter. Mitigation: request a text-free base, generate multiple candidates,
  and reject bad outputs.

- Deterministic overlays may look disconnected from the generated art. Mitigation: prompt for reserved blank label areas
  and use a restrained documentation style.

- The final image may be too dense in README rendering. Mitigation: use fewer words, larger labels, high contrast, and a
  16:9 layout that survives downscaling.

- README tests may fail if alt text changes. Mitigation: keep the existing Markdown line unless there is a concrete
  accessibility or clarity improvement.

## Non-Goals

- Do not change SDD directory semantics.
- Do not change `sase sdd init` path resolution or copy behavior.
- Do not introduce runtime image generation or network dependencies.
- Do not add new generated-image source variants to the repo unless there is a deliberate reason to preserve them.
