---
create_time: 2026-05-02 19:26:41
status: done
---
# Plan: Regenerate SDD Directory Map With Hierarchical Semantics

## Goal

Regenerate the SDD directory map PNGs so the diagram reflects the intended SDD relationship model:

- `myths/` contain `legends/`
- `legends/` contain `epics/`
- `epics/` contain `tales/`
- `beads/` are created for all of those planning tiers
- `research/` files are separate from the containment hierarchy but may be referenced by any tier
- `prompts/` remain the captured inputs that lead to SDD artifacts

The current image incorrectly presents `tales/`, `epics/`, `legends/`, `myths/`, and `research/` as mostly peer
directories flowing independently into `beads/`. This should be replaced with a hierarchy-first visual.

## Scope

Replace the two checked-in PNG copies with identical final bytes:

- `src/sase/sdd/assets/sdd-directory-map.png`
- `sdd/assets/sdd-directory-map.png`

No runtime behavior should change. `src/sase/sdd/files.py`, the generated SDD README content, and tests should remain
unchanged unless validation exposes a concrete mismatch outside the image.

## Product Direction

The new diagram should be practical documentation, not a decorative illustration. Preserve the README-friendly tone of a
light technical diagram, but make the conceptual model obvious at a glance.

Recommended composition:

- A central nested stack or nested containment diagram:
  - outer container: `myths/` - long-horizon context
  - inside it: `legends/` - roadmap and strategy
  - inside it: `epics/` - multi-phase plans
  - inside it: `tales/` - task-level plans
- A `prompts/` source block feeding into the hierarchy, ideally pointing at the level created from a prompt rather than
  implying that every prompt always starts at the same tier.
- A `beads/` execution tracking block connected to each planning tier, not just the hierarchy as a whole. Use multiple
  small connectors or a bracket/rail labeled by deterministic local text, so the image communicates that beads can be
  created for myths, legends, epics, and tales.
- A separate `research/` block outside the containment stack. Connect it with light dashed reference lines to the
  hierarchy, not a primary flow arrow, to show it can inform or be referenced by any tier.

Text labels should be short enough to stay readable when GitHub scales the README image:

- `prompts/` - captured inputs
- `myths/` - long-horizon context
- `legends/` - roadmap and strategy
- `epics/` - multi-phase plans
- `tales/` - task-level plans
- `research/` - referenced findings
- `beads/` - work tracking for every tier

## Image Strategy

Use GPT image generation for the visual base, but do not rely on generated text for correctness.

1. Generate a text-free 16:9 technical diagram base with GPT image.
   - Ask for a light README-style diagram with a nested central containment shape, side source/reference blocks, and an
     execution tracker block.
   - Request no rendered text, pseudo-text, logos, watermarks, or decorative fantasy styling.
   - Ask for blank regions with enough room for deterministic labels.

2. Overlay all final labels and descriptions locally.
   - Use ImageMagick or Pillow for crisp deterministic typography.
   - Keep output dimensions at `1600x900`.
   - Preserve `srgba` PNG output with an alpha channel to match the existing asset profile.

3. Reject any GPT image candidate that includes fake text, ambiguous containment, crowded panels, or arrows that imply
   research is part of the hierarchy.

This keeps the request's GPT-image requirement while making the exact documentation semantics deterministic.

## Implementation Steps

1. Confirm current workspace state and current asset metadata.
2. Confirm the two existing asset copies are identical before replacement.
3. Use the `imagegen` skill to generate one or more blank diagram bases matching the nested hierarchy layout.
4. Inspect the candidate visually and select the clearest base.
5. Post-process the selected base:
   - normalize to `1600x900`
   - clear or ignore any virtual canvas metadata
   - overlay deterministic labels and descriptions
   - draw or reinforce connector lines locally if GPT output does not clearly express the hierarchy and cross-reference
     relationships
6. Replace `src/sase/sdd/assets/sdd-directory-map.png`.
7. Copy the same bytes to `sdd/assets/sdd-directory-map.png`.
8. Inspect the final image at full size before running checks.

## Validation

After the asset replacement:

- Visually inspect the final PNG and verify:
  - nested order is `myths/` -> `legends/` -> `epics/` -> `tales/`
  - `research/` is outside the hierarchy and cross-referenced
  - `beads/` is connected to all planning tiers
  - all labels are exact and readable
- Run `cmp src/sase/sdd/assets/sdd-directory-map.png sdd/assets/sdd-directory-map.png`.
- Run `identify` or `file` to confirm both images are `1600x900` PNGs with `srgba`/alpha output.
- Run `just install` if needed before tests, per workspace memory.
- Run focused SDD tests:
  - `.venv/bin/pytest tests/main/test_sdd_handler.py tests/test_sdd_paths.py`
- Run `just check` before finishing because file changes in this repo require it.

## Risks

- GPT image may still produce fake text or confuse containment. Mitigate by generating a text-free base and reinforcing
  final geometry locally.
- Nested containment can become visually dense. Mitigate with broad nested bands rather than tiny boxes, and keep labels
  concise.
- Multiple bead connectors may clutter the image. Mitigate with a single side rail or bracket from all planning tiers to
  `beads/`, plus one deterministic label explaining "every tier".

## Non-Goals

- Do not change SDD directory creation, validation, or list behavior.
- Do not revise SDD README prose unless separately requested.
- Do not create runtime-generated diagrams.
- Do not commit until explicitly requested or a configured post-completion workflow requires it.
