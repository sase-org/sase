---
plan: sdd/tales/202604/retry_as_new_agent.md
---
 When an sase agent needs to be retried, we currently lose a lot of the context from the failed agents. Can you help me start creating a brand new agent for each retry (i.e. like `sase run -d` had been used to launch the
agent)? Make sure that there is still a clear indicator that marks these agents as retries and that there is a way to easily associate them back to the previous (failed) agents. I want you to lead the design on this one. Just make sure it looks beautiful! Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
