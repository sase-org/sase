---
status: wip
---

Can you help me create a new `#big` xprompt YAML workflow? This workflow should be used to complete large units of work
by:

- saving the prompt (given as an input arg) in a markdown file in the prompts/ directory
- creating a markdown plan file with (ideally parallizable) phases in the plans/ directory
- creating an epic bead associated with the plan file
- creating child beads associated with each phase and then setting up the child bead dependencies correctly
- adding the epic bead ID to the plan file (for example, see the plans/planning_coding_question.md file's frontmatter)
- run the following loop:
  - run the `tools/sase_bd ready --parent <epic_bead_id>` command and then iterate over each ready child
  - run the `tools/sase_bd list --parent <epic_bead_id>` command to get the child bead IDs and then adding those child
    bead IDs to the plan file (for example, see the plans/planning_coding_question.md file's frontmatter)

### Migrating the `/bd:*` Slash Commands to Xprompt Parts

All of the `/bd:*` slash commands (defined in the chezmoi repo) should have equivalent xprompt parts defined in markdown
files in the xfiles/ directory.
