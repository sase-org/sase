---
create_time: 2026-04-09 16:00:03
status: draft
prompt: sdd/prompts/202604/commit_type_aliases.md
---

# Plan: Short Aliases for `sase commit --type` Values

## Problem

The `sase commit --type` option currently requires verbose values: `create_commit`, `create_proposal`,
`create_pull_request`. These are fine for programmatic use (env vars, skill docs) but awkward for human CLI usage.

## Goal

Allow short aliases alongside the canonical names:

| Alias     | Canonical             |
| --------- | --------------------- |
| `commit`  | `create_commit`       |
| `propose` | `create_proposal`     |
| `pr`      | `create_pull_request` |

Both forms should work everywhere: `--type commit` and `--type create_commit` are equivalent.

## Design

**Resolve aliases at the CLI boundary** — the alias mapping lives in `workflow.py` (next to `VALID_METHODS`) and is
applied in `cl_handler.py` immediately after the method value is determined. Everything downstream continues to see only
canonical method names, so no other code needs to change.

The argparse `choices` list expands to include both canonical names and aliases so that `--type pr` doesn't get rejected
by the parser before our code even sees it.

## Phases

### Phase 1: Add alias mapping constant (`workflow.py`)

Add a `METHOD_ALIASES` dict next to the existing `VALID_METHODS` tuple:

```python
METHOD_ALIASES: dict[str, str] = {
    "commit": "create_commit",
    "propose": "create_proposal",
    "pr": "create_pull_request",
}
```

This follows the same pattern as `_DIRECTIVE_ALIASES` in `xprompt/directives.py`.

### Phase 2: Expand argparse choices (`parser_commands.py`)

Change the `choices` parameter to include both canonical values and aliases. Import `VALID_METHODS` and `METHOD_ALIASES`
from `workflow.py` and derive choices as `[*VALID_METHODS, *METHOD_ALIASES]`.

### Phase 3: Resolve aliases in the handler (`cl_handler.py`)

After the existing line that resolves `method` from args/env, add one line:

```python
method = METHOD_ALIASES.get(method, method)
```

This normalizes aliases from both `--type` and `$SASE_COMMIT_METHOD` to canonical form before passing to
`CommitWorkflow`.

### Phase 4: Update error message in workflow validation (`workflow.py`)

The `run()` method's error message currently shows only `VALID_METHODS`. Update it to also mention the available aliases
so users know about the short forms.

### Phase 5: Tests (`test_commit_cli.py`)

Add tests that:

- Parse each alias via `--type` and verify it resolves to the canonical method.
- Verify aliases work via `$SASE_COMMIT_METHOD` env var.

### Phase 6: Update SKILL.md files (chezmoi)

Update the three SKILL.md files (`dot_claude`, `dot_gemini`, `dot_codex`) to document the aliases in the flags section.
Keep the existing guidance to rely on `$SASE_COMMIT_METHOD` for the common case, but mention the short forms are
available when overriding with `--type`.
