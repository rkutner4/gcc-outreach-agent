"""The core guarantee: nobody ever receives a second initial email."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agent import pipeline
from agent.db import Base, Contact, Outreach
from agent.gmail_sender import already_emailed
from agent.outreach_compose import ComposedMessage


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _contact(db, name, email):
    contact = Contact(name=name, email=email, status="enriched")
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def _record_sent(db, contact, email, status="sent"):
    db.add(
        Outreach(
            contact_id=contact.id,
            channel="email",
            to_email=email,
            subject="Introduction",
            body="...",
            status=status,
        )
    )
    db.commit()


def _stub_message(contact, settings):
    return ComposedMessage(channel="email", subject="Introduction", body="hello")


@pytest.fixture
def captured(monkeypatch):
    """Replace the real sender; record every address it is asked to mail."""
    calls = []

    def fake_send_email(db, *, to_email, subject, body, contact_id, dry_run, settings=None):
        calls.append(to_email)
        outreach = Outreach(
            contact_id=contact_id,
            channel="email",
            to_email=to_email,
            subject=subject,
            body=body,
            status="dry_run" if dry_run else "sent",
        )
        db.add(outreach)
        db.flush()
        return outreach

    monkeypatch.setattr(pipeline, "send_email", fake_send_email)
    monkeypatch.setattr(pipeline, "compose_email", _stub_message)
    return calls


def test_duplicate_contact_rows_receive_one_email(db, captured):
    """The same person discovered twice under different spellings."""
    _contact(db, "Mohammed Al-Rashid", "m.alrashid@example.ae")
    _contact(db, "Mohamed Al Rashid", "m.alrashid@example.ae")

    stats = pipeline.send_outreach_for_contacts(db, db.query(Contact).all(), dry_run=False)

    assert captured == ["m.alrashid@example.ae"]
    assert stats["emailed"] == 1
    assert stats["already_contacted"] == 1


def test_case_variant_addresses_are_the_same_person(db, captured):
    _contact(db, "Sara Hassan", "S.Hassan@Example.com")
    _contact(db, "Sara Hassan", "s.hassan@example.com")

    pipeline.send_outreach_for_contacts(db, db.query(Contact).all(), dry_run=False)

    assert captured == ["s.hassan@example.com"]


def test_previously_emailed_address_is_never_re_emailed(db, captured):
    """A prior run's send must survive into later runs."""
    old = _contact(db, "Omar Al-Sabah", "omar@example.kw")
    _record_sent(db, old, "omar@example.kw")

    # Re-discovered later as a fresh row — the exact scenario the guard exists for.
    _contact(db, "Omar Al Sabah", "omar@example.kw")

    stats = pipeline.send_outreach_for_contacts(db, db.query(Contact).all(), dry_run=False)

    assert captured == []
    assert stats["already_contacted"] == 2


def test_dry_run_does_not_consume_the_one_send(db, captured):
    contact = _contact(db, "Layla Mansoor", "layla@example.bh")
    _record_sent(db, contact, "layla@example.bh", status="dry_run")

    pipeline.send_outreach_for_contacts(db, [contact], dry_run=False)

    assert captured == ["layla@example.bh"]


def test_dry_run_previews_deduplication(db, captured):
    """A rehearsal should report what a live run would actually do."""
    _contact(db, "Khalid Al-Nahyan", "khalid@example.ae")
    _contact(db, "Khalid Al Nahyan", "khalid@example.ae")

    stats = pipeline.send_outreach_for_contacts(db, db.query(Contact).all(), dry_run=False)

    assert stats["emailed"] == 1
    assert stats["already_contacted"] == 1


def test_failed_send_stays_retryable(db, monkeypatch):
    """Failures previously marked the contact contacted, so they never retried."""
    contact = _contact(db, "Ahmed Hassan", "ahmed@example.sa")

    def boom(*args, **kwargs):
        raise RuntimeError("gmail down")

    monkeypatch.setattr(pipeline, "send_email", boom)
    monkeypatch.setattr(pipeline, "compose_email", _stub_message)

    stats = pipeline.send_outreach_for_contacts(db, [contact], dry_run=False)

    assert stats["emailed"] == 0
    assert len(stats["errors"]) == 1
    assert contact.status == "enriched"


def test_unparseable_address_is_reported_not_sent(db, captured):
    contact = _contact(db, "Broken Record", "not-an-email")

    stats = pipeline.send_outreach_for_contacts(db, [contact], dry_run=False)

    assert captured == []
    assert len(stats["errors"]) == 1


def test_already_emailed_is_case_insensitive(db):
    contact = _contact(db, "Sara Hassan", "s.hassan@example.com")
    _record_sent(db, contact, "s.hassan@example.com")

    assert already_emailed(db, "S.Hassan@Example.COM") is True
    assert already_emailed(db, "someone.else@example.com") is False
    assert already_emailed(db, None) is False
