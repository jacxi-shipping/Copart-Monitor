"""
Copart unofficial API client.
Reverse-engineered from Copart's web app network traffic.
"""

import httpx
import json
import logging

logger = logging.getLogger(__name__)

BASE_URL = "https://api.copart.com/public/lots/search/US"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://www.copart.com",
    "Referer": "https://www.copart.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
}


def build_search_payload(
    makes,
    damage_types,
    year_min=None,
    year_max=None,
    page=0,
    rows=100,
):
    """Build the POST body for Copart's search endpoint."""
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

    # Year range filter
    if year_min is not None or year_max is not None:
        payload["filter"]["YEAR"] = {
            "from": str(year_min) if year_min else "*",
            "to": str(year_max) if year_max else "*",
        }

    return payload


def parse_lot(raw):
    """Normalize a raw Copart lot into a clean dict."""
    return {
        "lot_number": str(raw.get("lotNumberStr") or raw.get("ln") or ""),
        "title": raw.get("ld") or f"{raw.get('y', '')} {raw.get('mkn', '')} {raw.get('mdn', '')}".strip(),
        "year": raw.get("y"),
        "make": raw.get("mkn") or raw.get("mk"),
        "model": raw.get("mdn") or raw.get("md"),
        "damage": raw.get("dd") or raw.get("dmg"),
        "odometer": raw.get("orr") or raw.get("od"),
        "sale_date": raw.get("ad") or raw.get("saleDate"),
        "location": raw.get("yn") or raw.get("yardName"),
        "estimate": raw.get("la") or raw.get("lv"),
        "image_url": raw.get("tims") or raw.get("imgUrl"),
        "url": f"https://www.copart.com/lot/{raw.get('lotNumberStr') or raw.get('ln', '')}",
    }


def search_api(makes, damage_types, year_min=None, year_max=None, max_pages=3):
    """
    Query Copart's unofficial API.
    Returns a list of normalized lot dicts, or raises on failure.
    """
    results = []
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for page in range(max_pages):
            payload = build_search_payload(
                makes, damage_types,
                year_min=year_min, year_max=year_max,
                page=page,
            )
            logger.debug("API request page=%d", page)

            resp = client.post(BASE_URL, json=payload)
            resp.raise_for_status()

            data = resp.json()
            content = (
                data.get("data", {})
                    .get("results", {})
                    .get("content", [])
            )
            if not content:
                logger.debug("No more results at page %d", page)
                break

            for raw in content:
                results.append(parse_lot(raw))

            total_pages = (
                data.get("data", {})
                    .get("results", {})
                    .get("totalPages", 1)
            )
            if page + 1 >= total_pages:
                break

    logger.info("API returned %d lots", len(results))
    return results
