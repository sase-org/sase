---
create_time: 2026-04-11 20:48:28
status: done
bead_id: sase-h
prompt: sdd/prompts/202604/init_skills_1.md
---

# Plan: `sase init-skills` Command

## Overview

Add a `sase init-skills` command that generates and deploys agent skill files (SKILL.md) from xprompt source files using
Jinja2 templating for per-provider customization. This follows **Approach E** from the research doc: xprompt `.md` files
with a `skill` frontmatter field ARE the skill source, and `sase init-skills` renders and deploys them.

## Context

Agent skills are currently maintained as 15 separate SKILL.md files across 3 providers in the chezmoi repo. Most are
near-identical copies differing only in provider name ("Claude" vs "Gemini" vs "Codex"). This creates maintenance
burden: adding or updating a skill requires editing 3+ files manually.

The xprompt infrastructure already provides discovery, loading, and Jinja2 rendering. Skills fit naturally as xprompts
with a `skill` deployment flag -- analogous to the existing `snippet` field.

## Current Skill Inventory

| Skill             | Providers           | Provider Differences                                                  |
| ----------------- | ------------------- | --------------------------------------------------------------------- |
| `sase_beads`      | claude,gemini,codex | None (identical across all 3)                                         |
| `sase_plan`       | claude,gemini,codex | Provider name in "replaces X's native plan mode" sentence             |
| `sase_git_commit` | claude,gemini,codex | Provider name mentions + Claude has extra untracked-files instruction |
| `sase_questions`  | claude,gemini,codex | Provider name + native tool name (AskUserQuestion vs ask_user)        |
| `sase_hg_commit`  | gemini              | Gemini-only, Mercurial VCS                                            |

## Design Decisions

### Jinja2 Context Variables

Each provider gets these template variables during rendering:

| Variable                   | Claude              | Gemini         | Codex        |
| -------------------------- | ------------------- | -------------- | ------------ |
| `provider_name`            | `"Claude"`          | `"Gemini"`     | `"Codex"`    |
| `provider_tool_name`       | `"Claude Code"`     | `"Gemini CLI"` | `"Codex"`    |
| `provider_native_ask_tool` | `"AskUserQuestion"` | `"ask_user"`   | `"ask_user"` |

For provider-specific blocks, use Jinja2 conditionals:

```jinja2
{% if provider_name == "Claude" %}Pay attention to **untracked files**...{% endif %}
```

### Deployment Path Logic

```
use_chezmoi=true  -> ~/.local/share/chezmoi/home/dot_<provider>/skills/<name>/SKILL.md
use_chezmoi=false -> ~/.<provider>/skills/<name>/SKILL.md
```

### Skill Field Semantics

```yaml
skill: true                   # Deploy to all providers (claude, gemini, codex)
skill: [claude, gemini]       # Deploy to specific providers only
```

### Interactive Confirmation (when `-f|--force` is NOT set)

When a target SKILL.md already exists, prompt with `y/n/d` (yes/no/diff). The diff option shows a unified diff between
the existing file and what would be written. This runs in a loop per-file until the user chooses y or n. stdin must be a
TTY for interactive mode; if not a TTY, default to skip (like `--dry-run` behavior) with a warning.

---

## Phase 1: XPrompt Model & Parsing (skill + description fields)

Add `skill` and `description` fields to the XPrompt data model and update all parsing/construction sites.

### Changes

1. **`src/sase/xprompt/models.py`** -- Add fields to `XPrompt` dataclass:
   - `description: str | None = None`
   - `skill: bool | list[str] | None = None`

2. **`src/sase/xprompt/loader.py`** -- Update all XPrompt construction sites:
   - `_load_xprompt_from_file()`: Parse `skill` and `description` from frontmatter
   - `_namespace_xprompt()`: Pass through `skill` and `description`
   - `_load_xprompts_from_plugins()`: Parse `skill` and `description` from frontmatter

3. **`src/sase/xprompt/loader_parsing.py`** -- Update `parse_xprompt_entries()`:
   - Parse `skill` and `description` from structured dict format

