"""
Entry point for the auction tracker GitHub Actions workflow.
Kept separate so auction_tracker.yml avoids inline multi-line python -c "..." YAML.
"""
import sys
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

sys.path.insert(0, str(Path(".").resolve()))

from monitor import get_config, run_watchlist_check

config = get_config()
config["watchlist_file"] = Path("watchlist.json")
run_watchlist_check(config)
