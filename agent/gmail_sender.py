"""Gmail API sender with daily caps and thread tracking."""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from agent.config import Settings, get_settings
from agent.db import Outreach

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _credentials(settings: Settings):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds_path = Path(settings.gmail_credentials_path)
    if not creds_path.is_absolute():
        creds_path = settings.root_dir / creds_path
    token_path = Path(settings.gmail_token_path)
    if not token_path.is_absolute():
        token_path = settings.root_dir / token_path

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(
                    f"Gmail client secrets not found at {creds_path}. "
                    "Place OAuth client JSON there or enable dry-run."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def gmail_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    creds_path = Path(settings.gmail_credentials_path)
    if not creds_path.is_absolute():
        creds_path = settings.root_dir / creds_path
    token_path = Path(settings.gmail_token_path)
    if not token_path.is_absolute():
        token_path = settings.root_dir / token_path
    return creds_path.exists() or token_path.exists()


def emails_sent_today(db: Session) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(func.count(Outreach.id))
        .filter(
            Outreach.channel == "email",
            Outreach.status == "sent",
            Outreach.sent_at >= start,
        )
        .scalar()
        or 0
    )


def send_email(
    db: Session,
    *,
    to_email: str,
    subject: str,
    body: str,
    contact_id: int,
    dry_run: bool,
    settings: Settings | None = None,
) -> Outreach:
    settings = settings or get_settings()
    outreach = Outreach(
        contact_id=contact_id,
        channel="email",
        subject=subject,
        body=body,
        status="draft",
    )
    db.add(outreach)
    db.flush()

    if dry_run:
        outreach.status = "dry_run"
        outreach.sent_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(outreach)
        logger.info("DRY-RUN email to %s: %s", to_email, subject)
        return outreach

    if emails_sent_today(db) >= settings.email_daily_cap:
        outreach.status = "capped"
        db.commit()
        db.refresh(outreach)
        return outreach

    if not gmail_configured(settings):
        outreach.status = "failed"
        db.commit()
        raise RuntimeError("Gmail is not configured (missing credentials/token)")

    from googleapiclient.discovery import build

    creds = _credentials(settings)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    message = MIMEText(body)
    message["to"] = to_email
    message["subject"] = subject
    if settings.sender_email:
        message["from"] = settings.sender_email
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    sent = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw})
        .execute()
    )
    outreach.gmail_message_id = sent.get("id")
    outreach.gmail_thread_id = sent.get("threadId")
    outreach.status = "sent"
    outreach.sent_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(outreach)
    return outreach
