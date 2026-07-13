"""LLM / heuristic ranking for companies and contacts."""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _token_overlap_score(text: str, query: str) -> float:
    q_tokens = {t.lower() for t in query.split() if len(t) > 3}
    if not q_tokens:
        return 0.5
    hay = text.lower()
    hits = sum(1 for t in q_tokens if t in hay)
    return min(1.0, 0.35 + (hits / max(len(q_tokens), 1)) * 0.65)


def _heuristic_company_score(company: dict[str, Any], query: str) -> dict[str, Any]:
    text = " ".join(
        str(company.get(k) or "")
        for k in ("name", "short_name", "country", "city", "entity_type", "domain")
    )
    score = _token_overlap_score(text, query)
    # Boost known SWF / holding labels
    et = str(company.get("entity_type") or "").lower()
    if et in {"swf", "holding"}:
        score = min(1.0, score + 0.15)
    if company.get("country") in {"UAE", "KSA", "Kuwait", "Bahrain"}:
        score = min(1.0, score + 0.1)
    return {
        "confidence": round(score, 3),
        "reasoning": "Heuristic overlap with query + GCC entity boosts",
    }


def _heuristic_contact_score(contact: dict[str, Any], query: str) -> dict[str, Any]:
    text = " ".join(
        str(contact.get(k) or "")
        for k in ("name", "title", "company_name", "jobTitle")
    )
    score = _token_overlap_score(text, query)
    title = str(contact.get("title") or contact.get("jobTitle") or "").lower()
    senior_keywords = [
        "cio",
        "chief investment",
        "managing director",
        "head of",
        "ceo",
        "chairman",
        "portfolio",
    ]
    if any(k in title for k in senior_keywords):
        score = min(1.0, score + 0.25)
    junior = ["analyst", "associate", "coordinator", "intern", "assistant"]
    if any(k in title for k in junior):
        score = min(score, 0.2)
    return {
        "confidence": round(score, 3),
        "reasoning": "Heuristic title seniority + query overlap",
    }


def _llm_score_batch(
    kind: str,
    items: list[dict[str, Any]],
    query: str,
    settings: Settings,
) -> list[dict[str, Any]] | None:
    if not (settings.llm_provider == "openai" and settings.openai_api_key):
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        payload = {
            "kind": kind,
            "query": query,
            "items": items[:25],
        }
        prompt = (
            "Score each item 0-1 for fit to the prospecting query for GCC institutional wealth. "
            "Return JSON {\"scores\":[{\"index\":0,\"confidence\":0.0,\"reasoning\":\"...\"}]}. "
            f"Data: {json.dumps(payload)}"
        )
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        return data.get("scores")
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM ranker failed, using heuristics: %s", exc)
        return None


def rank_companies(
    companies: list[dict[str, Any]],
    query: str,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    llm_scores = _llm_score_batch("company", companies, query, settings)
    ranked = []
    for i, company in enumerate(companies):
        if llm_scores:
            match = next((s for s in llm_scores if s.get("index") == i), None)
            if match:
                company = {
                    **company,
                    "confidence_score": float(match.get("confidence", 0)),
                    "rank_reasoning": match.get("reasoning", ""),
                }
                ranked.append(company)
                continue
        scored = _heuristic_company_score(company, query)
        ranked.append(
            {
                **company,
                "confidence_score": scored["confidence"],
                "rank_reasoning": scored["reasoning"],
            }
        )
    ranked.sort(key=lambda c: c.get("confidence_score", 0), reverse=True)
    return ranked


def rank_contacts(
    contacts: list[dict[str, Any]],
    query: str,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    llm_scores = _llm_score_batch("contact", contacts, query, settings)
    ranked = []
    for i, contact in enumerate(contacts):
        if llm_scores:
            match = next((s for s in llm_scores if s.get("index") == i), None)
            if match:
                contact = {
                    **contact,
                    "confidence_score": float(match.get("confidence", 0)),
                    "rank_reasoning": match.get("reasoning", ""),
                }
                ranked.append(contact)
                continue
        scored = _heuristic_contact_score(contact, query)
        ranked.append(
            {
                **contact,
                "confidence_score": scored["confidence"],
                "rank_reasoning": scored["reasoning"],
            }
        )
    ranked.sort(key=lambda c: c.get("confidence_score", 0), reverse=True)
    return ranked
