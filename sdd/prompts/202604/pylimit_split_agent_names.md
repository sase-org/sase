---
plan: sdd/plans/202604/pylimit_split_agent_names.md
---
 #resume:sase-11.land  Can you help me name the `sase_pylimit_split` chop agents `pysplit.<base_name>` using the `%name` directive, where `<base_name>` is the basename with no extension of the file that the agent
is responsible for splitting (ex: if the the file the agent is splitting is src/sase/foobar.py, then the agents name would be "pysplit.foobar"). We are unlikely to need to deduplicate these names, but make sure that you add some logic
for that, just in case multiple files with the same basename need to be split in the same workflow run. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
