---
create_time: 2026-03-28 17:07:24
status: done
prompt: sdd/prompts/202603/bead_create_type_flag.md
---

# Plan: Migrate `sase bead create` to `--type` flag

## Motivation

The `sase bead create` command currently uses two separate flags (`--plan` and `--parent`) that implicitly determine the
bead type. This migration consolidates them into a single `--type` option with explicit type syntax: `plan(<plan_file>)`
or `phase(<bead_id>)`.

## Design Decision: Nested Plans

Currently `--plan plan.md --parent beads-001` creates a nested plan (type=PLAN with parent_id set). With the new
`--type` syntax, this becomes a two-argument form: `plan(<plan_file>,<parent_id>)`. This preserves full backward
compatibility of behavior.

## New CLI Syntax

```bash
# Create a plan bead linked to a plan file
sase bead create -t "New feature" --type plan(plan.md)

# Create a phase bead under a parent
sase bead create -t "Sub-task" --type phase(beads-001)

# Create a nested plan (plan with parent)
sase bead create -t "Sub-plan" --type plan(plan.md,beads-001)
```

Short option: `-T` (since `-t` is taken by `--title`).

## Parsing Logic

Parse the `--type` value with a regex like `^(plan|phase)\((.+)\)$`, then split the inner content on `,` to extract
arguments:

- `plan(<path>)` → IssueType.PLAN, design=path, parent_id=None
- `plan(<path>,<parent_id>)` → IssueType.PLAN, design=path, parent_id=parent_id
- `phase(<bead_id>)` → IssueType.PHASE, parent_id=bead_id

## Implementation Steps

### 1. Parser (`src/sase/main/parser_bead.py`)

Remove `--plan` and `--parent` arguments. Add:

```python
bead_create_parser.add_argument(
    "-T",
    "--type",
    required=True,
    help="Bead type: plan(<plan_file>) or phase(<parent_bead_id>)",
)
```

Note: `--type` is required (replaces the previous "at least one of --plan or --parent" validation).

### 2. CLI handler (`src/sase/bead/cli.py`)

Add a parsing function for the `--type` value. Update `handle_bead_create` to use it instead of `args.plan` /
`args.parent`. Update `handle_bead_onboard` quick-start examples. Update the error message that currently says "at least
one of --plan or --parent is required".

### 3. Documentation (`docs/beads.md`)

- Update Quick Start examples (lines 26-27)
- Update `sase bead create` flag table (lines 114-122)
- Update "Plan File Linking" section (line 215)

### 4. Documentation (`docs/configuration.md`)

- Update `sase bead create` flag table (lines 734-736)

### 5. XPrompt config (`src/sase/default_config.yml`)

- Update `bd/new_epic` xprompt that references `--plan` option (lines 243-244)
