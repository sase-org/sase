---
create_time: 2026-03-29 09:50:33
status: done
prompt: sdd/prompts/202603/scope_local_mentor_profiles_to_project.md
---

# Plan: Scope Local Mentor Profiles to Their Project

## Problem

Mentor profiles from the local `./sase.yml` (e.g., "gotchas", "testing") are being applied to ALL changespecs across all
projects, including the 'bug' hg project. They should only apply to changespecs belonging to the project that the local
repo represents.

## Root Cause

The axe harness's `sase_chop_mentor_checks` script inherits CWD from `sase axe start` (typically the sase repo). The
mentor loading code (`_load_mentor_profiles()`) calls `load_merged_config()`, which loads `./sase.yml` because
`_include_local_config` defaults to `True` (only `sase ace` sets it to `False`). Local profiles are concatenated with
plugin/user profiles and applied indiscriminately to all changespecs.

Call chain: `sase axe start` -> orchestrator -> lumberjack subprocess -> `sase_chop_mentor_checks` chop script ->
`HookJobRunner.run_mentor_checks()` -> `check_mentors()` -> `add_matching_profiles_upfront()` ->
`get_all_mentor_profiles()` -> `_load_mentor_profiles()` -> `load_merged_config()` (loads local `./sase.yml`)

## Solution

Add a `projects` filter field to `MentorProfileConfig`. Auto-populate it for local config profiles using
`detect_project()`. In the matching logic, skip profiles whose `projects` list doesn't include the changespec's
`project_basename`.

## Key Design Decisions

- `projects: list[str] | None` on `MentorProfileConfig` -- explicitly settable in YAML too, not just auto-derived
- Only local-layer profiles get auto-tagging; plugin/user profiles remain unscoped unless explicitly set
- When `detect_project()` returns `None`, local profiles are NOT auto-scoped (backwards compatible fallback)
- `project_basename` on ChangeSpec (already exists) provides the changespec's project name
- `detect_project()` (from `sase.xprompt.loader`) uses `get_workspace_name()` which for git repos strips `_\d+$` suffix
  from the repo name, so `sase_100` -> `"sase"`, matching `project_basename` from `~/.sase/projects/sase/sase.gp`

## Implementation Plan

### Phase 1: Add `projects` field to MentorProfileConfig

**File: `src/sase/config/mentor.py`**

- Add `projects: list[str] | None = None` field to `MentorProfileConfig`
- In `_load_mentor_profiles()`:
  - After loading merged config, also load the local config path via `_get_local_config_path()` and extract its profile
    names into a `set[str]`
  - Auto-detect CWD project via `detect_project()` (from `sase.xprompt.loader`)
  - When creating `MentorProfileConfig` objects: if the profile name is in the local set AND it doesn't explicitly
    specify `projects` AND detected project is not None, auto-set `projects = [detected_project]`
  - Also parse explicit `projects` from YAML (user may set it manually in any config layer)

### Phase 2: Filter by projects in matching logic

**File: `src/sase/ace/scheduler/mentor_profile_matching.py`**

- In `_get_matching_profiles_for_entry()` (line 228 loop): before checking `profile_matches_any_commit()`, check
  `profile.projects`
  - If `profile.projects is not None` and `changespec.project_basename not in profile.projects`, skip
- In `trace_profile_matching()` (line 449 loop): add a `projects` criterion to the trace output so users can debug
  scoping

### Phase 3: Tests

**File: `tests/test_mentor_config_dataclass.py`** (update existing)

- Test that `projects` field defaults to `None`
- Test that `projects` is parsed from YAML when explicitly set

**File: `tests/test_mentor_profile_matching.py`** (update existing)

- Test that a profile with `projects=["sase"]` matches a changespec with `project_basename="sase"`
- Test that it does NOT match a changespec with `project_basename="bug"`
- Test that a profile with `projects=None` matches any changespec (backwards compatible)

**File: `tests/test_mentor_config_loading.py`** (update existing)

- Test auto-tagging: when local config defines profiles and CWD project is detectable, those profiles get `projects` set
- Test that non-local profiles don't get auto-tagged

### Phase 4: JSON schema update

**File: `config/sase.schema.json`**

- Add `projects` field to the mentor_profiles schema (list of strings, optional)
