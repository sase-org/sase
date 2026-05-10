---
create_time: 2026-04-12 20:00:43
status: wip
prompt: sdd/prompts/202604/dynamic_memory_2.md
---

# Plan: Implement Dynamic Memory (`memory/dynamic.md`)

## Goal

Before each agent session, scan the user's prompt against keyword-tagged xprompts and write `memory/dynamic.md`
containing only the content relevant to the task. The agent runtime (Claude Code, Gemini CLI) already reads
`@memory/dynamic.md` from AGENTS.md if the file exists on disk.

## Approach: `keywords` field + `memory` tag (Approach A from research)

Add a `keywords` field and `memory` tag to the xprompt system. Memory-tagged xprompts with matching keywords get their
content merged into `memory/dynamic.md` before the agent runtime starts.

**Important**: Existing tier 3 files (`memory/long/`) are NOT migrated. They remain as on-demand reference material. The
new memory xprompts are separate content that benefits from automatic inclusion.

## Changes

### Phase 1: Model and parsing changes

**1a. Add `memory` tag** -- `src/sase/xprompt/tags.py:25`

Add `memory = "memory"` to `XPromptTag` enum.

**1b. Add `keywords` field to `XPrompt`** -- `src/sase/xprompt/models.py:165`

Add `keywords: list[str] = field(default_factory=list)` after the `skill` field.

**1c. Parse `keywords` in file loader** -- `src/sase/xprompt/loader.py:114`

In `_load_xprompt_from_file()`, extract `front_matter.get("keywords")`, normalize to `list[str]` (accept YAML list or
comma-separated string), and pass to `XPrompt(keywords=...)`.

**1d. Parse `keywords` in config parser** -- `src/sase/xprompt/loader_parsing.py:380-401`

In `parse_xprompt_entries()`, for structured dict entries read `value.get("keywords")` and pass to
`XPrompt(keywords=...)`.

**1e. Propagate through Workflow**

- Add `keywords: list[str] = field(default_factory=list)` to `Workflow` dataclass
  (`src/sase/xprompt/workflow_models.py:141`).
- Pass `keywords=xprompt.keywords` in `xprompt_to_workflow()` (`src/sase/xprompt/models.py:213`).
- Update `_namespace_workflow()` and the plugin Workflow() reconstructions in `workflow_loader.py` to propagate
  `keywords`.

### Phase 2: Generation function

**2a. Create `src/sase/memory/dynamic.py`**

Implement `generate_dynamic_memory(prompt: str, workspace_dir: str, project: str | None) -> None`:

- Load all prompts via `get_all_prompts(project=project)`.
- Filter to those with `XPromptTag.memory` in tags and non-empty `keywords`.
- For each, check if any keyword appears in the prompt (case-insensitive substring match).
- If matches found: write concatenated content to `{workspace_dir}/memory/dynamic.md`.
- If no matches: ensure `memory/dynamic.md` does not exist.

### Phase 3: Wire into agent runner

**3a. Call from `run_agent_runner.py`**

Insert the call after `os.chdir(workspace_dir)` (line 217) and before `extract_directives_and_write_meta()` (line 220).
At this point:

- The fully expanded prompt is available (after `process_xprompt_references()`)
- `prepare_workspace()` has already cleaned the workspace (if applicable)
- We're in the workspace directory

The function handles both creation and cleanup (deletes file if no matches), so no separate deletion step is needed. For
home mode (no `prepare_workspace()`), any stale `memory/dynamic.md` from a prior run is overwritten or deleted by the
function.

### Phase 4: Git hygiene

**4a. Add to `.gitignore`**

Append to root `.gitignore`:

```
# Dynamic memory (generated before agent runs)
memory/dynamic.md
```

### Phase 5: Create memory xprompts

Create new xprompt `.md` files in `src/sase/xprompts/` with `tags: memory` and `keywords`. These are NEW content that
provides targeted context for specific task domains. Tier 3 files remain untouched.

**5a. `src/sase/xprompts/memory_external_repos.md`**

- Keywords: `chezmoi, sase-github, retired Mercurial plugin, sase-telegram, sase-nvim, dotfile, plugin repo`
- Content: Key facts about external repos -- chezmoi location, the `chezmoi apply` requirement after commits, plugin
  repo locations, `just check` requirement per modified plugin repo.

**5b. `src/sase/xprompts/memory_skill_pipeline.md`**

- Keywords: `skill, SKILL.md, init-skills, sase_git_commit, sase_hg_commit, skill source, skill template`
- Content: The skill generation pipeline, CLI/skill contract synchronization requirements, and the commit skill
  availability matrix.

**5c. `src/sase/xprompts/memory_xprompt_system.md`**

- Keywords: `xprompt, workflow, workflow_models, XPromptTag, front matter, loader, xprompts/`
- Content: Quick reference for xprompt system internals -- model fields, tag system, loading priority, file vs config
  format, .md vs .yml distinction. Useful when the agent is modifying xprompt infrastructure.

**5d. `src/sase/xprompts/memory_agent_pipeline.md`**

- Keywords: `run_agent_runner, launcher, agent runner, execution loop, agent_meta, prepare_workspace`
- Content: Overview of the agent launch pipeline -- key phases (prompt loading, xprompt expansion, workspace prep,
  directive extraction, execution loop), relevant files, and where to insert new behavior.

### Phase 6: Tests

- Test `generate_dynamic_memory()`: matching keywords writes file, no matches deletes file, multiple matches
  concatenated.
- Test `keywords` parsing from front matter (list and string formats).
- Test `memory` tag is recognized by `parse_tags()`.

### Phase 7: Validation

Run `just install && just check`.

## Key Design Decisions

- **Case-insensitive substring matching** -- simple, and over-inclusion is cheap (~30 lines per xprompt) compared to
  missing relevant context.
- **Tier 3 files stay** -- they serve a different purpose (deep reference material the agent reads on demand). The
  dynamic memory xprompts are lighter-weight context that benefits from automatic injection.
- **Content for memory xprompts is new**, not copied from tier 3 files. This avoids duplication while providing targeted
  context for different task domains.
