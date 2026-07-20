"""Stage 2: find top executives at discovered holding companies."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from agent.config import Settings, get_settings
from agent.db import Contact, HoldingCompany
from agent.identity import name_key, normalize_email, normalize_linkedin
from agent.query_parser import parse_query
from agent.ranker import rank_contacts
from agent.salesnav_import import import_leads_from_dir
from agent.zoominfo import ZoomInfoClient

JUNIOR_BLOCKLIST = ("analyst", "associate", "coordinator", "intern", "assistant", "secretary")


def _is_junior(title: str | None) -> bool:
    t = (title or "").lower()
    return any(k in t for k in JUNIOR_BLOCKLIST)


def _find_existing(
    db: Session,
    company: HoldingCompany | None,
    payload: dict[str, Any],
    name: str,
) -> Contact | None:
    """Resolve a payload to an existing contact, strongest signal first.

    Exact `name` equality is not enough: the same person arrives spelled
    differently across ZoomInfo, Sales Navigator exports, and repeat queries,
    and every unmatched variant becomes another row eligible for a first email.
    """
    email = normalize_email(payload.get("email"))
    if email:
        hit = (
            db.query(Contact)
            .filter(func.lower(Contact.email) == email)
            .order_by(Contact.id)
            .first()
        )
        if hit:
            return hit

    zoom_id = payload.get("zoominfo_id") or payload.get("id")
    if zoom_id:
        hit = (
            db.query(Contact)
            .filter(Contact.zoominfo_id == str(zoom_id))
            .order_by(Contact.id)
            .first()
        )
        if hit:
            return hit

    linkedin = normalize_linkedin(payload.get("linkedin_url") or payload.get("linkedinUrl"))
    if linkedin:
        for cand in db.query(Contact).filter(Contact.linkedin_url.isnot(None)).all():
            if normalize_linkedin(cand.linkedin_url) == linkedin:
                return cand

    # Fall back to a normalized name match, scoped to the company so unrelated
    # people who normalize alike are never merged.
    key = name_key(name)
    if key:
        q = db.query(Contact)
        q = q.filter(Contact.holding_company_id == company.id) if company else q
        for cand in q.order_by(Contact.id).all():
            if name_key(cand.name) == key:
                return cand
    return None


def _upsert_contact(
    db: Session,
    company: HoldingCompany | None,
    payload: dict[str, Any],
) -> Contact | None:
    name = payload.get("name")
    if not name:
        first = payload.get("firstName") or payload.get("first_name")
        last = payload.get("lastName") or payload.get("last_name")
        name = " ".join(p for p in [first, last] if p)
    if not name:
        return None
    title = payload.get("title") or payload.get("jobTitle")
    if _is_junior(title):
        return None

    existing = _find_existing(db, company, payload, name)
    if existing and existing.status == "excluded":
        return existing
    if existing is None:
        existing = Contact(name=name)
        db.add(existing)

    zoom_id = payload.get("zoominfo_id") or payload.get("id")
    existing.holding_company_id = company.id if company else existing.holding_company_id
    existing.title = title or existing.title
    existing.linkedin_url = payload.get("linkedin_url") or payload.get("linkedinUrl") or existing.linkedin_url
    existing.zoominfo_id = str(zoom_id) if zoom_id else existing.zoominfo_id
    existing.email = normalize_email(payload.get("email")) or existing.email
    existing.phone = payload.get("phone") or payload.get("mobilePhone") or existing.phone
    score = payload.get("confidence_score")
    if score is not None:
        # Previously reset to 0 whenever a re-discovery payload omitted the score.
        existing.confidence_score = float(score)
    existing.source = payload.get("source") or existing.source or "zoominfo"
    # Never walk a terminal status backwards — re-discovery used to reset an
    # already-contacted person to "discovered", making them eligible again.
    if existing.status not in {"excluded", "suppressed", "contacted"}:
        existing.status = "discovered"
    return existing


def discover_contacts(
    db: Session,
    query: str,
    *,
    settings: Settings | None = None,
    zi: ZoomInfoClient | None = None,
    company_ids: list[int] | None = None,
) -> list[Contact]:
    settings = settings or get_settings()
    zi = zi or ZoomInfoClient(settings=settings)
    parsed = parse_query(query, settings)
    titles = parsed["contact_criteria"].get("titles") or []

    q = db.query(HoldingCompany).filter(HoldingCompany.status != "excluded")
    if company_ids:
        q = q.filter(HoldingCompany.id.in_(company_ids))
    else:
        q = q.filter(HoldingCompany.confidence_score >= settings.company_confidence_threshold)
    companies = q.all()

    candidates: list[tuple[HoldingCompany | None, dict[str, Any]]] = []

    for company in companies:
        filters = {
            "companyId": company.zoominfo_id,
            "companyName": company.name,
            "jobTitle": titles,
            "titles": titles,
        }
        for row in zi.search_contacts(filters):
            row = {**row, "company_name": company.name, "source": row.get("source") or "zoominfo"}
            candidates.append((company, row))

    # Optional Sales Navigator lead CSVs
    by_company_name = {c.name.lower(): c for c in companies}
    for lead in import_leads_from_dir(settings.imports_leads_dir):
        company = None
        cname = (lead.get("company_name") or "").lower()
        if cname:
            company = by_company_name.get(cname)
            if company is None:
                # fuzzy contains
                for name, co in by_company_name.items():
                    if cname in name or name in cname:
                        company = co
                        break
        candidates.append((company, lead))

    flat = []
    for company, row in candidates:
        name = row.get("name")
        if not name:
            name = " ".join(
                p
                for p in [
                    row.get("firstName") or row.get("first_name"),
                    row.get("lastName") or row.get("last_name"),
                ]
                if p
            )
        flat.append(
            {
                **row,
                "name": name,
                "title": row.get("title") or row.get("jobTitle"),
                "company_name": (company.name if company else row.get("company_name")),
            }
        )

    ranked = rank_contacts(flat, query, settings)
    threshold = settings.contact_confidence_threshold
    saved: list[Contact] = []
    # Re-associate company by name for ranked rows
    for row in ranked:
        if float(row.get("confidence_score") or 0) < threshold:
            continue
        company = None
        cname = (row.get("company_name") or "").lower()
        if cname:
            company = by_company_name.get(cname)
            if company is None:
                for name, co in by_company_name.items():
                    if cname in name or name in cname:
                        company = co
                        break
        contact = _upsert_contact(db, company, row)
        if contact:
            saved.append(contact)
    db.commit()
    for contact in saved:
        db.refresh(contact)
    return saved
