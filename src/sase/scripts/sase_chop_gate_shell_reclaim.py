#!/usr/bin/env python3
"""Gate-shell reclaim chop script."""

import json

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.gate_shell.reclaim import reclaim_pending_gate_shells


@builtin_chop("gate_shell_reclaim")
def _run(runtime: BuiltinChopRuntime) -> None:
    del runtime
    summary = reclaim_pending_gate_shells()
    print(json.dumps(summary.to_dict(), sort_keys=True))


def main() -> None:
    run_builtin_chop("gate_shell_reclaim")


if __name__ == "__main__":
    main()
