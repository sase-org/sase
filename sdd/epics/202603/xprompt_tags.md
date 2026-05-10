---
bead_id: sase-4
status: done
prompt: sdd/prompts/202603/xprompt_tags.md
---

# Plan: XPrompt Tags

Add a `tags` field to xprompts/workflows that marks them with predefined semantic roles (`vcs`, `crs`, `fix_hook`,
`rollover`). This replaces ad-hoc mechanisms like the `wraps_all` boolean and hardcoded xprompt name references.

## Phase 1: Core Tag Infrastructure

Define the tag system's data model, parsing, and lookup API. No behavioral changes yet.

### Changes

**New file: `src/sase/xprompt/tags.py`**

- Define `XPromptTag` enum with values: `vcs`, `crs`, `fix_hook`, `rollover`
- Add `parse_tags(raw: str | list | None) -> set[XPromptTag]` — accepts comma-separated string (from YAML) or list,
  validates against enum, raises on unknown tags
- Add `get_by_tag(tag: XPromptTag, project: str | None = None) -> Workflow | None` — finds the highest-priority
  xprompt/workflow with the given tag, using existing loader precedence (local > user > plugin > builtin). For singleton
  tags (`crs`, `fix_hook`), returns the first match.

**`src/sase/xprompt/models.py`** — `XPrompt` dataclass

- Add field: `tags: set[XPromptTag] = field(default_factory=set)`
- Add method: `has_tag(tag: XPromptTag) -> bool`
- Update `_namespace_xprompt()` in `loader.py` to copy `tags`

**`src/sase/xprompt/workflow_models.py`** — `Workflow` dataclass

- Add field: `tags: set[XPromptTag] = field(default_factory=set)`
- Add method: `has_tag(tag: XPromptTag) -> bool`
- Update `_namespace_workflow()` in `workflow_loader.py` to copy `tags`

**`src/sase/xprompt/loader_parsing.py`**

- Update `parse_yaml_front_matter` handling: extract `tags` from front matter dict
- Update `parse_xprompt_entries()`: parse `tags` from structured xprompt dicts
- In `_load_xprompt_from_file()` (loader.py): parse `tags` from front matter, pass to `XPrompt()`
- In `_load_xprompts_from_plugins()` (loader.py): same

**`src/sase/xprompt/workflow_loader.py`**

- In `_load_workflow_from_file()`: parse `tags` from YAML data, pass to `Workflow()`
- In `_load_workflows_from_plugins()`: copy `tags` when constructing Workflow

**`src/sase/xprompt/models.py`** — `xprompt_to_workflow()`

- Copy `tags` from XPrompt to the generated Workflow

**Tests: `tests/test_xprompt_tags.py`**

- Tag parsing: valid tags, invalid tags (error), comma-separated string, list format
- Tags on XPrompt: from .md frontmatter, from config entries
- Tags on Workflow: from .yml files
- `has_tag()` method
- `get_by_tag()` with precedence (mock multiple sources)
- Tags preserved through `xprompt_to_workflow()` and namespace operations

---

## Phase 2: VCS Tag — Replace `wraps_all`

Replace the `wraps_all: true` boolean with `tags: vcs`. Maintain backward compatibility during loading.

### Changes

**Xprompt files — add `tags: vcs`:**

- `src/sase/xprompts/git.yml` — add `tags: vcs`
- `../sase-github/src/sase_github/xprompts/gh.yml` — add `tags: vcs`
- `../retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/hg.yml` — add `tags: vcs`

**`src/sase/xprompt/workflow_loader.py`** — backward compat

- In `_load_workflow_from_file()`: if `wraps_all: true` is set, add `XPromptTag.vcs` to tags (so old YAML still works)
- Conversely, if `tags` contains `vcs`, set `wraps_all = True` on the Workflow (so downstream code works during
  migration)

**`src/sase/xprompt/workflow_executor_steps_embedded.py`** — replace `wraps_all` checks

