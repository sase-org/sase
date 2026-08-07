---
pdf: false
---

# SASE README Overview Prompt

## Target

- Documents: `README.md` and `docs/index.md`
- README insertion point: centered hero block below the user-facing badges
- Docs homepage insertion point: existing hero visual
- Final image: `docs/images/sase_overview.png`
- Final size: 1672×941 PNG, sRGB
- Alt text: "One developer using SASE to run parallel coding agents in isolated
  workspaces with tracked, reviewable results"

## Final GPT Image Prompt

The built-in GPT Image tool generated a completely text-free structural base. Exact
labels were added locally so the committed image contains no model-generated text.

```text
Use case: infographic-diagram
Asset type: dark 16:9 landing-page hero infographic base for the GitHub README and documentation homepage of a software engineering tool
Primary request: Create a polished, completely text-free structural base for a bold technical infographic showing one developer coordinating parallel coding agents through a control system. This base will receive exact deterministic labels later, so every label zone must be blank and there must be absolutely no readable words, letters, numbers, pseudo-text, tiny fake text, or watermark.
Scene/backdrop: near-black slate canvas matching GitHub dark mode, approximately #0d1117, with crisp thin light strokes, subtle dark panels, high contrast, and no texture.
Composition/framing: 16:9 landscape with generous safe margins. Reserve a clean centered header zone across the top for a large title and smaller subtitle. Below it, build one clear left-to-right flow in five beats. Beat 1 at far left: one developer node represented by a generic thin-line person icon, with two compact blank chips beneath it for interactive and scheduled controls. Beat 2 left-center: one wide blank prompt pill represented by a generic message/document icon. Beat 3 in the center: three equal isolated workspace cards side by side, each with a blank title zone, a blank agent pill, and a generic terminal/folder/branch line icon; show obvious fan-out arrows from the prompt into all three cards. Beat 4 beneath the workspace cards: one long shared durable-state rail split into four equal blank segments, connected from all three workspaces. Beat 5 at far right: three compact stacked outcome cards with blank label zones, connected from the durable-state rail. Use one unambiguous forward arrow path between every beat, with arrowheads fully inside the canvas.
Style/medium: crisp flat vector-like technical architecture illustration rendered as a high-resolution raster, terminal-inspired, professional and minimal. Slightly rounded rectangles, thin borders, disciplined spacing, no fake screenshot.
Color palette: near-black slate #0d1117 background; teal #00D7AF for interactive coordination and state connections; light blue #87D7FF for workspaces and parallel fan-out; coral #FF5F5F for scheduled controls; restrained amber and green for small status accents; warm off-white for primary strokes.
Constraints: no company or product logos, no provider logos, no mascots, no decorative gradients, no starbursts, no fake terminal text, no code snippets, no readable glyphs beyond generic line icons, no letters, no numerals, no pseudo-text, no watermark. Keep every label zone empty, clean, and large enough for DejaVu Sans labels at an eventual 1672x941 canvas. Do not crop any panel or arrow. The structure must remain legible when displayed at 830 pixels wide.
```

## Deterministic Post-Processing Record

The generated base already matched the 1672×941 target. A transparent SVG overlay
rendered with ImageMagick and DejaVu Sans supplied every visible label. The overlay also
removed a direct workspace-to-outcome edge and a stray lower arrow, then made the
durable-state rail the single source of the outcome spine. The final image was stripped
and normalized to sRGB:

```bash
magick -background none "$LABELS_SVG" "$LABELS_PNG"
magick "$BASE_PNG" "$LABELS_PNG" -compose over -composite \
  -strip -colorspace sRGB docs/images/sase_overview.png
```

The deterministic labels are:

- Header: `SASE` and `Structured Agentic Software Engineering`
- Operator controls: `You`, `ACE TUI` / `interactive`, and `AXE` / `scheduled`
- Input: `ONE PROMPT`, `Prompt`, `XPrompt`, and `Workflow`
- Fan-out: `PARALLEL AGENTS`; `Workspace 1` / `Claude Code`; `Workspace 2` / `Codex`;
  and `Workspace 3` / `Antigravity CLI`
- Durable state: `ChangeSpecs`, `Beads`, `Commits`, and `Artifacts`
- Outcomes: `Reviewed PRs`, `Tracked runs`, and `Scheduled work`

## Final Review

- Inspected at full 1672×941 resolution and at the README display width of 830 pixels.
- Confirmed exact label spelling, high contrast, clear fan-out arrows, complete safe
  margins, and no generated pseudo-text, logos, fake screenshots, gradients, cropping,
  or watermark.
- Confirmed the same asset works in the dark README banner and the existing
  `docs/index.md` hero slot.
- Final SHA-256: `5c2ef949d060f5239eacaf8e86e1962aa9def546a84765bfe1dc4fc72c190547`.
