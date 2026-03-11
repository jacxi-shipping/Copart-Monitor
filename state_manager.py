"""
State management — tracks which lots have been seen and stores full lot details
so they can be exported to a spreadsheet at any time.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = Path("state.json")


def load_state(path: Path = DEFAULT_STATE_FILE) -> dict:
    if not path.exists():
        logger.info("No existing state file, starting fresh")
        return {"seen_lots": [], "lot_details": {}, "last_run": None, "total_seen": 0}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Migrate old format (seen_lots was a list of strings, no lot_details)
        if "lot_details" not in data:
            data["lot_details"] = {}
        logger.info("Loaded state: %d seen lots, last run: %s",
                    len(data.get("seen_lots", [])), data.get("last_run"))
        return data
    except Exception as e:
        logger.error("Failed to load state file: %s — starting fresh", e)
        return {"seen_lots": [], "lot_details": {}, "last_run": None, "total_seen": 0}


def save_state(state: dict, path: Path = DEFAULT_STATE_FILE) -> None:
    seen = state.get("seen_lots", [])
    details = state.get("lot_details", {})

    # Cap to last 5000 to keep file size manageable
    if len(seen) > 5000:
        seen = seen[-5000:]
        # Also prune lot_details to only keep seen lots
        seen_set = set(seen)
        details = {k: v for k, v in details.items() if k in seen_set}

    state["seen_lots"] = seen
    state["lot_details"] = details
    state["last_run"] = datetime.now(timezone.utc).isoformat()

    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    logger.info("Saved state: %d seen lots", len(seen))


def find_new_lots(lots: list[dict], state: dict) -> list[dict]:
    seen_set = set(state.get("seen_lots", []))
    new_lots = [lot for lot in lots if lot["lot_number"] not in seen_set]
    logger.info("Total fetched: %d | Already seen: %d | New: %d",
                len(lots), len(lots) - len(new_lots), len(new_lots))
    return new_lots


def mark_seen(lots: list[dict], state: dict) -> dict:
    """Add lot numbers and full details to state."""
    seen_set = set(state.get("seen_lots", []))
    details = state.get("lot_details", {})

    for lot in lots:
        ln = lot["lot_number"]
        seen_set.add(ln)
        # Store full details, adding a first_seen timestamp
        if ln not in details:
            details[ln] = {**lot, "first_seen": datetime.now(timezone.utc).isoformat()}
        else:
            # Update any fields that may have changed (current_bid, etc.)
            details[ln].update({k: v for k, v in lot.items() if k != "first_seen"})

    state["seen_lots"] = list(seen_set)
    state["lot_details"] = details
    state["total_seen"] = state.get("total_seen", 0) + len(lots)
    return state
