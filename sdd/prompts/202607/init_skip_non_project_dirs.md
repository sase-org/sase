---
plan: sdd/tales/202607/init_skip_non_project_dirs.md
---
 Can you help me make it so the `sase init` command does not attempt to initialize non-project directories (look for VCS indicators)? When run outside of a project directory, we should just initialize the user's home directory. See the below command output for an example of what I am trying to avoid here. Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  
```
bryan in 🌐 athena in ~
❯ sase init --check
SASE initialization check

Up to date:
  ok   init skills  provider skill files are current

Needs attention:
  run  init memory  refresh 6 memory files and provider shims
    - update    memory/sase.md  generated SASE memory
    - overwrite AGENTS.md  managed AGENTS.md
    - overwrite CLAUDE.md  provider instruction shim
    ... 3 more actions
  run  init sdd     enable version-controlled SDD and create SDD README files and directory map
    - create    sase.yml  enable sdd.version_controlled
    - create    sdd/README.md  top-level README
    - create    sdd/tales/README.md  directory README
    ... 5 more actions

bryan in 🌐 athena in ~
❌1 ❯
```