---
create_time: 2026-05-01 23:55:12
status: done
prompt: sdd/prompts/202605/sdd_mythic_directory_image.md
---
# Plan: Add Mythic SDD Directory Image

## Goal

Generate a fun, mythic-themed image that explains how the SDD directories relate to each other, ship that image with the
`sase` Python package, and update `sase sdd init` so every generated `sdd/README.md` links to the image from the user's
own SDD tree.

## Current Shape

- `sase sdd init` is registered in `src/sase/main/parser_sdd.py`, dispatched from `src/sase/main/sdd_handler.py`, and
  implemented by `write_sdd_readme()` in `src/sase/sdd/files.py`.
- The README content is a deterministic module-level string, `SDD_README_CONTENT`, and `write_sdd_readme()` always
  overwrites stale generated content.
- The canonical SDD directories are `prompts/`, `tales/`, `epics/`, `legends/`, and `beads/`.
- The project uses hatchling with `packages = ["src/sase"]`; package-data handling for a new binary asset needs to be
  verified by building or inspecting a wheel.
- Existing focused tests for this surface live in `tests/main/test_sdd_handler.py` and `tests/test_sdd_paths.py`.

## Product Design

Create one polished raster image that reads like a whimsical fantasy map of the SDD realm:

- `prompts/` is the spark or scroll archive where an idea begins.
- `tales/` is a campfire trail for task-sized plans.
- `epics/` is a larger quest route, mountain pass, or fortress for multi-phase work.
- `legends/` is a high tower, constellation, or ancient map edge for roadmap-scale direction.
- `beads/` is a quest ledger or string of enchanted beads that tracks the work.

The image should feel fun and aligned with the `tales` / `epics` / `legends` / `myths` theme, but it must still be
usable documentation. The relationship should be clear: prompts feed plan-like artifacts; tales, epics, and legends
represent increasing planning scope; beads track execution. Avoid relying solely on generated text, because raster text
from image generation can be unreliable. Prefer GPT image generation for the illustrated base, then add any final
labels, arrows, or small legend text deterministically during post-processing if the generated text is not crisp.

## Technical Design

1. Generate the image with the `imagegen` skill's default built-in GPT image path.
   - Use a production prompt for a horizontal documentation illustration, likely around a 16:9 composition.
   - Keep the style warm and storybook-like, but avoid dark, blurred, or overly decorative output that obscures the
     directory relationships.
   - Inspect the generated image before using it. If labels are incorrect or unreadable, keep the illustration as the
     background and add deterministic labels locally.

2. Store the package source asset under the SDD package.
   - Suggested source path: `src/sase/sdd/assets/sdd-directory-map.png`.
   - This keeps the asset owned by the SDD feature instead of scattering documentation assets at the package root.
   - Use a stable, lowercase filename so generated README links are predictable.

3. Ensure the asset is included in user installations.
   - Verify whether hatchling includes the PNG automatically when it is under `src/sase`.
   - If not, update `pyproject.toml` with the narrowest package-data or force-include configuration needed for the PNG.
   - Add a test that uses `importlib.resources.files("sase.sdd").joinpath("assets/sdd-directory-map.png")` so missing
     package data fails quickly in editable installs and built wheels can be smoke-tested.

4. Have `sase sdd init` copy the packaged asset into the target SDD tree.
   - Suggested generated path: `<sdd-root>/assets/sdd-directory-map.png`.
   - README Markdown should link relatively, e.g. `![SDD directory map](assets/sdd-directory-map.png)`.
   - Copying into the user's SDD tree makes the README portable in GitHub, local editors, and rendered Markdown instead
     of linking to a machine-specific site-packages path.
   - The copy should be deterministic and idempotent. Re-running `sase sdd init` should refresh both README and asset
     from the packaged source, matching the current "overwrite stale generated docs" behavior.

5. Keep path resolution behavior unchanged.
   - `--path <project-root>` should write `<project-root>/sdd/README.md` and `<project-root>/sdd/assets/...`.
   - `--path <sdd-root>` should write `<sdd-root>/README.md` and `<sdd-root>/assets/...`.
   - Default behavior should still target `./sdd`.

6. Update tests.
   - Extend the existing init handler test to assert the asset exists next to the generated README and that the README
     references it with a relative Markdown image link.
   - Extend or add a path helper test if a helper such as `resolve_sdd_asset_path()` is introduced.
   - Add a package-resource test that confirms the source PNG is discoverable via `importlib.resources`.
   - Keep tests focused on behavior and packaging visibility rather than image content semantics.

7. Update this repository's generated README and asset.
   - After implementation, run `sase sdd init` in this repo so `sdd/README.md` includes the image link and
     `sdd/assets/sdd-directory-map.png` exists.
   - If deterministic post-processing creates labels, keep the generated source or final output only as needed; avoid
     committing temporary image variants.

8. Verify.
   - Run the focused SDD tests, including any new package-resource test.
   - Run formatting if Markdown or Python files changed.
   - Build or inspect a wheel to confirm the PNG ships in installation artifacts.
   - Run `just install` if needed for this workspace, then `just check` before finishing because this repo requires it
     after code changes.

## Non-Goals

- Do not add a new SDD directory kind named `myths`; use the mythic theme visually while keeping the canonical directory
  model unchanged.
- Do not make `sase sdd init` download images or depend on network access at runtime.
- Do not require users to have GPT image access installed; the generated PNG is a checked-in package asset.
- Do not change SDD validation, link repair, bead behavior, or the existing prompt/plan frontmatter model.
