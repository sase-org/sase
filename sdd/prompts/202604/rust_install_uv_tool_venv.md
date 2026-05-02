---
plan: sdd/tales/202604/rust_install_uv_tool_venv.md
---
 When I run `SASE_CORE_BACKEND=rust sase ace`, I'm getting an error (see below). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
❯ SASE_CORE_BACKEND=rust sase ace
Traceback (most recent call last):
  File "/home/bryan/.local/bin/sase", line 10, in <module>
    sys.exit(main())
             ~~~~^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/main/entry.py", line 35, in main
    handle_ace_command(args)
    ~~~~~~~~~~~~~~~~~~^^^^^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/main/ace_handler.py", line 49, in handle_ace_command
    app = AceApp(
        query=args.query,
    ...<5 lines>...
        restart_axe=getattr(args, "restart_axe", False),
    )
  File "/home/bryan/projects/github/sase-org/sase/src/sase/ace/tui/app.py", line 191, in __init__
    self._init_app_state(
    ~~~~~~~~~~~~~~~~~~~~^
        query=query,
        ^^^^^^^^^^^^
    ...<3 lines>...
        restart_axe=restart_axe,
        ^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/ace/tui/actions/_state_init.py", line 66, in _init_app_state
    self.parsed_query = parse_query(query)
                        ~~~~~~~~~~~^^^^^^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/ace/query/parser.py", line 302, in parse_query
    return _facade(query)
  File "/home/bryan/projects/github/sase-org/sase/src/sase/core/query_facade.py", line 61, in parse_query
    return dispatch(
        operation="parse_query",
    ...<2 lines>...
        args=(query,),
    )
  File "/home/bryan/projects/github/sase-org/sase/src/sase/core/backend.py", line 140, in dispatch
    raise RustBackendUnavailableError(
    ...<3 lines>...
    )
sase.core.backend.RustBackendUnavailableError: Rust backend requested for 'parse_query' but no Rust implementation is registered (Phase 0A ships Python only). Unset SASE_CORE_BACKEND or install the optional sase_core_rs extension.

```