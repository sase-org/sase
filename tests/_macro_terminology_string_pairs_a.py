"""Combined pinned string-literal pairs for the macro terminology guard."""

from __future__ import annotations

from tests._macro_terminology_string_pairs_a_early import (
    STRING_PAIRS as STRING_PAIRS_EARLY,
)
from tests._macro_terminology_string_pairs_a_late import (
    STRING_PAIRS as STRING_PAIRS_LATE,
)

STRING_PAIRS = STRING_PAIRS_EARLY | STRING_PAIRS_LATE
