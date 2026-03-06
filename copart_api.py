"""
Copart API client — session cookie approach with strict client-side filtering.
"""

import httpx
import logging

logger = logging.getLogger(__name__)

HOME_URL = "https://www.copart.com/"
SEARCH_ENDPOINTS = [
    "https://www.copart.com/public/lots/search",
    "https://www.copart.com/public/lots/search/US",
    "https://api.copart.com/public/lots/search",
    "https://api.copart.com/public/lots/search/US",
]

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


def build_payload(makes, damage_types, year_min=None, year_max=None, page=0, rows=100):
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

    # Year can be in multiple fields depending on endpoint
    year = (
        raw.get("y") or raw.get("yr") or raw.get("year")
        or raw.get("lty") or raw.get("vehicleYear")
    )

    # Make can be in multiple fields
    make = (
        raw.get("mkn") or raw.get("mk") or raw.get("make")
        or raw.get("makeDesc") or raw.get("mke")
    )

    # Damage can be in multiple fields
    damage = (
        raw.get("dd") or raw.get("dmg") or raw.get("damage")
        or raw.get("primaryDamage") or raw.get("dmgDesc")
        or raw.get("pd") or raw.get("pdd")
    )

    # Odometer
    odometer = (
        raw.get("orr") or raw.get("od") or raw.get("odometer")
        or raw.get("odometerReading") or raw.get("odm")
    )

    # Log all raw keys on first parse to help debug field names
    if not hasattr(parse_lot, "_logged_keys"):
        parse_lot._logged_keys = True
        logger.info("RAW LOT KEYS: %s", sorted(raw.keys()))
        logger.info("RAW LOT SAMPLE: year=%s make=%s damage=%s odo=%s",
            raw.get("y"), raw.get("mkn"), raw.get("dd"), raw.get("orr"))

    return {
        "lot_number": lot_number,
        "title": (
            raw.get("ld")
            or f"{year or ''} {make or ''} {raw.get('mdn') or raw.get('md') or ''}".strip()
        ),
        "year": year,
        "make": make,
        "model": raw.get("mdn") or raw.get("md") or raw.get("model"),
        "damage": damage,
        "odometer": odometer,
        "sale_date": raw.get("ad") or raw.get("saleDate"),
        "location": raw.get("yn") or raw.get("yardName"),
        "estimate": raw.get("la") or raw.get("lv"),
        "image_url": raw.get("tims") or raw.get("imgUrl"),
        "url": f"https://www.copart.com/lot/{lot_number}",
    }


def _passes_filters(lot, makes, damage_types, year_min, year_max, max_odometer):
    """Strict client-side filter."""
    # Make
    if makes:
        lot_make = (lot.get("make") or "").upper()
        if not any(m.upper() in lot_make for m in makes):
            return False

    # Damage
    if damage_types:
        lot_damage = (lot.get("damage") or "").upper()
        if not any(d.upper() in lot_damage for d in damage_types):
            return False

    # Year — only filter if year is known
    year = lot.get("year")
    if year is not None:
        try:
            y = int(year)
            if year_min and y < year_min:
                return False
            if year_max and y > year_max:
                return False
        except (ValueError, TypeError):
            pass
    # If year is None/unknown → keep the lot (don't reject)

    # Odometer — only filter if odometer is known
    if max_odometer and lot.get("odometer") is not None:
        try:
            odo = int(str(lot["odometer"]).replace(",", "").strip())
            if odo > max_odometer:
                return False
        except (ValueError, TypeError):
            pass

    return True


def _extract_content(data):
    return (
        data.get("data", {}).get("results", {}).get("content")
        or data.get("returnObject", {}).get("results", {}).get("content")
        or data.get("results", {}).get("content")
        or []
    )


def _extract_total_pages(data):
    return (
        data.get("data", {}).get("results", {}).get("totalPages")
        or data.get("returnObject", {}).get("results", {}).get("totalPages")
        or data.get("results", {}).get("totalPages")
        or 1
    )


def _find_working_endpoint(client, payload):
    for url in SEARCH_ENDPOINTS:
        try:
            resp = client.post(url, json=payload, timeout=15)
            logger.info("Tried %s → %d", url, resp.status_code)
            if resp.status_code == 200:
                data = resp.json()
                content = _extract_content(data)
                if content is not None:
                    logger.info("✅ Working endpoint: %s (%d lots)", url, len(content))
                    return url, data
        except Exception as e:
            logger.debug("Endpoint %s error: %s", url, e)
    return None, None


def search_api(makes, damage_types, year_min=None, year_max=None, max_odometer=None, max_pages=3):
    results = []

    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        # Get session cookies
        try:
            logger.info("Fetching Copart homepage for session cookies...")
            home = client.get(HOME_URL)
            logger.info("Homepage: status=%d cookies=%s", home.status_code, list(client.cookies.keys()))
        except Exception as e:
            logger.warning("Homepage failed: %s", e)

        # Find working endpoint
        payload0 = build_payload(makes, damage_types, year_min=year_min, year_max=year_max, page=0)
        working_url, first_data = _find_working_endpoint(client, payload0)

        if not working_url:
            raise RuntimeError("No working Copart API endpoint found")

        content = _extract_content(first_data)
        total_pages = _extract_total_pages(first_data)
        logger.info("Page 0: %d lots, total_pages=%d", len(content), total_pages)

        before = 0
        for raw in content:
            lot = parse_lot(raw)
            before += 1
            passed = _passes_filters(lot, makes, damage_types, year_min, year_max, max_odometer)
            logger.info(
                "LOT %s | make=%-12s | damage=%-25s | year=%s | odo=%s | pass=%s",
                lot.get("lot_number", ""), lot.get("make", ""), lot.get("damage", ""),
                lot.get("year", "?"), lot.get("odometer", "?"), passed,
            )
            if passed:
                results.append(lot)

        # More pages
        for page in range(1, min(max_pages, total_pages)):
            payload = build_payload(makes, damage_types, year_min=year_min, year_max=year_max, page=page)
            resp = client.post(working_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = _extract_content(data)
            logger.info("Page %d: %d lots", page, len(content))
            if not content:
                break
            for raw in content:
                lot = parse_lot(raw)
                before += 1
                if _passes_filters(lot, makes, damage_types, year_min, year_max, max_odometer):
                    results.append(lot)

        logger.info(
            "Client-side filter: %d fetched → %d matched (makes=%s damage=%s years=%s-%s max_odo=%s)",
            before, len(results), makes, damage_types,
            year_min or "*", year_max or "*", max_odometer or "*",
        )

    logger.info("API returned %d lots after filtering", len(results))
    return results
