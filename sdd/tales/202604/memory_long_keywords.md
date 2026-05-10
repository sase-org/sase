---
create_time: 2026-04-12 23:04:20
status: done
prompt: sdd/prompts/202604/memory_long_keywords.md
---

# Plan: Auto-discover memory/long/ files with `keywords` frontmatter

## Problem

Tier 3 (long-term) memory xprompts are currently hardcoded in `src/sase/default_config.yml` as config entries that
reference `memory/long/` files via `$(cat ...)`. This couples the xprompt definition (name, keywords, tags) to the
config file rather than co-locating it with the content. Adding a new memory/long/ file requires editing two places.

## Goal

Move the `keywords` (and implicitly the `memory` tag) into the `memory/long/` markdown files themselves as YAML
frontmatter. The system auto-discovers these files from multiple directories and generates `memory/long/<name>` xprompts
with `$(cat <path>)` content for shell substitution.

## Design

### Frontmatter contract

A `memory/long/*.md` file with a `keywords` field in its YAML frontmatter is treated as a memory xprompt source:

```yaml
---
keywords: [chezmoi, plugin, sase-github, cross-repo]
---
# External Repos
...actual content...
```

The presence of `keywords` is the opt-in signal. Files without `keywords` frontmatter are ignored.

### Auto-generated xprompt properties

For a file at `<dir>/memory/long/external_repos.md` with keywords `[chezmoi, plugin]`:

| Property    | Value                                         |
| ----------- | --------------------------------------------- |
| name        | `memory/long/external_repos`                  |
| tags        | `frozenset({XPromptTag.memory})`              |
| keywords    | `["chezmoi", "plugin"]`                       |
| content     | `$(cat <path>/memory/long/external_repos.md)` |
| source_path | absolute path to the file                     |

The `$(cat ...)` content uses a relative path for CWD-based files (e.g. `memory/long/foo.md`) and an absolute path for
home-based files (e.g. `/home/user/.claude/memory/long/foo.md`).

### Scan directories (priority order, first wins on name collision)

1. `<cwd>/memory/long/` - project root
2. `<cwd>/.claude/memory/long/` - project-local agent config
3. `<cwd>/.gemini/memory/long/` - project-local agent config
4. `<cwd>/.codex/memory/long/` - project-local agent config
5. `~/.claude/memory/long/` - global agent config
6. `~/.gemini/memory/long/` - global agent config
7. `~/.codex/memory/long/` - global agent config

### Integration point

New function `_load_memory_long_xprompts()` in `src/sase/xprompt/loader.py`, called from `get_all_xprompts()` between
config-based xprompts (priority 6) and file-based xprompts (priority 1-4). This gives memory/long/ files higher priority
than config but lower than explicit xprompt files.

## Changes

### 1. Add frontmatter to `memory/long/` files

- `memory/long/external_repos.md` - add
  `keywords: [chezmoi, plugin, sase-github, retired Mercurial plugin, sase-telegram, sase-nvim, dotfile, cross-repo]`
- `memory/long/generated_skills.md` - add
  `keywords: [skill, SKILL.md, init-skills, sase_commit, sase_git_commit, sase_hg_commit, commit workflow, commit skill]`

### 2. Add `_load_memory_long_xprompts()` to `src/sase/xprompt/loader.py`

- Scan the 7 directories listed above
- Parse frontmatter from each `.md` file
- Skip files without `keywords` frontmatter
- Build XPrompt objects with `memory` tag, keywords, and `$(cat ...)` content
- Return dict keyed by `memory/long/<stem>`

### 3. Wire into `get_all_xprompts()`

Call `_load_memory_long_xprompts()` and update `all_xprompts` at the right priority level.

### 4. Remove hardcoded entries from `src/sase/default_config.yml`

Delete the `memory/external_repos` and `memory/generated_skills` entries (lines ~314-321).

### 5. Update `tests/test_dynamic_memory.py`

- Xprompt names change: `memory/external_repos` -> `memory/long/external_repos`, `memory/generated_skills` ->
  `memory/long/generated_skills`
- Update `_make_memory_workflows()` helper and all assertions referencing old names
- Add test for `_load_memory_long_xprompts()` verifying frontmatter-based discovery
- Add test verifying files without `keywords` frontmatter are skipped

### 6. Run `just check`
