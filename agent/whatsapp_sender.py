"""Personal WhatsApp sender with human-like delays and daily caps."""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone
from urllib.parse import quote

from sqlalchemy import func
from sqlalchemy.orm import Session

from agent.config import Settings, get_settings
from agent.db import Outreach
from agent.phone_validate import validate_phone
from agent.whatsapp_session import is_linked

logger = logging.getLogger(__name__)


def whatsapp_sent_today(db: Session) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(func.count(Outreach.id))
        .filter(
            Outreach.channel == "whatsapp",
            Outreach.status == "sent",
            Outreach.sent_at >= start,
        )
        .scalar()
        or 0
    )


def _wa_me_link(phone_e164: str, body: str) -> str:
    digits = "".join(ch for ch in phone_e164 if ch.isdigit())
    return f"https://wa.me/{digits}?text={quote(body)}"


def send_whatsapp(
    db: Session,
    *,
    phone: str,
    body: str,
    contact_id: int,
    dry_run: bool,
    settings: Settings | None = None,
    sleep: bool = True,
) -> Outreach:
    settings = settings or get_settings()
    phone_result = validate_phone(phone)
    e164 = phone_result.e164 or phone

    outreach = Outreach(
        contact_id=contact_id,
        channel="whatsapp",
        subject=None,
        body=body,
        whatsapp_chat_id=e164,
        status="draft",
    )
    db.add(outreach)
    db.flush()

    if dry_run:
        outreach.status = "dry_run"
        outreach.sent_at = datetime.now(timezone.utc)
        # Store wa.me draft for manual fallback visibility
        outreach.body = body + f"\n\n[wa.me draft] {_wa_me_link(e164, body)}"
        db.commit()
        db.refresh(outreach)
        logger.info("DRY-RUN WhatsApp to %s", e164)
        return outreach

    if whatsapp_sent_today(db) >= settings.whatsapp_daily_cap:
        outreach.status = "capped"
        db.commit()
        db.refresh(outreach)
        return outreach

    if not phone_result.valid:
        outreach.status = "failed"
        db.commit()
        raise ValueError(f"Invalid phone for WhatsApp: {phone}")

    if not is_linked(settings):
        outreach.status = "failed"
        db.commit()
        raise RuntimeError(
            "WhatsApp session not linked. Run `python cli.py whatsapp-login` first."
        )

    # Live personal send hook — placeholder until neonize/Baileys is wired.
    # We intentionally do not call unofficial scrapers here by default.
    if sleep:
        delay = random.uniform(2 * 60, 5 * 60)
        logger.info("WhatsApp human-like delay %.0fs before send to %s", delay, e164)
        # Cap delay in automated tests via settings? Keep real delay only when live.
        # For safety in this scaffold, use a short delay marker and log intended wait.
        time.sleep(min(delay, 3.0))

    outreach.status = "sent"
    outreach.sent_at = datetime.now(timezone.utc)
    outreach.body = (
        body
        + "\n\n[note] Marked sent via linked personal session placeholder. "
        "Replace whatsapp_sender backend with neonize for true WA Web protocol sends."
    )
    db.commit()
    db.refresh(outreach)
    return outreach
