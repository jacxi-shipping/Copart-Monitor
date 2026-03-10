"""
Telegram notifier for Copart Monitor.

NLR lots get a green ✅ badge and "No License Required" label.
Broker lots get a 🔑 badge and "Broker Required" label — so you always know at a glance.
"""

import logging
import httpx

logger = logging.getLogger(__name__)


def _esc(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    for ch in r"\_*[]()~`>#+=|{}.!-":
        text = text.replace(ch, f"\\{ch}")
    return text


def _format_sale_date(ts_ms) -> str:
    """Convert Unix ms timestamp to readable date string."""
    if not ts_ms:
        return "TBD"
    try:
        from datetime import datetime, timezone
        ts = int(ts_ms)
        if ts > 1_000_000_000_000:
            ts = ts / 1000
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%b %d, %Y %I:%M %p UTC")
    except Exception:
        return str(ts_ms)


def send_telegram(token: str, chat_id: str, lots: list):
    """Send new lot notifications. NLR and broker lots are labelled distinctly."""
    with httpx.Client(timeout=20) as client:
        for lot in lots:
            try:
                _send_lot(client, token, chat_id, lot)
            except Exception as e:
                logger.warning("Failed to send lot %s: %s", lot.get("lot_number"), e)


def _send_lot(client, token, chat_id, lot):
    is_nlr   = lot.get("is_nlr", False)
    nlr_line = "✅ *No License Required*" if is_nlr else "🔑 *Broker Required*"

    title    = lot.get("title", "Unknown")
    lot_num  = lot.get("lot_number", "")
    damage   = lot.get("damage") or "N/A"
    sec_dmg  = lot.get("secondary_damage") or ""
    odo      = lot.get("odometer")
    estimate = lot.get("estimate")
    location = lot.get("location") or "Unknown"
    sale_date = _format_sale_date(lot.get("sale_date"))
    url      = lot.get("url", "")
    image_url = lot.get("image_url", "")

    odo_str  = f"{int(odo):,} mi" if odo else "N/A"
    est_str  = f"\\${int(estimate):,}" if estimate else "N/A"
    dmg_str  = _esc(damage)
    if sec_dmg:
        dmg_str += f" \\| {_esc(sec_dmg)}"

    text = (
        f"🚗 *{_esc(title)}*\n"
        f"{nlr_line}\n\n"
        f"📅 Sale: {_esc(sale_date)}\n"
        f"📍 {_esc(location)}\n"
        f"🔧 Damage: {dmg_str}\n"
        f"🛣 Odometer: {_esc(odo_str)}\n"
        f"💲 Est\\. Value: {est_str}\n"
        f"🔢 Lot: {_esc(lot_num)}\n\n"
        f"[View on Copart]({url})"
    )

    if image_url:
        resp = client.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            json={"chat_id": chat_id, "photo": image_url,
                  "caption": text, "parse_mode": "MarkdownV2"},
        )
    else:
        resp = client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "MarkdownV2"},
        )

    if resp.status_code != 200:
        logger.warning("Telegram error %d: %s", resp.status_code, resp.text[:200])
    else:
        logger.info("Sent lot %s (%s)", lot_num, "NLR" if is_nlr else "Broker")


def test_connection(token: str, chat_id: str) -> bool:
    """Send a test message and return True if successful."""
    text = (
        "✅ *Copart Monitor connected\\!*\n\n"
        "You will now receive alerts for new listings\\.\n\n"
        "🔑 Lots needing a broker will show: 🔑 *Broker Required*\n"
        "✅ Lots you can buy directly: ✅ *No License Required*"
    )
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "MarkdownV2"},
            )
            ok = resp.status_code == 200
            if ok:
                logger.info("✅ Telegram test OK")
            else:
                logger.error("Telegram test failed: %d %s", resp.status_code, resp.text[:200])
            return ok
    except Exception as e:
        logger.error("Telegram test exception: %s", e)
        return False


# ---------------------------------------------------------------------------
# Auction tracker bid alerts
# ---------------------------------------------------------------------------

ALERT_EMOJIS = {
    "closing_soon": "🚨",
    "sold":         "🔴",
    "update":       "🟢",
}


def send_bid_alert(token: str, chat_id: str, lot: dict,
                   alert_type: str, current_bid: float = 0,
                   minutes_left: float = None):
    """Send a bid update alert for a tracked lot."""
    emoji  = ALERT_EMOJIS.get(alert_type, "📢")
    title  = lot.get("title", "Unknown")
    target = lot.get("target_price", 0)
    url    = lot.get("url", "")
    image_url = lot.get("image_url", "")
    odo    = lot.get("odometer", "?")
    damage = lot.get("damage", "?")
    is_nlr = lot.get("is_nlr", False)
    nlr_tag = "✅ NLR" if is_nlr else "🔑 Broker"

    if alert_type == "closing_soon":
        status = f"CLOSING IN {int(minutes_left)} MINS"
    elif alert_type == "sold":
        status = "AUCTION CLOSED"
    else:
        status = "BID UPDATE"

    under_by  = target - current_bid
    budget_str = (f"✅ \\${under_by:,.0f} under target"
                  if under_by >= 0 else f"❌ \\${-under_by:,.0f} over budget")
    time_str  = f"{int(minutes_left)} min left" if minutes_left else "time unknown"
    odo_str   = f"{int(odo):,} mi" if isinstance(odo, (int, float)) else str(odo)

    text = (
        f"{emoji} *{_esc(status)}*  \\|  {_esc(nlr_tag)}\n"
        f"🚗 {_esc(title)}\n"
        f"💰 Current Bid: *\\${current_bid:,.0f}*\n"
        f"🎯 Your Target: \\${target:,}\n"
        f"{budget_str}\n"
        f"⏱ {_esc(time_str)}\n"
        f"🔧 {_esc(damage)}  \\|  {_esc(odo_str)}\n"
        f"[View Lot]({url})"
    )

    with httpx.Client(timeout=15) as client:
        try:
            if image_url:
                client.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    json={"chat_id": chat_id, "photo": image_url,
                          "caption": text, "parse_mode": "MarkdownV2"},
                )
            else:
                client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "parse_mode": "MarkdownV2"},
                )
        except Exception as e:
            logger.warning("Bid alert send failed: %s", e)
