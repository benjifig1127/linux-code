"""MTGO Modern metagame & matchup analysis.

Scrapes official Magic Online (mtgo.com) event results, caches the raw JSON
locally, and produces tidy CSVs for metagame share, per-archetype win/loss
records, and a top-8 head-to-head matchup matrix.
"""

from typing import Final

__version__: Final = "0.1.0"
