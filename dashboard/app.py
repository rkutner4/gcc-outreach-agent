"""FastAPI control-plane dashboard (HTMX-friendly HTML)."""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from agent.config import get_settings
from agent.db import (
    Contact,
    HoldingCompany,
    InboundMessage,
    PipelineState,
    get_db,
    init_db,
)

app = FastAPI(title="GCC Outreach Agent", version="0.1.0")

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    state = db.query(PipelineState).first()
    companies = db.query(HoldingCompany).count()
    contacts = db.query(Contact).count()
    unhandled = db.query(InboundMessage).filter(InboundMessage.handled.is_(False)).count()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "settings": settings,
            "state": state,
            "companies": companies,
            "contacts": contacts,
            "unhandled": unhandled,
        },
    )


@app.get("/companies", response_class=HTMLResponse)
def companies_page(request: Request, db: Session = Depends(get_db)):
    rows = (
        db.query(HoldingCompany)
        .order_by(HoldingCompany.confidence_score.desc(), HoldingCompany.name)
        .limit(500)
        .all()
    )
    return templates.TemplateResponse(
        "companies.html", {"request": request, "companies": rows}
    )


@app.get("/contacts", response_class=HTMLResponse)
def contacts_page(request: Request, db: Session = Depends(get_db)):
    rows = (
        db.query(Contact)
        .order_by(Contact.confidence_score.desc(), Contact.name)
        .limit(500)
        .all()
    )
    return templates.TemplateResponse(
        "contacts.html", {"request": request, "contacts": rows}
    )


@app.get("/inbound", response_class=HTMLResponse)
def inbound_page(request: Request, db: Session = Depends(get_db)):
    rows = (
        db.query(InboundMessage)
        .order_by(InboundMessage.received_at.desc())
        .limit(200)
        .all()
    )
    return templates.TemplateResponse(
        "inbound.html", {"request": request, "messages": rows}
    )


@app.post("/controls/pause")
def pause_pipeline(db: Session = Depends(get_db)):
    state = db.query(PipelineState).first()
    if state:
        state.paused = True
        db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/controls/resume")
def resume_pipeline(db: Session = Depends(get_db)):
    state = db.query(PipelineState).first()
    if state:
        state.paused = False
        db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/controls/dry-run")
def set_dry_run(enabled: str = Form("true"), db: Session = Depends(get_db)):
    state = db.query(PipelineState).first()
    if state:
        state.dry_run = enabled.lower() in {"1", "true", "yes", "on"}
        db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/inbound/{message_id}/handled")
def mark_handled(message_id: int, db: Session = Depends(get_db)):
    msg = db.get(InboundMessage, message_id)
    if msg:
        msg.handled = True
        db.commit()
    return RedirectResponse("/inbound", status_code=303)


@app.post("/companies/{company_id}/exclude")
def exclude_company(company_id: int, db: Session = Depends(get_db)):
    company = db.get(HoldingCompany, company_id)
    if company:
        company.status = "excluded"
        db.commit()
    return RedirectResponse("/companies", status_code=303)


@app.post("/contacts/{contact_id}/exclude")
def exclude_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = db.get(Contact, contact_id)
    if contact:
        contact.status = "excluded"
        db.commit()
    return RedirectResponse("/contacts", status_code=303)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    state = db.query(PipelineState).first()
    return {
        "status": "ok",
        "paused": bool(state.paused) if state else False,
        "dry_run": bool(state.dry_run) if state else True,
    }
