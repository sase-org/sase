---
plan: sdd/tales/202606/project_name_field.md
---
 When `#gh` is given an argument of `<github_org>/<github_repo>` and no project yet exists for `gh_<github_org>_<github_repo>` (i.e. the `~/.sase/projects/gh_<github_org>_<github_repo>/` directory doesn't exist), we currently create it. We also add an alias for this project named `<github_rep>`. We show the project using its full project name `gh_<github_org>_<github_repo>`, which is too verbose and not easily readable.

Can you help me add support for a new project name field (i.e. `PROJECT_NAME: `) that can be configured in project spec files and is configured for new GitHub projects to be equal to `<github_repo>` (instead of using a normal alias). This value should be treated as the project name in all ways except for when determining the file path of the project spec file, of course. Make sure that we use `<github_repo>_<N>` when the `<github_repo>` project name is already in use (this way we can support, for example, the foo-org/foo and bar-org/foo GitHub projects) where `<N>` is the first positive integer such that the `<github_repo>_<N>` project name is not taken.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 