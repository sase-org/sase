"""Command implementations for the ``sase artifact`` CLI group."""

from sase.artifact_cli.create import handle_create
from sase.artifact_cli.doctor import handle_doctor
from sase.artifact_cli.listing import handle_list
from sase.artifact_cli.open import handle_open
from sase.artifact_cli.path import handle_path
from sase.artifact_cli.prune import handle_prune
from sase.artifact_cli.reclaim import handle_reclaim
from sase.artifact_cli.show import handle_show
from sase.artifact_cli.stats import handle_stats
from sase.artifact_cli.trash import handle_trash

__all__ = [
    "handle_create",
    "handle_doctor",
    "handle_list",
    "handle_open",
    "handle_path",
    "handle_prune",
    "handle_reclaim",
    "handle_show",
    "handle_stats",
    "handle_trash",
]
