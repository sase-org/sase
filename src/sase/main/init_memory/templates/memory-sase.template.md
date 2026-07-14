# SASE = Structured Agentic Software Engineering

{% if project_name %}
## Ephemeral `{{ project_name }}_<N>` Workspace Directories

SASE runs agents (like you) from ephemeral workspace directories, which are full clones of the {{ project_name }} repo.
These directories are named `{{ project_name }}_<N>` where `<N>` is some integer. You need to be mindful not to run
commands outside of these workspace directories, since they have their own isolated virtual environments.

IMPORTANT: Do NOT mention your workspace directory (or any sibling workspace directory) in any plan files that you
generate using your `/sase_plan` skill. The agent(s) that implement the plan might not run in the same workspace
directory as you!

{% endif %}
## Repositories

{% if linked_repo_entries %}
Configured linked repositories for this context:

{{ linked_repo_entries }}

{% else %}
No linked repositories are configured for this context.
{% endif %}

When you need to read or modify files in any repository other than your own workspace checkout, agents MUST use your
`/sase_repo` skill first. This includes configured linked repos and sidecars, another SASE project's repo, and any
GitHub repo not linked to the current project. Open different-project and unlinked GitHub repos as external repos through
the skill. Use the path it prints as the only path for reads and writes.

IMPORTANT REMINDER: Do NOT locate or clone another repo any other way than by using `/sase_repo`!
