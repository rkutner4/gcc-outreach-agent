"""Load and query the GCC holding company seed list."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from agent.config import get_settings

ALLOWED_COUNTRIES = {"UAE", "KSA", "Kuwait", "Bahrain"}


@lru_cache
def _seed_path() -> Path:
    return get_settings().data_dir / "gcc_holding_companies.yaml"


@lru_cache
def load_seed_entities() -> list[dict[str, Any]]:
    path = _seed_path()
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entities = raw.get("entities", [])
    return [
        e
        for e in entities
        if str(e.get("country", "")).upper() in {c.upper() for c in ALLOWED_COUNTRIES}
        or e.get("country") in ALLOWED_COUNTRIES
    ]


def filter_seed_entities(
    *,
    countries: list[str] | None = None,
    entity_types: list[str] | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    rows = load_seed_entities()
    if countries:
        allowed = {c.upper() for c in countries}
        rows = [r for r in rows if str(r.get("country", "")).upper() in allowed]
    if entity_types:
        allowed_types = {t.lower() for t in entity_types}
        rows = [r for r in rows if str(r.get("entity_type", "")).lower() in allowed_types]
    if query:
        q = query.lower()
        filtered = []
        for r in rows:
            hay = " ".join(
                [
                    str(r.get("name", "")),
                    str(r.get("short_name", "")),
                    str(r.get("city", "")),
                    str(r.get("country", "")),
                    " ".join(r.get("aliases") or []),
                ]
            ).lower()
            if q in hay:
                filtered.append(r)
        rows = filtered
    return rows
