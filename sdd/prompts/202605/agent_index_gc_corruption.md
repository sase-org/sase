---
plan: sdd/tales/202605/agent_index_gc_corruption.md
---
 When I run the `sase agents index gc` command, it is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
sase agents index gc ❯ sase agents index gc
Traceback (most recent call last):
  File "/home/bryan/.local/bin/sase", line 10, in <module>
    sys.exit(main())
             ~~~~^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/main/entry.py", line 44, in main
    handle_agents_command(args)
    ~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/main/agents_handler.py", line 47, in handle_agents_command
    handle_agents_index(args)
    ~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/agents/cli_index.py", line 34, in handle_agents_index
    _handle_agents_index_gc(args)
    ~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/agents/cli_index.py", line 217, in _handle_agents_index_gc
    update = rebuild_agent_artifact_index(index_path, projects_root)
  File "/home/bryan/projects/github/sase-org/sase/src/sase/core/agent_scan_facade.py", line 104, in rebuild_agent_artifact_index
    payload: dict[str, Any] = rust_rebuild(
                              ~~~~~~~~~~~~^
        str(index_path), str(projects_root), _options_to_dict(opts)
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
RuntimeError: database disk image is malformed
```