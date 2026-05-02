---
create_time: 2026-03-21 00:26:43
bead_id: sase-6
status: done
prompt: sdd/prompts/202603/directory_restructure.md
---

# Plan: Directory Structure Restructure

## Problem

The `src/sase/` root has 41 loose `.py` files that should be organized into packages. The previous agent's critique (in
`~/.sase/chats/sase-org-ace_run-260320_201451.md`) identified the right moves but a prior proposal over-engineered the
solution. This plan follows the critique's recommendations: move files into existing conceptual homes, avoid creating
packages for 1-3 files, and keep some files loose at root where that's fine.

## Current State

**41 root-level files** in `src/sase/`:

- 10 `axe_*` files (agent/workflow runners using filename prefix as namespace)
- 5 history files (chat, command, hook, prompt history + extras)
- 5 workflow files (amend, crs, mentor workflows + workflow_base + workflow_utils)
- 8 utils files (shared_utils, sase_utils, rich_utils, workspace_utils, etc.)
- 3 config files (config, mentor_config, metahook_config)
- 10 other files (agent_launcher, running_field, sdd, multi_prompt, etc.)

**18 existing packages** under `src/sase/`.

**Import intensity** (critical for ordering phases):

- `sase_utils.py`: 77 importers (highest risk to move)
- `running_field.py`: 52 importers
- `shared_utils.py`: 25 importers
- `rich_utils.py`: 22 importers
- `workflow_utils.py`: 14 importers
- `chat_history.py`: 15 importers
- `config.py`: 12 importers
- Everything else: <10 importers

## Approach

Each phase is designed to be **independently completable by a distinct claude instance**. Phases are ordered from
lowest-risk/simplest to highest-risk/most-complex. Each phase must:

1. Move/rename files
2. Update all imports across the codebase
3. Pass `just check` (fmt, lint, test)

---

## Phase 1: Move `axe_*` files into `axe/` package

**Rationale**: The 10 `axe_*` files are axe code that was never packaged. They form a tight cluster — most imports are
within the group (via `axe_runner_utils`), and the non-axe\_\* importers are few. The `axe/` package already exists.
This is the single highest-value, lowest-risk change.

**Files to move** (drop the `axe_` prefix): | From | To | |---|---| | `axe_run_agent_runner.py` |
`axe/run_agent_runner.py` | | `axe_run_agent_exec.py` | `axe/run_agent_exec.py` | | `axe_run_agent_phases.py` |
`axe/run_agent_phases.py` | | `axe_run_agent_helpers.py` | `axe/run_agent_helpers.py` | | `axe_run_workflow_runner.py` |
`axe/run_workflow_runner.py` | | `axe_runner_utils.py` | `axe/runner_utils.py` | | `axe_crs_runner.py` |
`axe/crs_runner.py` | | `axe_fix_hook_runner.py` | `axe/fix_hook_runner.py` | | `axe_mentor_runner.py` |
`axe/mentor_runner.py` | | `axe_summarize_hook_runner.py` | `axe/summarize_hook_runner.py` |

**Import updates required**:

- ~9 cross-imports within the axe\_\* group itself (e.g., `from sase.axe_runner_utils` → `from sase.axe.runner_utils`)
- External importers: mostly in `ace/`, `main/`, `xprompt/`, other root files
- The `axe_runner_utils` module is imported by all 9 other axe\_\* files — but since they all move together, these
  updates are straightforward

**Also check**: The `axe/` package's `__init__.py` — may need to export new symbols or update `__all__`.

**Entry points**: Check `pyproject.toml` for any console*scripts or entry_points referencing `axe*\*` modules.

---

## Phase 2: Create `history/` package

**Rationale**: Four files follow the identical `*_history.py` pattern, plus `chat_history_extras.py`. They share a clear
domain and benefit from co-location. Moderate number of importers (15 for chat_history, 6 for prompt_history, 4 for
hook_history, 2 each for command_history and chat_history_extras).

