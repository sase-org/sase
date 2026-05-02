---
plan: sdd/plans/202604/fix_keymaps_cache_mutation.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
=========================== short test summary info ============================
FAILED tests/test_keybinding_footer_status.py::test_keybinding_footer_axe_bindings - AssertionError: assert ('K', 'start axe') == ('x', 'start axe')
  
  At index 0 diff: 'K' != 'x'
  
  Full diff:
    (
  -     'x',
  ?      ^
  +     'K',
  ?      ^
        'start axe',
    )
====== 1 failed, 5330 passed, 8 skipped, 14 warnings in 88.02s (0:01:28) =======
error: Recipe `test-cov` failed on line 113 with exit code 1
Error: Process completed with exit code 1.
```