---
plan: sdd/tales/202605/artifact_viewer_runpy_warning.md
---
 Every time I launch the artifact viewer, the below warning message appears before the first image is displayed. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
<frozen runpy>:128: RuntimeWarning: 'sase.ace.tui.graphics.viewer' found in sys.modules after import of package 'sase.ace.tui.graphics', but prior to execution of 'sase.ace.tui.graphics.viewer'; this may result in unpredictable behaviour
```