**Files to move**: | From | To | |---|---| | `chat_history.py` | `history/chat.py` | | `chat_history_extras.py` |
`history/chat_extras.py` | | `command_history.py` | `history/command.py` | | `hook_history.py` | `history/hook.py` | |
`prompt_history.py` | `history/prompt.py` |

**Create**: `history/__init__.py`

**Import updates**: ~29 total import sites across the codebase (mostly in `ace/tui/`, `main/query_handler/`, `axe/`
(after Phase 1), `llm_provider/`, `xprompt/`).

---

## Phase 3: Consolidate workflows under `workflows/`

**Rationale**: There are 3 loose workflow files, 2 workflow infrastructure files, and 3 existing `*_workflow/` packages.
Consolidating them under one `workflows/` package eliminates the inconsistency and groups related code.

**Files to move**: | From | To | |---|---| | `workflow_base.py` | `workflows/base.py` | | `workflow_utils.py` |
`workflows/utils.py` | | `amend_workflow.py` | `workflows/amend.py` | | `crs_workflow.py` | `workflows/crs.py` | |
`mentor_workflow.py` | `workflows/mentor.py` |

**Packages to move**: | From | To | |---|---| | `commit_workflow/` | `workflows/commit/` | | `accept_workflow/` |
`workflows/accept/` | | `rewind_workflow/` | `workflows/rewind/` | | `commit_utils/` | `workflows/commit_utils/` |

**Create**: `workflows/__init__.py`

**Import updates**: This is the most import-heavy phase:

- `workflow_utils`: 14 importers
- `workflow_base`: 5 importers
- `commit_workflow/*`: importers in `ace/`, `main/`, etc.
- `accept_workflow/*`: importers in `ace/`, `main/`
- `rewind_workflow/*`: importers in `ace/`, `main/`
- `commit_utils/*`: importers in `commit_workflow/`, `ace/`
- Plus internal cross-references within the moved files

**Note**: `renumber_utils.py` is imported by both `rewind_workflow/renumber.py` and `accept_workflow/renumber.py`. Move
it into `workflows/renumber_utils.py` since both consumers will be under `workflows/`.

---

## Phase 4: Absorb domain-specific utils into owning packages

**Rationale**: Several `*_utils` files have a clear owning domain. Moving them into their domain package reduces root
clutter without creating new packages.

**Files to move**: | From | To | Rationale | |---|---|---| | `workspace_utils.py` | `workspace_provider/utils.py` | 6 of
11 importers are in `workspace_provider/` | | `workspace_changespec.py` | `workspace_provider/changespec.py` |
Workspace-domain code, only 1 importer | | `submission_utils.py` | `workspace_provider/submission_utils.py` | Only
importer is `workspace_provider/plugins/bare_git_submit.py` | | `summarize_utils.py` | `ace/hooks/summarize_utils.py` |
2 of 3 importers are in `ace/hooks/` and `axe/` | | `plugin_discovery.py` | `main/plugin_discovery.py` | Used by
`config.py`, `xprompt/loader.py`, and `ace/tui/` — `main/` is where app bootstrap lives | | `change_actions.py` |
`ace/change_actions.py` | All 3 importers are in `ace/` |

**Note on remaining root-level utils**: `rich_utils.py` (22 importers across many packages), `shared_utils.py` (25
importers), and `sase_utils.py` (77 importers) are true cross-cutting utilities. They should **stay at root** as
`utils.py` or stay as-is. Merging `shared_utils.py` + `sase_utils.py` into a single `utils.py` could be considered but
is high-risk (77+ import sites) and low-value — the names are already clear enough. Best left alone unless the user
specifically wants this.

---

## Phase 5: Config grouping + final loose file cleanup

**Rationale**: After phases 1-4, the root will be down to ~15 files. This phase handles the remaining organizational
opportunities without over-structuring.

**Config grouping** — create `config/` package: | From | To | |---|---| | `config.py` | `config/config.py` (or
`config/core.py`) | | `mentor_config.py` | `config/mentor.py` | | `metahook_config.py` | `config/metahook.py` |

