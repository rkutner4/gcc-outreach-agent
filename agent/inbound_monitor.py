"""Inbound reply detection for Gmail + WhatsApp — NEVER auto-replies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from agent.config import Settings, get_settings
from agent.db import Contact, InboundMessage, Outreach
from agent.gmail_sender import SCOPES, gmail_configured

logger = logging.getLogger(__name__)


def _gmail_service(settings: Settings):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_path = Path(settings.gmail_token_path)
    if not token_path.is_absolute():
        token_path = settings.root_dir / token_path
    if not token_path.exists():
        raise FileNotFoundError("Gmail token missing; authorize Gmail first")
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def poll_gmail_replies(db: Session, settings: Settings | None = None) -> list[InboundMessage]:
    """Detect replies on known Gmail threads. Does not send any response."""
    settings = settings or get_settings()
    created: list[InboundMessage] = []
    if not gmail_configured(settings):
        logger.info("Gmail not configured — skipping inbound poll")
        return created

    try:
        service = _gmail_service(settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gmail inbound poll unavailable: %s", exc)
        return created

    sent = (
        db.query(Outreach)
        .filter(
            Outreach.channel == "email",
            Outreach.gmail_thread_id.isnot(None),
            Outreach.status.in_(["sent", "dry_run"]),
        )
        .all()
    )
    for outreach in sent:
        thread_id = outreach.gmail_thread_id
        if not thread_id:
            continue
        try:
            thread = (
                service.users()
                .threads()
                .get(userId="me", id=thread_id, format="metadata")
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Thread fetch failed for %s: %s", thread_id, exc)
            continue
        messages = thread.get("messages") or []
        if len(messages) <= 1:
            continue
        # Any message beyond the first is treated as potential reply activity
        last = messages[-1]
        external_id = last.get("id")
        exists = (
            db.query(InboundMessage)
            .filter(InboundMessage.external_id == external_id)
            .one_or_none()
        )
        if exists:
            continue
        snippet = ""
        for header in (last.get("payload") or {}).get("headers") or []:
            if header.get("name", "").lower() == "subject":
                snippet = header.get("value") or ""
                break
        inbound = InboundMessage(
            contact_id=outreach.contact_id,
            outreach_id=outreach.id,
            channel="email",
            body=snippet or f"Reply detected on Gmail thread {thread_id}",
            received_at=datetime.now(timezone.utc),
            handled=False,
            external_id=external_id,
        )
        db.add(inbound)
        created.append(inbound)

    db.commit()
    return created


def record_whatsapp_inbound(
    db: Session,
    *,
    phone: str,
    body: str,
    contact_id: int | None = None,
    outreach_id: int | None = None,
    external_id: str | None = None,
) -> InboundMessage:
    """Manual/listener entrypoint for WhatsApp replies. Never auto-responds."""
    if contact_id is None:
        contact = db.query(Contact).filter(Contact.phone == phone).one_or_none()
        contact_id = contact.id if contact else None
    inbound = InboundMessage(
        contact_id=contact_id,
        outreach_id=outreach_id,
        channel="whatsapp",
        body=body,
        received_at=datetime.now(timezone.utc),
        handled=False,
        external_id=external_id,
    )
    db.add(inbound)
    db.commit()
    db.refresh(inbound)
    return inbound


def poll_inbound(db: Session, settings: Settings | None = None) -> dict:
    gmail = poll_gmail_replies(db, settings)
    return {
        "gmail_replies": len(gmail),
        "whatsapp_replies": 0,
        "note": "WhatsApp replies are detected via session listener / manual record; never auto-replied.",
    }
