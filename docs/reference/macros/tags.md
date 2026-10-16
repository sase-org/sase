---
title: Macro tags
description: Available macro tags, their definitions, and tag-based lookup.
---

# Macro tags

This page lists macro tags and explains their lookup behavior.

## Tags

Macros and workflows can be annotated with semantic role tags. Tags enable
lookup-by-role instead of lookup-by-name, making the system extensible: a plugin or user
can override the CRS workflow by defining a higher-priority macro or workflow with
`tags: crs`.

### Available Tags

| Tag                            | Description                                                                                                                             |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| `vcs`                          | Workspace workflow macro (`#git`, `#gh`, or a plugin-provided ref) — wraps other embedded workflows, running setup/teardown around them |
| `crs`                          | Code Review Summary workflow (singleton role)                                                                                           |
| `fix_hook`                     | Fix hook workflow (singleton — used by axe to find the hook-fix agent)                                                                  |
| `rollover`                     | Marks workflows whose embedded references carry forward to follow-up agent steps                                                        |
| `mentor`                       | Mentor review prompt workflow                                                                                                           |
| `commit`                       | Commit workflow (appended by mentor review `A` key for direct commit)                                                                   |
| `propose`                      | Propose workflow (appended by mentor review `a` key for propose-style amend)                                                            |
| `make_mentor_changes`          | Apply accepted mentor comments workflow (launched by mentor review `Enter`)                                                             |
| `diff_file`                    | Injects the PR diff into the mentor prompt                                                                                              |
| `append_to_pr`                 | VCS-specific post-commit prompt appended when the active commit method creates a pull request                                           |
| `append_to_commit_and_propose` | VCS-specific post-commit prompt appended when the active commit method creates a commit or proposal                                     |
| `create_epic_bead`             | Plan-approval Epic flow — creates the plan file, beads, and the epic agent prompt                                                       |
| `work_phase_bead`              | Per-phase agent prompt used by `sase bead work` (input: `bead_id`)                                                                      |
| `work_task_bead`               | Task-agent prompt used by `sase bead work` (input: `bead_id`)                                                                           |
| `land_epic`                    | Final land agent prompt used by `sase bead work`: verifies, integrates, and closes the epic                                             |

### Defining Tags

Tags can be defined in three places:

**YAML workflow files** (`.yml`):

```yaml
tags: vcs, rollover       # comma-separated string
# or
tags: [vcs, rollover]     # list format
```

**Markdown front matter** (`.md`):

```markdown
---
name: fix_hook
tags: fix_hook
---

Fix the failing hook...
```

**Config-based macros** (`sase.yml`):

```yaml
macros:
  my_crs:
    content: "Review the code..."
    tags: [crs]
```

### Tag-Based Lookup

The `get_by_tag()` function returns the highest-priority macro/workflow matching a tag,
respecting the standard [discovery order](discovery.md#discovery-order). This means higher-priority
sources (e.g., project-local) can override built-in tagged macros, even when the
override uses a different name. `get_by_tag_strict()` applies the same ranking and
raises only when multiple matches remain at the highest discovery rank.

```python
from sase.macro.tags import MacroTag, get_by_tag

crs_wf = get_by_tag(MacroTag.crs)
fh_wf = get_by_tag(MacroTag.fix_hook)
```

### Backward Compatibility

The legacy `wraps_all: true` field on workflows is still supported — it automatically
adds the `vcs` tag. New workflows should use `tags: vcs` instead.

Source: `src/sase/macro/tags.py`, `src/sase/macro/models.py`

## Related

- [Macro reference](index.md)
- [Workflow specification](../workflows.md)
