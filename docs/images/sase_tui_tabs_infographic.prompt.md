---
pdf: false
---

# SASE TUI Tabs Infographic Prompt

!!! warning "Historical generation record"

    This prompt produced the retired pre-Artifacts ACE diagram. Current ACE navigation is **Agents · Artifacts · Axe**.
    Artifacts has **Commits · Beads · Bugs · PRs · Files** as its top-level views, with **Plans · Chats · Other** nested
    under Files. The PNG is no longer embedded in active documentation; do not reuse it without regenerating the
    composition and labels for the current tab model.

## Target

- Document: retired from active documentation
- Former insertion point: `docs/index.md`, "How the pieces connect" image grid
- Image: `docs/images/sase_tui_tabs_infographic.png`
- Alt text: `SASE ACE TUI tab overview`

## Final GPT Image Prompt

```text
Use case: infographic-diagram
Asset type: 16:9 technical documentation infographic base for a GitHub Markdown page
Primary request: Create a clean architecture-infographic base showing the SASE ACE TUI as one shared control plane wrapping three tabs: PRs, Agents, and AXE. IMPORTANT: use no readable words, no letters, no numbers, and no fake text; leave blank label space for deterministic labels to be added later.

Scene/backdrop: light neutral software documentation diagram on an off-white background.

Composition/framing: landscape 16:9. Draw one large rounded application window frame with shared persistent chrome. At the top inside the frame, show three connected tab pills side by side using these accent colors: teal for the left tab, light blue for the middle tab, coral red for the right tab. Include a small indicator stack at top right as four compact icon-only chips, and a small keyboard navigation chip near the tabs using only abstract arrow glyphs, no text. Inside the shared frame, place three equal vertical panels aligned under the tab pills, with generous blank spaces for three labeled rows in each panel. Each panel should have three horizontal subpanels for surfaces, lifecycle, and actions, but the subpanels must be blank except for simple abstract icons.

Bottom area: below the three tab panels but still visually part of the same control plane, show a clearly separated conceptual lifecycle rail with four connected nodes from left to right. Put subtle tinted bands behind the first node in teal, the middle two nodes in blue, and the final node in red, showing tab ownership without any text. Make the rail obviously conceptual, separated by a thin divider from the tab panels.

Style/medium: crisp flat vector-like architecture diagram, professional documentation infographic, light background, thin dark-gray strokes, restrained mixed accents, consistent with software manual diagrams.

Color palette: neutral white/off-white base; teal #00D7AF, light blue #87D7FF, coral red #FF5F5F, muted amber/green only as small status accents.

Constraints: no logos, no screenshots, no decorative gradients, no terminal text, no readable text, no letters, no numbers, no watermark. Leave large clean blank areas for later DejaVu Sans labels. Keep all shapes sharp and balanced; readable at 900px wide.
```

## Post-Processing Notes

Generated with the built-in image generation tool, copied into
`docs/images/sase_tui_tabs_infographic.png`, resized to the existing 1672x941 documentation image
size, and labeled deterministically with ImageMagick using DejaVu Sans.

The generated base is intentionally text-free. Final labels were added to show:

- Shared ACE chrome: connected tab pills, `Tab / Shift-Tab`, top-right indicators, and footer
  framing.
- Tab colors: PRs `#00D7AF`, Agents `#87D7FF`, AXE `#FF5F5F`.
- Per-tab `Surfaces`, `Lifecycle`, and `Actions` rows:
  - PRs: ChangeSpec list/detail, ancestors/children, PR status lifecycle,
    accept/mail/rebase/diff/checkout.
  - Agents: agent tree, retry chains, prompt/files/diffs/thinking detail, run lifecycle,
    resume/tag/kill/open.
  - AXE: BgCmd list, dashboard, daemon health, Lumberjack output, queued/running/done/errored
    lifecycle, daemon and log actions.
- A separated conceptual lifecycle rail: plan -> launch -> monitor -> land, with tinted ownership
  bands tying those phases back to the three tabs.
