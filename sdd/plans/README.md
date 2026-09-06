# Plans

The `plans/` directory stores implementation plans. Every plan must declare a plan-file
`tier` in YAML frontmatter: `tale` for focused task plans or `epic` for larger work that
may span multiple phases or beads. This plan-file tier is separate from bead tier
metadata. Canonical committed run prompts are archived in the agents sidecar under
`prompts/<YYYYMM>/`; historical `prompts/` subdirectories here remain readable during
migration.
