---
plan: sdd/tales/202606/invalid_sase_project.md
---
 Can you help me figure out how the invalid ".sase" project keeps getting added to our project list and stop it from happening in the future (see the below command output for context)? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.

```
❌2 ❯ sase project
PROJECT                  STATE      CLAIMS LAUNCH  WORKSPACE
.sase                    active          0 no      -
CV                       active          0 yes     /home/bryan/projects/github/bbugyi200/CV/
beads                    active          0 yes     /home/bryan/projects/github/steveyegge/beads/
bob-cli                  active          0 yes     /home/bryan/projects/github/bbugyi200/bob-cli/
sase                     active          0 yes     /home/bryan/projects/github/sase-org/sase/
zorg                     active          0 yes     /home/bryan/projects/github/zettel-org/zorg/
```