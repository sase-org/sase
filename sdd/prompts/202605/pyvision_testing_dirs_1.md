---
plan: sdd/tales/202605/pyvision_testing_dirs_1.md
---
 #resume:rg.cld.plan  Any reference in a testing/ directory should be considered an exception. pyvision should ignore those directories. Can you help me implement that change? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### Additional Requirements

- I meant that the testing/ directory's symbols should not be checked by sase. These are testing utilities so it is expected that they are only used in tests/ files.