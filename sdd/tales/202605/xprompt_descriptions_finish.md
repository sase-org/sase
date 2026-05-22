---
create_time: 2026-05-22 14:03:16
status: wip
prompt: sdd/prompts/202605/xprompt_descriptions_finish.md
---
# Finish xprompt description support for sase-3w

## Findings

The epic's child beads are closed, but the implementation is incomplete in the workspace-matched sibling repositories:

- `sase-core` does not preserve input descriptions in native catalog input records or mobile/editor input wire data, and
  native workflow catalog records do not carry workflow descriptions.
- `sase-nvim` fallback picker and Telescope surfaces ignore xprompt and input descriptions returned by
  `sase xprompt list`.
- `sase-github` plugin xprompt YAML files have no top-level descriptions and no input descriptions.

## Plan

1. Update `sase-core` native catalog and editor/gateway wire paths so optional xprompt, workflow, and input descriptions
   are parsed, preserved, serialized, and shown in completion/hover documentation where applicable.
2. Add focused Rust coverage for catalog parsing, input wire serialization, completion documentation, hover text, and
   frontmatter diagnostics.
3. Update `sase-nvim` fallback picker and Telescope preview to consume and show xprompt/workflow and input descriptions,
   and include descriptions in local fallback filtering where the picker owns the filtering.
4. Add focused Lua tests for formatting, filtering, and preview rendering with descriptions.
5. Add descriptions to `sase-github` plugin xprompt YAML files, including each declared user input.
6. Run the required checks for every modified repo, plus the main repo checks needed after bead and plan metadata
   updates.
7. Update the epic plan frontmatter status to `done`, close child beads if any were reopened during repair, close epic
   bead `sase-3w`, and run `just pyvision` if available after the epic is closed.