4. **`src/sase/xprompt/snippet_bridge.py`** -- No changes needed (doesn't construct XPrompts).

5. **Tests**: Add tests for parsing `skill` and `description` from both `.md` frontmatter and config dict formats.

### Verification

- `just check` passes
- Existing xprompts without `skill`/`description` fields continue to work unchanged
- New fields are correctly parsed from frontmatter

---

## Phase 2: Skill Source Files + `sase init-skills` Command

Create the skill xprompt source files and implement the CLI command.

### Skill Source Files

Create `src/sase/xprompts/skills/` directory with these files migrated from chezmoi:

- `sase_beads.md` -- `skill: true` (identical across providers, no Jinja2 needed)
- `sase_plan.md` -- `skill: true` (uses `{{ provider_name }}`)
- `sase_git_commit.md` -- `skill: true` (uses `{{ provider_name }}`, `{{ provider_tool_name }}`, conditionals for
  Claude-specific instructions)
- `sase_questions.md` -- `skill: true` (uses `{{ provider_name }}`, `{{ provider_native_ask_tool }}`)
- `sase_hg_commit.md` -- `skill: [gemini]` (Gemini-only)

Each file has the same format as a standard xprompt `.md` file:

```yaml
---
name: sase_plan
description: Create an implementation plan. Use instead of plan mode (which is disabled).
skill: true
---
Use this skill when you need to plan...
```

The skill source files should be placed in `src/sase/xprompts/skills/` (a subdirectory of the existing internal xprompts
directory). The loader already globs `src/sase/xprompts/*.md` but does NOT recurse into subdirectories, so skill files
in `skills/` won't pollute the xprompt namespace. The `init-skills` command will load them directly by path.

### CLI Command

**Parser** (`src/sase/main/parser_commands.py`):

```
sase init-skills [-f|--force] [-p|--provider PROVIDER] [-n|--dry-run]
```

- `-f, --force`: Overwrite existing files without confirmation
- `-p, --provider`: Only deploy for a specific provider (claude, gemini, codex)
- `-n, --dry-run`: Show what would be written without writing

**Handler** (`src/sase/main/init_skills_handler.py`):

Core logic:

1. Discover skill source files from `src/sase/xprompts/skills/*.md`
2. For each skill file, parse frontmatter to get `skill` field (determines target providers)
3. For each target provider: a. Build Jinja2 context (`provider_name`, `provider_tool_name`, `provider_native_ask_tool`)
   b. Render the skill content through Jinja2 c. Build the output SKILL.md (frontmatter with `name` + `description`,
   then rendered body) d. Strip the `skill` field from the output frontmatter (it's deployment metadata, not part of the
   skill spec) e. Determine target path based on `use_chezmoi` config f. If target exists and not `--force`: prompt
   y/n/d g. Write file (or print path in `--dry-run` mode)

**Entry point** (`src/sase/main/entry.py`): Add `init-skills` handler in alphabetical position.

**Parser registration** (`src/sase/main/parser.py`): Import and register `register_init_skills_parser`.

### Verification

- `just check` passes
- `sase init-skills --dry-run` shows correct output paths and rendered content
- `sase init-skills --force` writes files that match (or intentionally improve upon) the current chezmoi skill files
- Provider-specific Jinja2 rendering produces correct per-provider output

---

## Phase 3: Migration & Cleanup

Remove old manually-maintained skill files from chezmoi and deploy via `sase init-skills`.

### Steps

1. Run `sase init-skills --force` to generate all skill files into chezmoi source directories
2. Verify generated files match the originals (modulo intentional improvements like the consistent `-f` flag
   description)
3. Delete the old manually-maintained skill files from chezmoi (they're now generated)
   - Wait, actually the generated files go TO the same chezmoi paths, so step 1 already overwrites them
   - Just verify the content is correct
4. Run `chezmoi apply` to deploy
5. Update `AGENTS.md` to document `sase init-skills` usage
6. Commit all changes

### Verification

- All 13 skill files (4 skills x 3 providers + 1 gemini-only) exist at correct chezmoi paths
- Content matches expected output (provider-specific rendering is correct)
- `chezmoi apply` succeeds
- `just check` passes in both sase repo and chezmoi repo
