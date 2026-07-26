"""Shared helpers for chop runner tests."""

import stat
from datetime import datetime, timedelta
from pathlib import Path

from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig


def config_with(**chops_per_jack: list[ChopConfig]) -> AxeConfig:
    return AxeConfig(
        lumberjacks={
            name: LumberjackConfig(
                name=name,
                description=f"Run {name} test chops",
                interval=10,
                chops=chops,
            )
            for name, chops in chops_per_jack.items()
        }
    )


def make_script(tmp: Path, name: str, body: str) -> Path:
    scripts = tmp / "scripts"
    scripts.mkdir(exist_ok=True)
    script = scripts / name
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


def started_at_seconds_ago(seconds: int) -> str:
    return (datetime.now() - timedelta(seconds=seconds)).isoformat()
