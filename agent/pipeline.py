"""Pipeline orchestration for prospecting + auto outreach."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from agent.company_discovery import discover_companies
from agent.config import get_settings
from agent.contact_discovery import discover_contacts
from agent.db import Contact, PipelineState, get_session_factory, init_db
from agent.enrich import enrich_contacts, is_suppressed
from agent.gmail_sender import already_emailed, send_email
from agent.identity import normalize_email
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
    already = 0
    capped = 0
    errors: list[str] = []
    # Guards against duplicate contact rows for the same person colliding within
    # a single run, before any of them has been committed as sent.
    seen_emails: set[str] = set()

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

        sent_any = False
        failed_any = False

        if contact.email:
            normalized = normalize_email(contact.email)
            if not normalized:
                errors.append(f"email:{contact.id}:unparseable address {contact.email!r}")
                failed_any = True
            elif normalized in seen_emails or already_emailed(db, normalized):
                # This person has had their one message. Nothing further is ever sent.
                seen_emails.add(normalized)
                already += 1
            else:
                try:
                    msg = compose_email(contact, settings)
                    outreach = send_email(
                        db,
                        to_email=normalized,
                        subject=msg.subject or "Introduction",
                        body=msg.body,
                        contact_id=contact.id,
                        dry_run=dry_run,
                        settings=settings,
                    )
                    if outreach.status in {"sent", "dry_run"}:
                        # Claimed in dry-run too, so a rehearsal previews the real run.
                        seen_emails.add(normalized)
                        emailed += 1
                        sent_any = True
                    elif outreach.status == "capped":
                        capped += 1
                    else:
                        failed_any = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"email:{contact.id}:{exc}")
                    failed_any = True

        if contact.phone:
            try:
                msg = compose_whatsapp(contact, settings)
                outreach = send_whatsapp(
                    db,
                    phone=contact.phone,
                    body=msg.body,
                    contact_id=contact.id,
                    dry_run=dry_run,
                    settings=settings,
                    sleep=not dry_run,
                )
                if outreach.status in {"sent", "dry_run"}:
                    whatsapped += 1
                    sent_any = True
                elif outreach.status == "capped":
                    capped += 1
                else:
                    failed_any = True
            except Exception as exc:  # noqa: BLE001
                errors.append(f"whatsapp:{contact.id}:{exc}")
                failed_any = True

        if sent_any and not dry_run:
            contact.status = "contacted"
        elif failed_any:
            # Leave retryable — previously any contact with an address was marked
            # contacted even when every send raised, so failures were never retried.
            contact.status = "enriched"

    db.commit()
    return {
        "emailed": emailed,
        "whatsapped": whatsapped,
        "skipped": skipped,
        "already_contacted": already,
        "capped": capped,
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

        send_stats = {
            "emailed": 0,
            "whatsapped": 0,
            "skipped": 0,
            "already_contacted": 0,
            "capped": 0,
            "errors": [],
        }
        if send:
            send_stats = send_outreach_for_contacts(
                db, enriched or contacts, dry_run=bool(state.dry_run)
            )

        state.last_run_at = datetime.now(timezone.utc)
        state.last_run_status = "ok"
        state.last_run_message = (
            f"query={query!r} companies={len(companies)} contacts={len(contacts)} "
            f"enriched={len(enriched)} emailed={send_stats['emailed']} "
            f"already_contacted={send_stats['already_contacted']} "
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
