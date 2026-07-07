---
create_time: 2026-07-07 11:57:05
status: done
prompt: sdd/prompts/202607/gh_first_use_project_display.md
---
# Plan: First-use `#gh:org/repo` launches should display the repo name as the project, not `org/repo`

## Problem

When the `#gh` VCS xprompt workflow is used with a brand-new project, the user must spell out the GitHub org and repo
(e.g. `#gh:bbugyi200/actstat`). After that first use, `#gh:actstat` suffices. However, the _first_ agent launched this
way looks special: the Agents-tab row title and the detail panel's `ChangeSpec:` field show `bbugyi200/actstat`, while
every subsequent agent for the same project shows just `actstat` (see the real example in the screenshot at
`.sase/home/tmp/screenshots/20260707_114227.png`).

## Root cause

All launch paths funnel VCS-ref resolution through `resolve_ref_from_prompt()`
(`src/sase/ace/tui/actions/agent_workflow/_ref_resolution.py`). That function returns the **raw matched ref** as the
launch identity (the 5th tuple element), and callers use it as the agent's display identity:

- `_launch_body_single.py` sets `ctx.display_name = ref_value` and `ctx.history_sort_key = ref_value`;
  `ctx.display_name` becomes the spawned agent's `cl_name`.
- `multi_prompt_vcs.resolve_segment_vcs_context()` sets `cl_name=resolved_ref` per segment.
- `launch_cwd_agents.py` builds `vcs_ref = (wf_name, ref_value)` the same way.

Display layers then render `humanize_cl_name(cl_name)` (Agents-tab row via `Agent.display_name`, detail panel via
`_agent_display_header.py`) and `project_display_name_for(display_name)` (launch toasts). Those helpers map **canonical
project directory keys** (e.g. `gh_bbugyi200__actstat`) to display names (`actstat`).

- **Subsequent launches** (`#gh:actstat`): `resolve_ref_from_prompt()` first calls
  `canonicalize_project_aliases_in_prompt()`, so the matched ref is already the canonical key `gh_bbugyi200__actstat`,
  which humanizes to `actstat` everywhere. ✔
- **First launch** (`#gh:bbugyi200/actstat`): no alias exists yet at match time, so the raw repo-path locator
  `bbugyi200/actstat` becomes `cl_name`. It is not a key in the display-name map, so it renders verbatim. ✘

Note that by the time `resolve_ref_from_prompt()` returns, the gh plugin's `_resolve_repo_path_ref()` has _already_
cloned the repo, allocated the canonical project name (`gh_<org>__<repo>`), and locked the `actstat` display name —
`ResolvedRef.project_name` holds the canonical key. The callers just never use it for the ref/identity.

Secondary symptoms of the same bug:

- `save_replayable_vcs_selection()` (`_launch_history.py`) compares `ref == ctx.project_name`; with the raw repo path
  they differ, so the Ctrl+Space replay selection is wrongly saved as a `[PR]`/ChangeSpec item named `bbugyi200/actstat`
  instead of a `[P]` project item.
- The VCS xprompt MRU records the prefix `#gh:bbugyi200/actstat` instead of the canonical prefix recorded by all later
  launches.
- The bare-git plugin has the same latent bug: a first-use `#git:<path-with-slashes>` (Mode 4 bare-repo path) shows the
  whole path as the agent's identity instead of the derived project name.

The `#cd` workflow also matches refs containing `/`, but there the full directory path _is_ the intended display
identity — any fix must not change `#cd` behavior.

## Design

Let the **plugin that resolved the ref** declare the launch-equivalent identity, instead of hard-coding a "contains `/`"
heuristic in generic code:

1. Add an optional field to `ResolvedRef` (`src/sase/workspace_provider/_hookspec.py`):

   ```python
   canonical_ref: str | None = None
   ```

   Semantics: "when set, use this instead of the raw matched ref as the launch identity (display name / history key /
   replay selection / MRU prefix)". Plugins set it when the raw ref is a provider-specific _locator_ (repo path,
   bare-repo path) rather than a stable project/ChangeSpec name.

2. In `resolve_ref_from_prompt()`, return `resolved.canonical_ref or ref` as the final tuple element. This single change
   propagates to all launch paths (TUI single/fan-out/multi-prompt segments, CLI `launch_cwd_agents`), fixing the row
   title, `ChangeSpec:` field, launch toast, replay selection (now correctly saved as a `[P]` project item), and MRU
   prefix in one place.