- Phase 2 validation (line 447): check `workflow.has_tag(XPromptTag.vcs)` instead of `workflow.wraps_all`
- Phase 3 execution order (line 458): same replacement
- Phase 5 post-step list (line 538): same replacement

**`src/sase/xprompt/workflow_models.py`**

- Deprecate `wraps_all` field — keep it but add a comment that it's deprecated in favor of `tags: vcs`
- Do NOT remove it yet (backward compat for any user YAML files that use it)

**Tests**

- Verify `wraps_all: true` in YAML auto-adds `vcs` tag
- Verify `tags: vcs` in YAML sets `wraps_all = True` for backward compat
- Verify embedded workflow execution order uses tag-based detection
- Verify validation rejects multiple `vcs`-tagged workflows in one prompt

---

## Phase 3: CRS and Fix Hook Tags

Replace hardcoded `#crs` and `#fix_hook` xprompt name references with tag-based lookup.

### Changes

**Xprompt files — add tags:**

- `../retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/crs.md` — add `tags: crs` to frontmatter
- `src/sase/xprompts/fix_hook.md` — add `tags: fix_hook` to frontmatter

**`src/sase/crs_workflow.py`** — replace hardcoded `#crs`

- In `_build_crs_prompt()`: use `get_by_tag(XPromptTag.crs)` to find the xprompt name, then construct the `#<name>(...)`
  reference dynamically
- Fall back to `#crs` if no tagged xprompt found (defensive)

**Fix hook references** — search for hardcoded `#fix_hook` usage

- In any code that constructs `#fix_hook(...)` prompts: use `get_by_tag(XPromptTag.fix_hook)` to find the name
- Same fallback pattern

**Override precedence** — already handled by `get_by_tag()` using loader precedence:

- Local xprompts (`.xprompts/`, `xprompts/`) win over user (`~/xprompts/`) win over plugin win over builtin
- User creates their own `my_crs.md` with `tags: crs` in `~/xprompts/` → overrides the builtin

**Tests**

- Tag-based lookup returns correct xprompt for `crs` and `fix_hook`
- User override: local xprompt with `tags: crs` takes precedence over plugin's `crs.md`
- `_build_crs_prompt()` uses the tag-resolved name
- Defensive fallback when no tagged xprompt found

---

## Phase 4: Rollover Tag

Make xprompt rollover to `.code`/`.q` agents tag-based instead of rolling over ALL xprompts.

### Changes

**Determine which xprompts need `rollover` tag:**

- Xprompts that should roll over to coder/question agents are those whose embedded workflow refs (like `#propose`,
  `#commit`) need to run after the follow-up agent. Currently ALL embedded refs are rolled over via
  `_get_embedded_workflow_refs()`.
- The `rollover` tag marks xprompts whose _non-VCS_ embedded refs should be preserved in follow-up agents.
- Xprompts that are planner-only (meant to orchestrate multi-step plans but not carry forward to coders) should NOT have
  this tag.

**Xprompt files — add `tags: rollover`:**

- Identify which xprompts currently get rolled over and should continue to (e.g., `propose.yml`, `commit.yml`, `crs.md`)
- Add `tags: rollover` to each

**`src/sase/axe_run_agent_exec.py`** — filter by tag

- In `_get_embedded_workflow_refs()`: load workflow metadata with tags, only include refs whose workflow has
  `has_tag(XPromptTag.rollover)`
- This requires storing tags in `embedded_workflows.json` metadata (update the write in
  `workflow_executor_steps_embedded.py`)

**`src/sase/xprompt/workflow_executor_steps_embedded.py`**

- When writing `embedded_workflows.json`, include `tags` for each workflow

**Tests**

- Only `rollover`-tagged xprompts appear in follow-up agent prompts
- Non-tagged xprompts are excluded from rollover
- `embedded_workflows.json` includes tag information
