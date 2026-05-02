---
plan: sdd/epics/202603/xprompt_add_edit_ux.md
---
#gh:sase Can you help me make the experience of adding/editing xprompts from the `sase ace` TUI WAY better?

- We will improve the `<c-o>` xprompt widget keymap (see the `sase ace` snapshot below) so it asks the user to select
  from a list of known xprompt locations (this should include EVERY `sase.yml` file (or variants with underscores),
  `default_config.yml` file, `xprompts/*.md` file, `xprompts/*.yml` workflow files, etc...
- If the user selects an xprompts directory, we should prompt for a file basename (ex: foobar.md or foobar.yml). The
  user MUST give a .md or .yml extension.
- If the user gives a markdown file path, we should open that markdown file, which should contain no contents, in their
  editor.
- If the user gives a YAML file path, we should open an xprompt YAML workflow template in their editor (we do this
  elsewhere, so look for that code).
- We should start allowing the user to edit EVERY xprompt that sase knows about, even if they don't necessarily own it.
  We will even prompt them if they want to commit and push (the worst-case is that the push fails).
- After the user closes their editor when adding/editing an xprompt, if the file that was created / modified is under
  git version-control, we should prompt the user if they would like to commit their change. If the user confirms the
  commit, we should commit and push the changes using a `chore: ` conventional commit prefix and a smart / useful commit
  message.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.

### Current Xprompt Widget (`sase ace` snapshot)

```
 ⭘                                                                                                     sase ace
  CLs  │  Agents  │  AXE (6)                                                                                                                                                                                ■ IDLE  ✉ 0
 Agents: 0/0   (auto-refresh in 7s)
┌──────────────────────────────────────┐┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                      ││                                                                                                                                                                              │
│        █▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀█        │
│        █                                                                                                                                                                                                    █        │
│        █  XPrompt Browser [39 xprompts]                                                                                                                                                                     █        │
│        █                                                                                                                                                                                                    █        │
│        █  ▊▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▎  █        │
│        █  ▊  Type to filter...                                                                                                                                                                           ▎  █        │
│        █  ▊▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▎  █        │
│        █                                                                                                                                                                                                    █        │
│        █  ┌──────────────────────────────────────┐ ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐  █        │
│        █  │ ── CWD .xprompts/ ──                 │ │ # Workflow: sase/pylimit_split                                                                                                                      │  █        │
│        █  │   ⚙ #sase/pylimit_split              │ │                                                                                                                                                     │  █        │
│        █  │      limits=1000 850 700             │ │ ## Inputs                                                                                                                                           │  █        │
│        █  │ ── Home ~/xprompts/ ──               │ │ - **limits**: text (default: 1000 850 700)                                                                                                          │  █        │
│        █  │   ⚙ #refresh_cl_desc                 │ │                                                                                                                                                     │  █        │
│        █  │      cl_name?                        │ │ ## Steps                                                                                                                                            │  █        │
│        █  │      project_file?                   │ │ 1. [bash] find_src_files: tools/pylimit_files-260227 src {{ limits }} | python3 -c "import sys, json; print('files=' + json.dumps([l.strip() for l  │  █        │
│        █  │ ── User sase.yml ──                  │ │ in sys.stdin if l.strip()]))"                                                                                                                       │  █        │
│        █  │   #codex                             │ │                                                                                                                                                     │  █        │
│        █  │   #flash                             │ │ 2. [bash] find_tests_files: tools/pylimit_files-260227 tests {{ limits }} | python3 -c "import sys, json; print('files=' + json.dumps([l.strip()    │  █        │
│        █  │   #gh_dotfiles                       │ │ for l in sys.stdin if l.strip()]))"                                                                                                                 │  █        │
│        █  │   #gh_sase                           │ │                                                                                                                                                     │  █        │
│        █  │   #m_codex                           │ │ 3. [agent] split_src_files: #sase/pysplit {{ file_path }}                                                                                         │  █        │
│        █  │   #m_flash                           │ │ 4. [agent] split_tests_files: #sase/pysplit {{ file_path }}                                                                                       │  █        │
│        █  │   #m_opus_codex                      │ │                        █▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀█                                                                 │  █        │
│        █  │   #m_opus_sonnet                     │ │                        █                                                          █                                                                 │  █        │
│        █  │   #m_pro                             │ │                        █  Add New XPrompt                                         █                                                                 │  █        │
│        █  │   #m_pro_flash                       │ │                        █                                                          █                                                                 │  █        │
│        █  │   #m_sonnet                          │ │                        █  Enter path for new xprompt (.md file):                  █                                                                 │  █        │
│        █  │   #m_swarm                           │ │                        █                                                          █                                                                 │  █        │
│        █  │   #pro                               │ │                        █  ▊▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▎  █                                                                 │  █        │
│        █  │ ── Plugin (sase-github) ──        ▇▇ │ │                        █  ▊  .xprompts/                                        ▎  █                                                                 │  █        │
│        █  │   ⚙ #gh                              │ │                        █  ▊▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▎  █                                                                 │  █        │
│        █  │      gh_ref?                         │ │                        █                                                          █                                                                 │  █        │
│        █  │      n?                              │ │                        █▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄█                                                                 │  █        │
│        █  │      release=True                    │ │                                                                                                                                                     │  █        │
│        █  │      workflow_label?                 │ │                                                                                                                                                     │  █        │
│        █  │   ⚙ #new_pr_desc                     │ │                                                                                                                                                     │  █        │
│        █  │      name?                           │ │                                                                                                                                                     │  █        │
│        █  │   ⚙ #pr                              │ │                                                                                                                                                     │  █        │
│        █  │      name?                           │ │                                                                                                                                                     │  █        │
│        █  │ ── Built-in ──                       │ │                                                                                                                                                     │  █        │
│        █  │   #bd/land_epic                      │ │                                                                                                                                                     │  █        │
│        █  │      bead_id                         │ │                                                                                                                                                     │  █        │
│        █  │   #bd/new_epic                       │ │                                                                                                                                                     │  █        │
│        █  │      plan_file_path                  │ │                                                                                                                                                     │  █        │
│        █  │   #bd/next                           │ │                                                                                                                                                     │  █        │
│        █  │      prompt?                         │ └─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘  █        │
│        █  │   #bd/review/plan                    │                                                                                                                                                          █        │
│        █  │      file_base                       │  ── Source Info ──                                                                                                                                       █        │
│        █  │   #bd/review/prompt                  │  Source: ./.xprompts/pylimit_split.yml                                                                                                                   █        │
│        █  │      file_base                       │  Type: workflow (4 steps)                                                                                                                                █        │
│        █  │   ⚙ #eval_ifs_loops                  │  Inputs: limits (text)                                                                                                                                   █        │
│        █  └──────────────────────────────────────┘  Editable: yes                                                                                                                                           █        │
│        █                                                                                                                                                                                                    █        │
│        █                                                                ^n/^p: navigate  enter: edit  ^o: add new  ^d/^u: scroll  Esc: close                                                                █        │
│        █                                                                                                                                                                                                    █        │
│        █▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄█        │
│                                      ││                                                                                                                                                                              │
│                                      ││                                                                                                                                                                              │
└──────────────────────────────────────┘└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                                                                                                                                                                               RUNNING


```