3. Plugins:
   - **sase-github** (linked repo): in `workspace_plugin.py`, set `canonical_ref` on the `ResolvedRef`s built by
     `resolve_gh_ref()`:
     - Mode 1 repo path (`_resolve_repo_path_ref`): `canonical_ref = project_name` (the canonical `gh_<org>__<repo>` key
       — exactly what subsequent alias-canonicalized launches produce).
     - Alias-record path (`_resolved_ref_for_record`): `canonical_ref = record.project_name` (harmless normalization;
       covers callers that resolve an alias without prompt canonicalization, e.g. the workflow's `gh_setup` step).
     - Mode 2 project shorthand and Mode 3 ChangeSpec: leave `None` — the ref (project name / ChangeSpec name) already
       _is_ the identity.
     - `ws_resolve_ref()` re-wraps the `ResolvedRef`; pass `canonical_ref` through.
     - Bump the `sase` dependency floor in `pyproject.toml` to the release that adds the field (constructing
       `ResolvedRef(canonical_ref=...)` against an older sase would raise `TypeError`).
   - **bare-git plugin** (`src/sase/workspace_provider/plugins/bare_git_workspace.py`): in `ws_resolve_ref()`, set
     `canonical_ref = resolved.project_name` when `"/" in ref` (Mode 4 bare-repo path). Modes 1–3 leave it `None`.
   - **cd plugin**: unchanged — `#cd` keeps showing the full path.

4. Consistency touch-up in `record_launched_vcs_xprompt_usage()` (`_launch_history.py`): when the helper re-resolves the
   prompt (the non-home-mode path that only pattern-matched a raw ref), build the MRU prefix from the resolved ref
   (tuple element 5) rather than the raw one, so first-use MRU entries match what all later launches record.

Out of scope (intentionally unchanged):

- The `Xprompts:` detail section keeps showing the user's literal `#gh bbugyi200/actstat` args — that is the prompt the
  user typed, not the project identity.
- The gh workflow's internal `workflow_name = "gh-<ref>"` label and `gh_setup.py` outputs — the RUNNING-claim label is
  ephemeral and not the display identity the user complained about.
- No Rust-core changes: ref resolution and the workspace-provider pluggy layer live entirely in Python today, and this
  change only re-labels the launch identity within that existing layer.

## Implementation steps

### sase repo

1. `src/sase/workspace_provider/_hookspec.py`: add `canonical_ref: str | None = None` to `ResolvedRef` with a docstring
   line explaining the locator-vs-identity semantics.
2. `src/sase/ace/tui/actions/agent_workflow/_ref_resolution.py`: in `resolve_ref_from_prompt()`, return
   `resolved.canonical_ref or ref` as the ref element.
3. `src/sase/workspace_provider/plugins/bare_git_workspace.py`: set `canonical_ref` for bare-path refs as described
   above.
4. `src/sase/ace/tui/actions/agent_workflow/_launch_history.py`: use the resolved ref for the MRU prefix when
   re-resolution succeeds (step 4 of Design).

### sase-github linked repo

5. `src/sase_github/workspace_plugin.py`: set `canonical_ref` in `_resolve_repo_path_ref()` and
   `_resolved_ref_for_record()`; pass it through in `ws_resolve_ref()`.
6. `pyproject.toml`: raise the `sase>=` dependency floor to the first sase version containing the new `ResolvedRef`
   field.

## Tests

### sase repo

- Extend `tests/ace/tui/agent_launch_vcs/test_resolution.py` (reusing the existing fake-plugin / metadata-monkeypatch
  helpers in `tests/ace/tui/_agent_launch_helpers.py`):
  - A launch-body test with a workspace plugin whose `ws_resolve_ref` returns `canonical_ref="proj_key"` for an
    `org/repo`-style ref: assert the launched agent's `cl_name`, `history_sort_key`, and `vcs_ref` all use `proj_key`,
    and that the saved replay selection is a `[P]` project item (not a `[PR]` item named `org/repo`).
  - A regression test that `#cd:<path>` behavior is unchanged (existing test already asserts
    `vcs_ref == ("cd", <path>)`; keep it green).
- Bare-git plugin unit test: `ws_resolve_ref` on a path ref (contains `/`) returns `canonical_ref == project_name`;
  project-shorthand and ChangeSpec refs return `canonical_ref is None`.
- MRU helper test: `record_launched_vcs_xprompt_usage` with a prompt whose ref resolves to a `canonical_ref` records the
  canonical prefix.

### sase-github linked repo

- Extend `tests/test_workspace_plugin.py`:
  - `resolve_gh_ref("alice/myrepo")` → `canonical_ref == "gh_alice__myrepo"` (and equals `project_name`).
  - Alias resolution (`resolve_gh_ref("<display-name>")` after a repo-path first use) →
    `canonical_ref == <canonical project key>`.
  - Project shorthand and ChangeSpec-name resolution → `canonical_ref is None`.
  - `ws_resolve_ref` passes `canonical_ref` through.

## Verification

- sase repo: `just install` then `just check`.
- sase-github repo: run its lint/test suite via its own Justfile.
- Manual sanity check (optional, requires network): launch an agent with a fresh `#gh:<org>/<repo>` ref and confirm the
  Agents-tab row and `ChangeSpec:` detail field show the repo display name (e.g. `actstat`), matching subsequent
  `#gh:<repo>` launches.

## Acceptance criteria

- The first agent launched with `#gh:<org>/<repo>` for a new project displays the same project identity (`<repo>`, or
  the deduplicated display name the gh plugin allocates) as later agents launched with `#gh:<repo>` — in the Agents-tab
  row title, the detail panel's `ChangeSpec:` field, and the launch toast.
- The Ctrl+Space replay selection after such a first launch is a `[P]` project selection.
- `#cd` launches still display the full target path.
- A first-use `#git:<path>` bare-repo launch displays the derived project name instead of the path.
