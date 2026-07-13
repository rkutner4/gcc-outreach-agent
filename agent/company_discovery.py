"""Stage 1: discover holding companies (auto-proceed, no approval gate)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from agent.config import Settings, get_settings
from agent.db import HoldingCompany
from agent.gcc_entities import filter_seed_entities
from agent.query_parser import parse_query
from agent.ranker import rank_companies
from agent.salesnav_import import import_accounts_from_dir
from agent.zoominfo import ZoomInfoClient


def _upsert_company(db: Session, payload: dict[str, Any]) -> HoldingCompany:
    name = payload["name"]
    existing = (
        db.query(HoldingCompany)
        .filter(HoldingCompany.name == name)
        .one_or_none()
    )
    if existing and existing.status == "excluded":
        return existing
    if existing is None:
        existing = HoldingCompany(name=name)
        db.add(existing)
    existing.domain = payload.get("domain") or existing.domain
    existing.zoominfo_id = payload.get("zoominfo_id") or existing.zoominfo_id
    existing.country = payload.get("country") or existing.country
    existing.city = payload.get("city") or existing.city
    existing.entity_type = payload.get("entity_type") or existing.entity_type
    existing.source = payload.get("source") or existing.source
    existing.confidence_score = float(payload.get("confidence_score") or 0)
    if existing.status != "excluded":
        existing.status = "discovered"
    return existing


def discover_companies(
    db: Session,
    query: str,
    *,
    settings: Settings | None = None,
    zi: ZoomInfoClient | None = None,
) -> list[HoldingCompany]:
    settings = settings or get_settings()
    zi = zi or ZoomInfoClient(settings=settings)
    parsed = parse_query(query, settings)
    company_criteria = parsed["company_criteria"]
    countries = company_criteria.get("countries") or list(settings.target_countries)
    entity_types = company_criteria.get("entity_types")

    candidates: list[dict[str, Any]] = []

    # 1) Seed list
    for e in filter_seed_entities(countries=countries, entity_types=entity_types, query=None):
        candidates.append(
            {
                "name": e["name"],
                "domain": e.get("domain"),
                "country": e.get("country"),
                "city": e.get("city"),
                "entity_type": e.get("entity_type"),
                "source": "seed",
                "zoominfo_id": None,
            }
        )

    # 2) ZoomInfo / mock
    zi_filters = {
        "countries": countries,
        "companyName": " ".join(company_criteria.get("keywords") or [])[:80],
        "query": query,
    }
    for row in zi.search_companies(zi_filters):
        candidates.append(
            {
                "name": row.get("name") or row.get("companyName"),
                "domain": row.get("website") or row.get("domain"),
                "country": row.get("country"),
                "city": row.get("city"),
                "entity_type": row.get("entity_type"),
                "source": row.get("source") or "zoominfo",
                "zoominfo_id": str(row.get("id")) if row.get("id") else None,
            }
        )

    # 3) Sales Navigator account CSVs
    for row in import_accounts_from_dir(settings.imports_accounts_dir):
        if row.get("country") and row["country"] not in settings.target_countries:
            continue
        candidates.append(
            {
                "name": row["name"],
                "domain": row.get("domain"),
                "country": row.get("country"),
                "city": row.get("city"),
                "entity_type": "holding",
                "source": "salesnav",
                "zoominfo_id": None,
            }
        )

    # Dedupe by normalized name
    deduped: dict[str, dict[str, Any]] = {}
    for c in candidates:
        if not c.get("name"):
            continue
        key = str(c["name"]).strip().lower()
        if key not in deduped:
            deduped[key] = c
        else:
            # Prefer zoominfo ids / domains when merging
            prev = deduped[key]
            for field in ("domain", "zoominfo_id", "country", "city", "entity_type"):
                if not prev.get(field) and c.get(field):
                    prev[field] = c[field]
            if prev.get("source") == "seed" and c.get("source") != "seed":
                prev["source"] = f"seed+{c['source']}"

    ranked = rank_companies(list(deduped.values()), query, settings)
    threshold = settings.company_confidence_threshold
    saved: list[HoldingCompany] = []
    for row in ranked:
        if float(row.get("confidence_score") or 0) < threshold:
            continue
        # Geography hard filter when known
        if row.get("country") and row["country"] not in settings.target_countries:
            continue
        saved.append(_upsert_company(db, row))
    db.commit()
    for company in saved:
        db.refresh(company)
    return saved
