---
plan: sdd/tales/202606/plugin_list_packaging_import.md
---
  When I run `sase plugin list` now, it crashes (see the error below). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

```
Traceback (most recent call last):
  File "/home/bryan/.local/bin/sase", line 10, in <module>
    sys.exit(main())
             ~~~~^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/main/entry.py", line 284, in main
    handle_plugin_command(args)
    ~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/main/plugin_handler.py", line 17, in handle_plugin_command
    from sase.plugins.cli_list import handle_plugin_list_command
  File "/home/bryan/projects/github/sase-org/sase/src/sase/plugins/cli_list.py", line 21, in <module>
    from sase.plugins.catalog import (
    ...<3 lines>...
    )
  File "/home/bryan/projects/github/sase-org/sase/src/sase/plugins/catalog.py", line 37, in <module>
    from sase.plugins.latest import LatestInfo, is_newer
  File "/home/bryan/projects/github/sase-org/sase/src/sase/plugins/latest.py", line 14, in <module>
    from packaging.version import InvalidVersion, Version
ModuleNotFoundError: No module named 'packaging'

```