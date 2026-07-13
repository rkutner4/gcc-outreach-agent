"""Pipeline orchestration for prospecting runs (Stage 1 + Stage 2)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from agent.company_discovery import discover_companies
from agent.config import get_settings
from agent.contact_discovery import discover_contacts
from agent.db import PipelineState, get_session_factory, init_db


def _get_state(db: Session) -> PipelineState:
    state = db.query(PipelineState).first()
    if state is None:
        settings = get_settings()
        state = PipelineState(paused=False, dry_run=settings.dry_run)
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def run_prospect(query: str, *, db: Session | None = None) -> dict:
    """Discover companies then contacts. Auto-proceeds; respects pause flag."""
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

        state.last_run_at = datetime.now(timezone.utc)
        state.last_run_status = "ok"
        state.last_run_message = (
            f"query={query!r} companies={len(companies)} contacts={len(contacts)}"
        )
        db.commit()
        return {
            "ok": True,
            "query": query,
            "companies": len(companies),
            "contacts": len(contacts),
            "dry_run": state.dry_run,
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