This is borderline (the critique said don't create packages for 1-3 files), but 3 config files with a clear shared
domain is reasonable. The `config/` package can re-export from `__init__.py` to minimize import churn.

**Files that stay at root** (and that's fine):

- `__init__.py`, `__main__.py` — required
- `sase_utils.py` — 77 importers, true cross-cutting utility
- `shared_utils.py` — 25 importers, true cross-cutting utility
- `rich_utils.py` — 22 importers, true cross-cutting utility
- `running_field.py` — 52 importers, concurrency primitive used everywhere
- `agent_launcher.py` — process spawning, used by 5 modules across different packages
- `agent_names.py` — used by 5 modules across different packages
- `multi_prompt.py` — used by 7 modules across different packages
- `multi_prompt_launcher.py` — used by 3 modules
- `sdd.py` — standalone, only 2 importers

**Final state** (~10-12 root files):

```
src/sase/
├── __init__.py
├── __main__.py
├── sase_utils.py          # cross-cutting utilities (77 importers)
├── shared_utils.py        # cross-cutting utilities (25 importers)
├── rich_utils.py          # cross-cutting utilities (22 importers)
├── running_field.py       # concurrency primitive (52 importers)
├── agent_launcher.py      # process spawning (5 importers)
├── agent_names.py         # agent naming (5 importers)
├── multi_prompt.py        # multi-prompt orchestration (7 importers)
├── multi_prompt_launcher.py  # multi-prompt launching (3 importers)
├── sdd.py                 # standalone (2 importers)
├── ace/                   # TUI + core app logic (unchanged)
├── axe/                   # agent execution (expanded with Phase 1 files)
├── bead/                  # bead workflow system
├── config/                # configuration (Phase 5)
├── gemini_wrapper/        # Gemini LLM wrapper
├── history/               # history tracking (Phase 2)
├── llm_provider/          # LLM abstraction layer
├── logs/                  # logging
├── main/                  # CLI entry points
├── notifications/         # notification system
├── scripts/               # utility scripts
├── status_state_machine/  # status tracking
├── vcs_provider/          # VCS abstraction layer
├── workflows/             # all workflows consolidated (Phase 3)
├── workspace_provider/    # workspace management (expanded with Phase 4 files)
├── xprompt/               # prompt workflow engine
└── xprompts/              # built-in prompt templates
```

That's 11 root files + 17 packages — down from 41 files + 18 packages. Much cleaner.

---

## Cross-cutting concerns for all phases

1. **Import rewriting**: Every phase needs a systematic find-and-replace of all `from sase.old_module import X`
   statements. Use `grep -r` to find all import sites before moving.

2. **Re-exports for compatibility**: For heavily-imported modules, consider adding re-exports in the old location (a
   one-line file that re-imports from the new location) as a transitional measure. This can be removed in a follow-up
   cleanup. However, since this is an internal codebase with no external consumers, direct import rewriting is cleaner.

3. **Tests**: The `tests/` directory mirrors `src/sase/` structure. Any file moves need corresponding test file moves
   and test import updates.

4. **Entry points**: Check `pyproject.toml` `[project.scripts]` and `[project.entry-points]` for any references to moved
   modules.

5. **xprompts/\*.yml**: These YAML files contain Python import paths in their step definitions. Check for references to
   moved modules.

6. **Validation**: Each phase must end with `just check` passing (fmt + lint + test).

## Phase dependency ordering

```
Phase 1 (axe_*)  ──→  no dependencies
Phase 2 (history) ──→  no dependencies
Phase 3 (workflows) ──→  no dependencies
Phase 4 (utils)  ──→  depends on Phase 1 (summarize_utils importers include axe/)
                       depends on Phase 3 (renumber_utils moves to workflows/)
Phase 5 (config)  ──→  no hard dependencies, but easiest to do last
```

Phases 1, 2, and 3 can be done in any order (or in parallel). Phase 4 should follow 1 and 3. Phase 5 is independent but
best done last as a cleanup pass.
