---
diagram: docs/images/xprompt-resolution-infographic.png
embedded_in: docs/xprompt.md
phase: final-review
pdf: false
---

# Final Review: `xprompt-resolution-infographic.png`

## Outcome

The regenerated infographic is accurate enough to embed in `docs/xprompt.md`. It preserves the useful three-zone inputs
→ resolution → outcomes structure while replacing the stale technical content in the prior PNG.

## Accuracy Review

The final labels match the authoritative launch and expansion model:

1. Workspace references dispatch before prompt execution; bare prompts default to `#git:home`.
2. Raw alias substitution happens before fenced-block and disabled-region masking.
3. Expansion iterates through parsing, first-wins lookup, argument and `$(cmd)` processing, typed-input validation, and
   Jinja2/legacy rendering for at most 100 passes.
4. Protected text is restored before prompt directives are extracted from the fully expanded text.
5. Inline expansion, standalone workflows, and depth-capped multi-agent fan-out are runtime outcomes. Workflow graph and
   explain output are presented separately as developer tools.

The discovery panel mirrors all 17 rows in the current `docs/xprompt.md` table. Canonical project and home directories
precede their read-compatible legacy locations; canonical and legacy project config entries remain distinct; user
overlays/base config, plugin/package defaults, plugin xprompt entry points, and both package-provided xprompt locations
retain their documented order.

## Visual Review

The 1672×941 PNG was inspected at full resolution for:

- uncropped section tabs, panels, labels, and arrowheads;
- readable dark labels on light deterministic backing areas;
- a visible loop through all iterative expansion stages;
- a direct protected-content connection to masking;
- distinct runtime and developer-tool regions; and
- absence of model-generated text, pseudo-text, logos, or watermarks.

The 17-row discovery panel is intentionally the densest part of the asset. Its monospace labels remain readable at full
resolution, while the larger stage labels preserve the diagram's scan path at normal documentation width.

## Resolved Problems From The Previous Asset

- Removed the obsolete keyword-trigger and dynamic-memory rows.
- Put aliases before masking and moved directive extraction after full expansion.
- Added the iterative expansion loop and the missing argument-time `$(cmd)` step.
- Replaced the stale collapsed discovery stack with the canonical 17-row ordering.
- Corrected `#name` / `#!name` semantics and changed fan-out from “one-level” to depth-capped.
- Renamed the inline outcome and visually demoted graph/explain to developer tooling.

Final SHA-256: `a2b5e5e55e8af32966cb59e6806982c15d7fc19ff70583e327d6a8a280b19174`.
