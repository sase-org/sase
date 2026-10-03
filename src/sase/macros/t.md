---
name: t
description: Defer launch until a duration elapses or an absolute wall-clock time.
input:
  - name: time
    type: line
    description:
      Duration (e.g. 5m, 1h30m, 90s) or absolute time (e.g. 1430, 260415/0900).
---

%wait(time={{ time }})
