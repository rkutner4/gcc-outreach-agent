"""Compose business-casual emails and personal WhatsApp messages."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from agent.config import Settings, get_settings
from agent.db import Contact, HoldingCompany

logger = logging.getLogger(__name__)


@dataclass
class ComposedMessage:
    channel: str
    subject: str | None
    body: str


def _load_style(settings: Settings, name: str) -> str:
    path = settings.templates_dir / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _first_name(contact: Contact) -> str:
    return (contact.name or "there").split(" ", 1)[0]


def _company_name(contact: Contact) -> str:
    if contact.holding_company:
        return contact.holding_company.name
    return "your firm"


def _heuristic_email(contact: Contact, settings: Settings) -> ComposedMessage:
    first = _first_name(contact)
    company = _company_name(contact)
    title = contact.title or "your role"
    subject = f"Quick intro — {settings.sender_firm} & {company}"
    body = f"""Hi {first},

I hope this finds you well. Given your role as {title} at {company}, I wanted to reach out — {settings.outreach_pitch}

No pressure at all — happy to share a bit more context if useful. Would a brief call sometime this week make sense?

Best,
{settings.sender_name}
{settings.sender_firm}
{settings.mailing_address}
"""
    return ComposedMessage("email", subject, body.strip() + "\n")


def _heuristic_whatsapp(contact: Contact, settings: Settings) -> ComposedMessage:
    first = _first_name(contact)
    company = _company_name(contact)
    body = (
        f"Hi {first}, hope you're well. Came across your work at {company} and wanted to "
        f"reach out personally — {settings.outreach_pitch} Happy to share more if useful. "
        f"Best, {settings.sender_name}"
    )
    return ComposedMessage("whatsapp", None, body)


def _llm_compose(
    channel: str,
    contact: Contact,
    settings: Settings,
    style: str,
) -> ComposedMessage | None:
    if not (settings.llm_provider == "openai" and settings.openai_api_key):
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        payload = {
            "channel": channel,
            "contact": {
                "name": contact.name,
                "title": contact.title,
                "company": _company_name(contact),
                "country": contact.holding_company.country if contact.holding_company else None,
            },
            "sender": {
                "name": settings.sender_name,
                "firm": settings.sender_firm,
                "pitch": settings.outreach_pitch,
                "mailing_address": settings.mailing_address,
            },
            "style_guide": style,
        }
        prompt = (
            "Write one outreach message. Return JSON with keys subject (email only, else null) "
            "and body. Follow the style guide strictly. Do not invent facts.\n"
            f"{json.dumps(payload)}"
        )
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.5,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        body = data.get("body")
        if not body:
            return None
        subject = data.get("subject") if channel == "email" else None
        if channel == "email" and settings.mailing_address not in body:
            body = body.rstrip() + "\n" + settings.mailing_address
        return ComposedMessage(channel, subject, body.strip())
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM compose failed (%s): %s", channel, exc)
        return None


def compose_email(contact: Contact, settings: Settings | None = None) -> ComposedMessage:
    settings = settings or get_settings()
    style = _load_style(settings, "outreach_email_style.txt")
    return _llm_compose("email", contact, settings, style) or _heuristic_email(contact, settings)


def compose_whatsapp(contact: Contact, settings: Settings | None = None) -> ComposedMessage:
    settings = settings or get_settings()
    style = _load_style(settings, "outreach_whatsapp_style.txt")
    return _llm_compose("whatsapp", contact, settings, style) or _heuristic_whatsapp(
        contact, settings
    )
