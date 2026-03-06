"""
Copart API client — uses a two-step approach:
1. First visits copart.com to get session cookies
2. Then calls the search API with those cookies
"""

import httpx
import logging

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.copart.com/public/lots/search/US"
HOME_URL   = "https://www.copart.com/"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://www.copart.com",
    "Referer": "https://www.copart.com/lotSearchResults/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}


def build_payload(makes, damage_types, year_min=None, year_max=None, max_odometer=None, page=0, rows=100):
    filter_list = []

    if makes:
        filter_list.append({
            "displayName": "Make",
            "name": "make",
            "values": [m.upper() for m in makes],
        })
    if damage_types:
        filter_list.append({
            "displayName": "Primary Damage",
            "name": "primaryDamage",
            "values": [d.upper() for d in damage_types],
        })

    payload = {
        "query": ["*"],
        "filter": {
            "SALE_STATUS": ["On Time, Sold"],
            "AUCTION_COUNTRY_CODE": ["US"],
        },
        "sort": {"auction_date_type": "desc"},
        "page": page,
        "size": rows,
        "start": page * rows,
        "watchListOnly": False,
        "freeFormFilters": filter_list,
        "defaultSort": False,
    }

    if year_min is not None or year_max is not None:
        payload["filter"]["YEAR"] = {
            "from": str(year_min) if year_min else "*",
            "to": str(year_max) if year_max else "*",
        }

    return payload


def parse_lot(raw):
    lot_number = str(raw.get("lotNumberStr") or raw.get("ln") or "")
    return {
        "lot_number": lot_number,
        "title": (
            raw.get("ld")
            or f"{raw.get('y', '')} {raw.get('mkn', '')} {raw.get('mdn', '')}".strip()
        ),
        "year": raw.get("y"),
        "make": raw.get("mkn") or raw.get("mk"),
        "model": raw.get("mdn") or raw.get("md"),
        "damage": raw.get("dd") or raw.get("dmg"),
        "odometer": raw.get("orr") or raw.get("od"),
        "sale_date": raw.get("ad") or raw.get("saleDate"),
        "location": raw.get("yn") or raw.get("yardName"),
        "estimate": raw.get("la") or raw.get("lv"),
        "image_url": raw.get("tims") or raw.get("imgUrl"),
        "url": f"https://www.copart.com/lot/{lot_number}",
    }


def _passes_filters(lot, max_odometer):
    """Post-fetch client-side odometer filter."""
    if max_odometer and lot.get("odometer"):
        try:
            odo = int(str(lot["odometer"]).replace(",", "").strip())
            if odo > max_odometer:
                return False
        except (ValueError, TypeError):
            pass
    return True


def search_api(makes, damage_types, year_min=None, year_max=None, max_odometer=None, max_pages=3):
    """
    Two-step: visit homepage to get cookies, then call search API.
    """
    results = []

    with httpx.Client(
        headers=HEADERS,
        timeout=30,
        follow_redirects=True,
    ) as client:
        # Step 1 — get session cookies by visiting homepage
        try:
            logger.info("Fetching Copart homepage for session cookies...")
            home_resp = client.get(HOME_URL)
            logger.info("Homepage status: %d, cookies: %s", home_resp.status_code, list(client.cookies.keys()))
        except Exception as e:
            logger.warning("Homepage fetch failed: %s", e)

        # Step 2 — call search API with session cookies
        for page in range(max_pages):
            payload = build_payload(
                makes, damage_types,
                year_min=year_min, year_max=year_max,
                page=page,
            )

            resp = client.post(SEARCH_URL, json=payload)
            logger.info("Search API page=%d status=%d", page, resp.status_code)
            resp.raise_for_status()

            data = resp.json()
            content = (
                data.get("data", {})
                    .get("results", {})
                    .get("content", [])
            )
            if not content:
                logger.info("No more results at page %d", page)
                break

            for raw in content:
                lot = parse_lot(raw)
                if _passes_filters(lot, max_odometer):
                    results.append(lot)

            total_pages = (
                data.get("data", {})
                    .get("results", {})
                    .get("totalPages", 1)
            )
            logger.info("Page %d: got %d lots, total_pages=%d", page, len(content), total_pages)
            if page + 1 >= total_pages:
                break

    logger.info("API returned %d lots after filtering", len(results))
    return results
