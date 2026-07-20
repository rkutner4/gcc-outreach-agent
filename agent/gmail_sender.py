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
from agent.identity import normalize_email

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def resolve_gmail_paths(settings: Settings) -> tuple[Path, Path]:
    creds_path = Path(settings.gmail_credentials_path)
    if not creds_path.is_absolute():
        creds_path = settings.root_dir / creds_path
    token_path = Path(settings.gmail_token_path)
    if not token_path.is_absolute():
        token_path = settings.root_dir / token_path
    return creds_path, token_path


def login_instructions(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    creds_path, token_path = resolve_gmail_paths(settings)
    return (
        "Gmail OAuth setup:\n"
        "1) Google Cloud Console → create/select a project → enable Gmail API.\n"
        "2) OAuth consent screen → External → add your Google account as a test user.\n"
        "3) Credentials → Create OAuth client ID → Desktop app → download JSON.\n"
        f"4) Save the JSON as: {creds_path}\n"
        f"5) Set SENDER_EMAIL in .env to the mailbox you will send from.\n"
        "6) Run: python cli.py gmail-login\n"
        "   (opens a browser; approves gmail.send + gmail.readonly scopes)\n"
        f"7) Token is written to: {token_path}\n"
        "8) Keep DRY_RUN=true until a test prospect looks right, then disable dry-run "
        "in the dashboard or set DRY_RUN=false in .env.\n"
        "Note: both credential files stay gitignored — never commit them."
    )


def authorize_gmail(settings: Settings | None = None):
    """Load or obtain Gmail OAuth credentials; persists refresh token locally."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    settings = settings or get_settings()
    creds_path, token_path = resolve_gmail_paths(settings)

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
                    "Run `python cli.py gmail-login` after placing OAuth client JSON."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def gmail_status(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    creds_path, token_path = resolve_gmail_paths(settings)
    return {
        "client_secret_path": str(creds_path),
        "token_path": str(token_path),
        "client_secret_exists": creds_path.exists(),
        "token_exists": token_path.exists(),
        "configured": creds_path.exists() or token_path.exists(),
        "sender_email": settings.sender_email or None,
        "scopes": list(SCOPES),
    }


def verify_gmail_account(settings: Settings | None = None) -> dict:
    """Confirm OAuth works and return the authorized mailbox address."""
    from googleapiclient.discovery import build

    settings = settings or get_settings()
    creds = authorize_gmail(settings)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    return {
        "email_address": profile.get("emailAddress"),
        "messages_total": profile.get("messagesTotal"),
        "threads_total": profile.get("threadsTotal"),
    }


def gmail_configured(settings: Settings | None = None) -> bool:
    return gmail_status(settings)["configured"]


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


def already_emailed(db: Session, email: str | None) -> bool:
    """True if this address has ever received a real send.

    Keyed on the address rather than the contact row: re-discovery routinely
    produces a second row for the same person, and that row is exactly what
    would otherwise earn them a second "initial" email. Dry runs do not count —
    nothing left the building.
    """
    normalized = normalize_email(email)
    if not normalized:
        return False
    return (
        db.query(Outreach.id)
        .filter(
            Outreach.channel == "email",
            Outreach.status == "sent",
            func.lower(Outreach.to_email) == normalized,
        )
        .first()
        is not None
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
        to_email=normalize_email(to_email) or to_email,
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

    creds = authorize_gmail(settings)
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
