"""Enrich contacts with email/phone via ZoomInfo; enforce suppression + dedupe."""

from __future__ import annotations

from sqlalchemy.orm import Session

from agent.config import Settings, get_settings
from agent.db import Contact, HoldingCompany, Suppression
from agent.phone_validate import validate_phone
from agent.zoominfo import ZoomInfoClient


def is_suppressed(
    db: Session,
    *,
    email: str | None = None,
    phone: str | None = None,
    contact_id: int | None = None,
    channel: str = "all",
) -> bool:
    q = db.query(Suppression)
    rows = q.all()
    for row in rows:
        if row.channel not in {channel, "all"}:
            continue
        if contact_id and row.contact_id == contact_id:
            return True
        if email and row.email and row.email.lower() == email.lower():
            return True
        if phone and row.phone and row.phone == phone:
            return True
    return False


def enrich_contacts(
    db: Session,
    contacts: list[Contact] | None = None,
    *,
    settings: Settings | None = None,
    zi: ZoomInfoClient | None = None,
) -> list[Contact]:
    settings = settings or get_settings()
    zi = zi or ZoomInfoClient(settings=settings)

    if contacts is None:
        contacts = (
            db.query(Contact)
            .filter(Contact.status.in_(["discovered", "enriched"]))
            .filter(Contact.status != "excluded")
            .all()
        )

    enriched: list[Contact] = []
    for contact in contacts:
        if contact.status == "excluded":
            continue
        if is_suppressed(db, contact_id=contact.id, email=contact.email, phone=contact.phone):
            contact.status = "suppressed"
            continue

        company = contact.holding_company
        country = company.country if company else None

        match = {
            "id": contact.zoominfo_id,
            "firstName": (contact.name.split(" ", 1)[0] if contact.name else None),
            "lastName": (
                contact.name.split(" ", 1)[1] if contact.name and " " in contact.name else None
            ),
            "jobTitle": contact.title,
            "companyName": company.name if company else None,
            "email": contact.email,
            "linkedinUrl": contact.linkedin_url,
        }
        data = zi.enrich_contact(match)
        if data:
            email = data.get("email") or contact.email
            phone_raw = data.get("mobilePhone") or data.get("phone") or contact.phone
            phone_result = validate_phone(phone_raw, country=country)

            if is_suppressed(db, email=email, phone=phone_result.e164, contact_id=contact.id):
                contact.status = "suppressed"
                continue

            contact.email = email
            contact.phone = phone_result.e164 if phone_result.valid else phone_raw
            contact.enrichment_confidence = float(
                data.get("enrichment_confidence")
                or (0.8 if email else 0.4)
            )
            if data.get("id"):
                contact.zoominfo_id = str(data["id"])
            if data.get("linkedinUrl") and not contact.linkedin_url:
                contact.linkedin_url = data["linkedinUrl"]
            contact.status = "enriched"
            enriched.append(contact)

    db.commit()
    return enriched
