# External Script Dependencies

This document catalogs external executables referenced in the sase codebase that are **not included in this repo** and
are **not well-known standard tools**. Contributors should be aware that these scripts are expected to exist on `$PATH`
(or at the listed absolute path) for certain features to work.

## Google-internal / Mercurial wrappers

Source: `src/sase/vcs_provider/_hg.py`

| Script            | Usage                       | Line(s)  |
| ----------------- | --------------------------- | -------- |
| `sase_hg_update`  | Checkout/update to revision | 73       |
| `sase_hg_amend`   | Amend current CL            | 136      |
| `sase_hg_rename`  | Rename branch               | 144      |
| `sase_hg_rebase`  | Rebase branch               | 150      |
| `sase_hg_archive` | Archive revision            | 154      |
| `sase_hg_prune`   | Prune revision              | 158      |
| `sase_hg_clean`   | Stash and clean workspace   | 164      |
| `sase_hg_sync`    | Sync workspace              | 176      |
| `sase_hg_reword`  | Reword CL description       | 207, 213 |

## Google-internal / CL utilities

| Script                     | Usage                                    | Source location                                                                 |
| -------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------- |
| `branch_name`              | Get current branch name                  | `_hg.py:230`                                                                    |
| `branch_number`            | Get CL number                            | `_hg.py:237`                                                                    |
| `workspace_name`           | Get workspace name                       | `_hg.py:246`, `shared_utils.py:148`, `main/utils.py:18`, `prompt_history.py:45` |
| `branch_local_changes`     | Check for local changes                  | `_hg.py:253`                                                                    |
| `sase_hg_branch_bug`       | Get bug number for branch                | `_hg.py:259`                                                                    |
| `branch_or_workspace_name` | Get branch or workspace name             | `chat_history.py:24`, `prompt_history.py:33`                                    |
| `cl_desc`                  | Get CL description                       | `_hg.py:219`                                                                    |
| `is_cl_submitted`          | Check if CL is submitted                 | `ace/scheduler/checks_runner.py:158`                                            |
| `critique_comments`        | Get reviewer comments                    | `crs_workflow.py:58`, `ace/scheduler/checks_runner.py:222`                      |
| `p4` (findreviewers)       | Find code reviewers                      | `_hg.py:279`                                                                    |
| `changed_test_targets`     | Get Blaze test targets for changed files | `workflow_utils.py:67`                                                          |

## sase ecosystem scripts (not in this repo)

| Script                  | Usage                                                      | Source location                   |
| ----------------------- | ---------------------------------------------------------- | --------------------------------- |
| `sase_hg_get_workspace` | Get/create workspace directory                             | `running_field.py:546`            |
| `sase_hg_rewind`        | Rewind diffs                                               | `_hg.py:285`                      |
| `sase_metahook_*`       | Dynamic metahook scripts (pattern: `sase_metahook_{name}`) | `axe_summarize_hook_runner.py:69` |

## Notification / UI utilities

| Script              | Usage                              | Source location               |
| ------------------- | ---------------------------------- | ----------------------------- |
| `tm`                | Open tmux session (custom wrapper) | `ace/tui/actions/base.py:463` |
| `bam`               | Audio/visual notification          | `shared_utils.py:203`         |
| `terminal-notifier` | macOS desktop notifications        | `tools/sase_stop_hook:52`     |

## Shell library (referenced but sourced from `~/lib/`)

| Path                                       | Usage                                              | Source location                                |
| ------------------------------------------ | -------------------------------------------------- | ---------------------------------------------- |
| `~/lib/bugyi.sh`                           | Shell utility library (sourced by `tools/pylimit`) | `tools/pylimit-260217:4`                       |
| `~/lib/sase/xprompts/workflow.schema.json` | Workflow schema file                               | `ace/tui/actions/agent_workflow/_editor.py:72` |

## LLM CLI tools

| Script                                         | Usage                                              | Source location             |
| ---------------------------------------------- | -------------------------------------------------- | --------------------------- |
| `/google/bin/releases/gemini-cli/tools/gemini` | Google Gemini CLI (hardcoded Google-internal path) | `llm_provider/gemini.py:42` |

---

**Excluded from this list** (well-known tools that happen to be optional): `git`, `hg`, `claude`, `nvim`/`vim`, `fzf`,
`bat`, `less`, `cat`, `tmux`, `pbcopy`, `xclip`, `prettier`, `perl`, `logger`, `python3`, `twine`, `npm`, `just`, `wc`,
`find`, `grep`, `getopt`, `mktemp`, `date`.

**Included in this repo** (also excluded from the list above): `tools/pyvision-260217`, `tools/pylimit-260217`,
`tools/sase_stop_hook`, `lib/bugyi_260217.sh`.
