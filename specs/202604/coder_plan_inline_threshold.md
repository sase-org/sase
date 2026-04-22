To mitigate the frequent "Prompt is too long" claude errors we've been getting for coder agents, I want to start only
adding an `@` prefix to the plan file when it is below a certain size. Can you help me implement this? You should figure
out what size to make the threshold (i.e. how many lines are allowed in a plan file before we remove the `@` prefix) by
reviewing the existing plan files that were created within the last 2 weeks. This user should be able to override this
default in their sase.yml config. Think this through thoroughly and create a plan using your `/sase_plan` skill before
making any file changes.
