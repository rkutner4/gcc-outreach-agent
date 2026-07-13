"""Pipeline orchestration for prospecting + auto outreach."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from agent.company_discovery import discover_companies
from agent.config import get_settings
from agent.contact_discovery import discover_contacts
from agent.db import Contact, PipelineState, get_session_factory, init_db
from agent.enrich import enrich_contacts, is_suppressed
from agent.gmail_sender import send_email
from agent.outreach_compose import compose_email, compose_whatsapp
from agent.whatsapp_sender import send_whatsapp


def _get_state(db: Session) -> PipelineState:
    state = db.query(PipelineState).first()
    if state is None:
        settings = get_settings()
        state = PipelineState(paused=False, dry_run=settings.dry_run)
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def send_outreach_for_contacts(
    db: Session,
    contacts: list[Contact],
    *,
    dry_run: bool,
) -> dict:
    settings = get_settings()
    emailed = 0
    whatsapped = 0
    skipped = 0
    errors: list[str] = []

    for contact in contacts:
        if contact.status in {"excluded", "suppressed"}:
            skipped += 1
            continue
        if is_suppressed(
            db,
            contact_id=contact.id,
            email=contact.email,
            phone=contact.phone,
        ):
            contact.status = "suppressed"
            skipped += 1
            continue

        if contact.email:
            try:
                msg = compose_email(contact, settings)
                send_email(
                    db,
                    to_email=contact.email,
                    subject=msg.subject or "Introduction",
                    body=msg.body,
                    contact_id=contact.id,
                    dry_run=dry_run,
                    settings=settings,
                )
                emailed += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"email:{contact.id}:{exc}")

        if contact.phone:
            try:
                msg = compose_whatsapp(contact, settings)
                send_whatsapp(
                    db,
                    phone=contact.phone,
                    body=msg.body,
                    contact_id=contact.id,
                    dry_run=dry_run,
                    settings=settings,
                    sleep=not dry_run,
                )
                whatsapped += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"whatsapp:{contact.id}:{exc}")

        if contact.email or contact.phone:
            contact.status = "contacted" if not dry_run else "enriched"

    db.commit()
    return {
        "emailed": emailed,
        "whatsapped": whatsapped,
        "skipped": skipped,
        "errors": errors,
    }


def run_prospect(query: str, *, db: Session | None = None, send: bool = True) -> dict:
    """Discover companies → contacts → enrich → compose/send (respects dry-run/pause)."""
    init_db()
    own_session = db is None
    if own_session:
        SessionLocal = get_session_factory()
        db = SessionLocal()
    assert db is not None
    try:
        state = _get_state(db)
        if state.paused:
            return {
                "ok": False,
                "error": "Pipeline is paused",
                "companies": 0,
                "contacts": 0,
            }

        companies = discover_companies(db, query)
        contacts = discover_contacts(db, query)
        enriched = enrich_contacts(db, contacts)

        send_stats = {"emailed": 0, "whatsapped": 0, "skipped": 0, "errors": []}
        if send:
            send_stats = send_outreach_for_contacts(
                db, enriched or contacts, dry_run=bool(state.dry_run)
            )

        state.last_run_at = datetime.now(timezone.utc)
        state.last_run_status = "ok"
        state.last_run_message = (
            f"query={query!r} companies={len(companies)} contacts={len(contacts)} "
            f"enriched={len(enriched)} emailed={send_stats['emailed']} "
            f"whatsapp={send_stats['whatsapped']} dry_run={state.dry_run}"
        )
        db.commit()
        return {
            "ok": True,
            "query": query,
            "companies": len(companies),
            "contacts": len(contacts),
            "enriched": len(enriched),
            "dry_run": state.dry_run,
            "send": send_stats,
            "message": state.last_run_message,
        }
    except Exception as exc:  # noqa: BLE001
        state = _get_state(db)
        state.last_run_at = datetime.now(timezone.utc)
        state.last_run_status = "error"
        state.last_run_message = str(exc)
        db.commit()
        raise
    finally:
        if own_session:
            db.close()
