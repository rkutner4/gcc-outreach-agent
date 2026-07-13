"""Parse natural-language prospecting targets into structured filters."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from agent.config import Settings, get_settings

logger = logging.getLogger(__name__)

DEFAULT_TITLES = [
    "Chief Investment Officer",
    "CIO",
    "CEO",
    "Managing Director",
    "Head of Investments",
    "Head of Alternatives",
    "Head of Private Markets",
    "Head of Public Markets",
    "Head of Real Assets",
    "Executive Director",
    "Portfolio Director",
    "Chairman",
]

DEFAULT_COUNTRIES = ["UAE", "KSA", "Kuwait", "Bahrain"]


def _heuristic_parse(query: str) -> dict[str, Any]:
    q = query.lower()
    countries = []
    if "uae" in q or "abu dhabi" in q or "dubai" in q or "emirates" in q:
        countries.append("UAE")
    if "ksa" in q or "saudi" in q or "riyadh" in q:
        countries.append("KSA")
    if "kuwait" in q:
        countries.append("Kuwait")
    if "bahrain" in q or "manama" in q:
        countries.append("Bahrain")
    if not countries:
        countries = list(DEFAULT_COUNTRIES)

    entity_types = []
    if "sovereign" in q or "swf" in q:
        entity_types.append("swf")
    if "family office" in q:
        entity_types.append("family_office")
    if "asset manager" in q or "institutional" in q:
        entity_types.append("institutional")
    if "holding" in q:
        entity_types.append("holding")
    if not entity_types:
        entity_types = ["swf", "holding", "institutional"]

    titles = []
    title_map = {
        "cio": "Chief Investment Officer",
        "chief investment": "Chief Investment Officer",
        "ceo": "CEO",
        "managing director": "Managing Director",
        "head of alternatives": "Head of Alternatives",
        "head of private markets": "Head of Private Markets",
        "head of investments": "Head of Investments",
        "chairman": "Chairman",
    }
    for key, title in title_map.items():
        if key in q:
            titles.append(title)
    if not titles:
        titles = list(DEFAULT_TITLES)

    return {
        "company_criteria": {
            "countries": countries,
            "entity_types": entity_types,
            "keywords": re.findall(r"[a-zA-Z]{4,}", query)[:12],
            "raw_query": query,
        },
        "contact_criteria": {
            "titles": titles,
            "seniority": ["c_suite", "vp", "director"],
            "raw_query": query,
        },
    }


def _llm_parse(query: str, settings: Settings) -> dict[str, Any] | None:
    if settings.llm_provider == "openai" and settings.openai_api_key:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=settings.openai_api_key)
            prompt = (
                "Split this GCC institutional wealth prospecting request into JSON with keys "
                "company_criteria and contact_criteria. "
                "company_criteria: countries (subset of UAE,KSA,Kuwait,Bahrain), entity_types "
                "(swf|holding|institutional|family_office), keywords (list). "
                "contact_criteria: titles (list of senior investment roles), seniority (list). "
                f"Request: {query}"
            )
            resp = client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            content = resp.choices[0].message.content or "{}"
            return json.loads(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM query parse failed, falling back to heuristics: %s", exc)
            return None
    return None


def parse_query(query: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    parsed = _llm_parse(query, settings) or _heuristic_parse(query)
    # Enforce geography hard-limit
    countries = parsed.get("company_criteria", {}).get("countries") or DEFAULT_COUNTRIES
    parsed.setdefault("company_criteria", {})["countries"] = [
        c for c in countries if c in DEFAULT_COUNTRIES
    ] or list(DEFAULT_COUNTRIES)
    parsed.setdefault("contact_criteria", {})
    parsed["contact_criteria"].setdefault("titles", list(DEFAULT_TITLES))
    parsed["company_criteria"]["raw_query"] = query
    parsed["contact_criteria"]["raw_query"] = query
    return parsed
