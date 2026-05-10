---
create_time: 2026-03-23 22:25:50
status: done
prompt: sdd/prompts/202603/vcs_aware_tag_disambiguation.md
---

# Plan: VCS-Aware Tag Disambiguation for `diff_file`

## Problem

Currently, the `diff_file` xprompt tag can only have one provider at a given priority level. The builtin `#pr_diff` (in
`src/sase/xprompts/pr_diff.md`, lowest priority) works for GitHub, while `#cl_diff` (in
`retired Mercurial plugin/default_config.yml`, plugin-config priority) works for Mercurial.

If we move `#pr_diff` to sase-github's `default_config.yml` (so it lives alongside its VCS plugin), both plugins would
provide `diff_file` at plugin-config priority. When both plugins are installed, `get_by_tag(XPromptTag.diff_file)` would
return whichever loaded last — wrong behavior.

## Goal

Allow both sase-github and retired Mercurial plugin to define a `diff_file`-tagged xprompt, and resolve the correct one based on
which VCS workflow is active (e.g., `#gh` → `#pr_diff`, `#hg` → `#cl_diff`).

## Key Insight

Every plugin xprompt has a `source_path` that encodes its originating module:

- Plugin workflows: `"plugin:sase_github/gh.yml"`
- Plugin config xprompts: `"plugin_config:retired_mercurial_plugin"`

The VCS workflow (e.g., `#gh`) and its companion `diff_file` xprompt (e.g., `#pr_diff`) come from the same plugin
module. We can disambiguate by preferring the tag match from the same plugin as the active VCS workflow.

## Phases

### Phase 1: Add `#pr_diff` to sase-github plugin config

**Repo: `../sase-github`**

1. **Create `src/sase_github/default_config.yml`** with:

   ```yaml
   xprompts:
     pr_diff:
       tags: diff_file
       content: |
         #x(pr_changes.diff, git diff origin/master)
   ```

2. **Add `sase_config` entry point** in `pyproject.toml`:

   ```toml
   [project.entry-points."sase_config"]
   sase_github = "sase_github"
   ```

   (Mirrors how retired Mercurial plugin registers its `default_config.yml`.)

3. **Remove `src/sase/xprompts/pr_diff.md`** from the main sase repo since sase-github now owns this xprompt. (The main
   repo should not provide a GitHub-specific diff xprompt.)

### Phase 2: VCS-aware `get_by_tag` in sase core

**Repo: sase (main)**

**File: `src/sase/xprompt/tags.py`**

4. **Add `_extract_plugin_module()` helper**:

   ```python
   def _extract_plugin_module(source_path: str | None) -> str | None:
       """Extract the plugin module name from an xprompt/workflow source_path."""
       if not source_path:
           return None
       if source_path.startswith("plugin:"):
           # "plugin:sase_github/gh.yml" → "sase_github"
           return source_path.removeprefix("plugin:").split("/")[0]
       if source_path.startswith("plugin_config:"):
           # "plugin_config:retired_mercurial_plugin" → "retired_mercurial_plugin"
           return source_path.removeprefix("plugin_config:")
       return None
   ```

5. **Add `vcs_hint` parameter to `get_by_tag()`**:
   - New optional parameter `vcs_hint: str | None = None` — the name of the active VCS workflow (e.g., `"gh"` or
     `"hg"`).
   - When there are multiple matches and `vcs_hint` is provided:
     1. Look up the VCS workflow by name from `get_all_prompts()`.
     2. Extract its plugin module via `_extract_plugin_module()`.
     3. Among the matches, prefer the one from the same plugin module.
     4. If no module match, fall back to last-wins (current behavior).
   - When `vcs_hint` is None or there's only one match, behavior is unchanged.

### Phase 3: Update callers to pass `vcs_hint`

6. **`src/sase/workflows/mentor.py:86`** — already has `vcs_type` in scope:

   ```python
   diff_wf = get_by_tag(XPromptTag.diff_file, project=project, vcs_hint=vcs_type)
   ```

7. **Check other callers of `get_by_tag`** — `fix_hook_runner.py:141`, `crs.py:81`, `_mentor_review.py:177,179` — these
   don't look up `diff_file`, so no change needed. But if any future caller needs VCS-aware resolution, the parameter is
   available.

### Phase 4: Tests

8. **Unit test in sase core** (`tests/xprompt/test_tags.py` or similar):
   - Test `_extract_plugin_module()` with various source_path formats.
   - Test `get_by_tag()` with `vcs_hint` when two xprompts share the same tag but come from different plugin modules.
     Verify the correct one is returned based on which VCS workflow's module matches.
   - Test `get_by_tag()` without `vcs_hint` still returns last-wins behavior.

9. **Reinstall sase-github** (`just install` in sase-github) to pick up the new entry point and default_config.yml.
   Verify `#pr_diff` resolves correctly.

## Files Changed

| Repo        | File                                 | Change                                                                 |
| ----------- | ------------------------------------ | ---------------------------------------------------------------------- |
| sase-github | `src/sase_github/default_config.yml` | **Create** — define `pr_diff` with `diff_file` tag                     |
| sase-github | `pyproject.toml`                     | Add `sase_config` entry point                                          |
| sase (main) | `src/sase/xprompts/pr_diff.md`       | **Delete** — no longer needed                                          |
| sase (main) | `src/sase/xprompt/tags.py`           | Add `_extract_plugin_module()`, add `vcs_hint` param to `get_by_tag()` |
| sase (main) | `src/sase/workflows/mentor.py`       | Pass `vcs_hint=vcs_type` to `get_by_tag()`                             |
| sase (main) | `tests/`                             | Add tests for VCS-aware tag disambiguation                             |

## Risks / Edge Cases

- **Neither plugin installed**: `get_by_tag(XPromptTag.diff_file)` returns `None` — callers already handle this (e.g.,
  `diff_ref = diff_wf.name if diff_wf else ""`).
- **Only one plugin installed**: Single match, no disambiguation needed.
- **User override in `sase.yml`**: User-config xprompts have higher priority than plugin-config, so a user-defined
  `diff_file` xprompt would still win regardless of VCS hint. This is correct.
- **`vcs_hint` doesn't match any loaded workflow**: Falls back to last-wins behavior.
