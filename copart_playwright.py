"""
Playwright-based fallback scraper for Copart.
Intercepts network responses from Copart's internal search API.
"""

import logging
import time

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.copart.com/lotSearchResults/"


def _build_search_url(makes, damage_types):
    from urllib.parse import quote
    query_parts = []
    if makes:
        encoded = quote(",".join(m.upper() for m in makes), safe=",")
        query_parts.append(f"makeList={encoded}")
    if damage_types:
        encoded = quote(",".join(d.upper() for d in damage_types), safe=",")
        query_parts.append(f"damageList={encoded}")
    query = "&".join(query_parts)
    return f"{SEARCH_URL}?{query}" if query else SEARCH_URL


def _matches_filters(raw, makes, damage_types, year_min=None, year_max=None, max_odometer=None):
    if makes:
        lot_make = (raw.get("mkn") or raw.get("mk") or "").upper()
        if not any(m.upper() in lot_make for m in makes):
            return False
    if damage_types:
        lot_damage = (raw.get("dd") or raw.get("dmg") or "").upper()
        if not any(d.upper() in lot_damage for d in damage_types):
            return False
    lot_year = raw.get("y")
    if lot_year:
        try:
            y = int(lot_year)
            if year_min and y < year_min:
                return False
            if year_max and y > year_max:
                return False
        except (ValueError, TypeError):
            pass
    if max_odometer is not None:
        raw_odo = raw.get("orr") or raw.get("od")
        if raw_odo is not None:
            try:
                odo = int(str(raw_odo).replace(",", "").strip())
                if odo > max_odometer:
                    return False
            except (ValueError, TypeError):
                pass
    return True


def search_playwright(makes, damage_types, year_min=None, year_max=None, max_odometer=None, max_pages=3):
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        raise RuntimeError("playwright not installed.")

    url = _build_search_url(makes, damage_types)
    intercepted = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--window-size=1280,900",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            },
            java_script_enabled=True,
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = { runtime: {} };
        """)

        page = context.new_page()

        def handle_response(response):
            try:
                if response.status != 200:
                    return
                ct = response.headers.get("content-type", "")
                if "application/json" not in ct:
                    return
                resp_url = response.url
                if "copart.com" not in resp_url:
                    return
                data = response.json()
                content = (
                    data.get("data", {}).get("results", {}).get("content")
                    or data.get("returnObject", {}).get("results", {}).get("content")
                    or data.get("results", {}).get("content")
                    or []
                )
                if content:
                    logger.info("Intercepted %d lots from: %s", len(content), resp_url)
                    intercepted.extend(content)
            except Exception as e:
                logger.debug("Response intercept error: %s", e)

        page.on("response", handle_response)

        # Step 1: visit homepage first to get cookies
        logger.info("Visiting Copart homepage for cookies...")
        try:
            page.goto("https://www.copart.com/", wait_until="domcontentloaded", timeout=20_000)
            time.sleep(2)
        except Exception as e:
            logger.warning("Homepage visit failed: %s", e)

        # Step 2: navigate to search results
        logger.info("Navigating to search: %s", url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        except PWTimeout:
            logger.warning("domcontentloaded timeout")

        # Wait for JS to execute and fire API calls
        time.sleep(6)

        # Scroll to trigger lazy loading
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(1)
        except Exception:
            pass

        # Debug info
        try:
            title = page.title()
            page_url = page.url
            body = page.inner_text("body") if page.query_selector("body") else ""
            logger.info("Page title: '%s'", title)
            logger.info("Page URL: %s", page_url)
            logger.info("Body preview: %s", body[:400].replace("\n", " "))
        except Exception as ex:
            logger.info("Debug error: %s", ex)

        browser.close()

    # Debug: log first lot's raw keys and values
    if intercepted:
        sample = intercepted[0]
        logger.info("SAMPLE RAW KEYS: %s", sorted(sample.keys()))
        logger.info("SAMPLE VALUES: lcy=%s mkn=%s dd=%s orr=%s ln=%s",
            sample.get("lcy"), sample.get("mkn"), sample.get("dd"),
            sample.get("orr"), sample.get("ln"))

    before = len(intercepted)
    filtered = []
    for raw in intercepted:
        passed = _matches_filters(raw, makes, damage_types, year_min, year_max, max_odometer)
        logger.info("LOT %s | make=%-12s | damage=%-25s | year=%s | odo=%s | pass=%s",
            raw.get("ln", ""), raw.get("mkn", ""), raw.get("dd", ""),
            raw.get("lcy", "?"), raw.get("orr", "?"), passed)
        if passed:
            filtered.append(raw)
    logger.info("Client-side filter: %d intercepted → %d matched", before, len(filtered))

    results = [_parse_lot(raw) for raw in filtered]
    results = [r for r in results if r.get("lot_number")]
    logger.info("Playwright returned %d lots", len(results))
    return results


def _parse_lot(raw):
    lot_number = str(raw.get("ln") or raw.get("lotNumberStr") or "")
    year  = raw.get("lcy") or raw.get("y") or raw.get("yr")
    make  = raw.get("mkn") or raw.get("mk")
    model = raw.get("lm")  or raw.get("mdn") or raw.get("md")
    damage = raw.get("dd") or raw.get("dmg")
    return {
        "lot_number": lot_number,
        "title": raw.get("ld") or f"{year or ''} {make or ''} {model or ''}".strip(),
        "year": year,
        "make": make,
        "model": model,
        "damage": damage,
        "odometer": raw.get("orr") or raw.get("od"),
        "sale_date": raw.get("ad"),
        "location": raw.get("yn"),
        "estimate": raw.get("la") or raw.get("lv"),
        "image_url": raw.get("tims"),
        "url": f"https://www.copart.com/lot/{lot_number}/{raw.get('ldu','')}".rstrip("/"),
    }
