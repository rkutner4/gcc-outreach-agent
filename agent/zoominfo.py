"""ZoomInfo GTM API client (OAuth + company/contact search + enrich).

Works in mock mode when credentials are missing so the pipeline can be
developed and dry-run without live API access.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.config import Settings, get_settings
from agent.gcc_entities import load_seed_entities

logger = logging.getLogger(__name__)

AUTH_URL = "https://api.zoominfo.com/authenticate"
BASE_URL = "https://api.zoominfo.com"


@dataclass
class ZoomInfoClient:
    settings: Settings = field(default_factory=get_settings)
    _token: str | None = None

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.zoominfo_client_id
            and self.settings.zoominfo_client_secret
            and self.settings.zoominfo_username
            and self.settings.zoominfo_password
        )

    def _headers(self) -> dict[str, str]:
        if not self._token:
            self.authenticate()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def authenticate(self) -> str:
        if not self.configured:
            raise RuntimeError("ZoomInfo credentials are not configured")
        payload = {
            "username": self.settings.zoominfo_username,
            "password": self.settings.zoominfo_password,
        }
        # Some ZoomInfo setups also require client id/secret via basic auth or body.
        payload["client_id"] = self.settings.zoominfo_client_id
        payload["client_secret"] = self.settings.zoominfo_client_secret
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(AUTH_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
        token = data.get("jwt") or data.get("access_token") or data.get("token")
        if not token:
            raise RuntimeError(f"ZoomInfo auth succeeded but no token found: {data}")
        self._token = token
        return token

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def search_companies(self, filters: dict[str, Any], *, page: int = 1) -> list[dict[str, Any]]:
        if not self.configured:
            return self._mock_company_search(filters)
        body = {"page": page, **filters}
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(
                f"{BASE_URL}/search/company",
                headers=self._headers(),
                json=body,
            )
            if resp.status_code == 401:
                self._token = None
                resp = client.post(
                    f"{BASE_URL}/search/company",
                    headers=self._headers(),
                    json=body,
                )
            resp.raise_for_status()
            data = resp.json()
        return data.get("data") or data.get("companies") or []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def search_contacts(self, filters: dict[str, Any], *, page: int = 1) -> list[dict[str, Any]]:
        if not self.configured:
            return self._mock_contact_search(filters)
        body = {"page": page, **filters}
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(
                f"{BASE_URL}/search/contact",
                headers=self._headers(),
                json=body,
            )
            if resp.status_code == 401:
                self._token = None
                resp = client.post(
                    f"{BASE_URL}/search/contact",
                    headers=self._headers(),
                    json=body,
                )
            resp.raise_for_status()
            data = resp.json()
        return data.get("data") or data.get("contacts") or []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def enrich_contact(self, match: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            return self._mock_enrich(match)
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(
                f"{BASE_URL}/enrich/contact",
                headers=self._headers(),
                json={"matchPersonInput": [match], "outputFields": [
                    "id",
                    "firstName",
                    "lastName",
                    "email",
                    "phone",
                    "mobilePhone",
                    "jobTitle",
                    "companyName",
                    "externalUrls",
                ]},
            )
            if resp.status_code == 401:
                self._token = None
                resp = client.post(
                    f"{BASE_URL}/enrich/contact",
                    headers=self._headers(),
                    json={"matchPersonInput": [match]},
                )
            resp.raise_for_status()
            data = resp.json()
        results = data.get("data") or data.get("result") or []
        return results[0] if results else {}

    def _mock_company_search(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        logger.info("ZoomInfo not configured — using seed list mock company search")
        q = (filters.get("companyName") or filters.get("query") or "").lower()
        countries = filters.get("countries") or []
        rows = []
        for e in load_seed_entities():
            if countries and e.get("country") not in countries:
                continue
            if q and q not in str(e.get("name", "")).lower() and q not in str(e.get("short_name", "")).lower():
                # still include all seed entities when query is a broad NL phrase
                if len(q) < 40:
                    continue
            rows.append(
                {
                    "id": f"mock-{e.get('short_name') or e.get('name')}",
                    "name": e.get("name"),
                    "website": e.get("domain"),
                    "country": e.get("country"),
                    "city": e.get("city"),
                    "entity_type": e.get("entity_type"),
                    "source": "zoominfo_mock",
                }
            )
        return rows

    def _mock_contact_search(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        logger.info("ZoomInfo not configured — using mock contact search")
        company_name = filters.get("companyName") or filters.get("company_name") or "Holding Company"
        titles = filters.get("jobTitle") or filters.get("titles") or [
            "Chief Investment Officer",
            "Managing Director",
            "Head of Alternatives",
        ]
        if isinstance(titles, str):
            titles = [titles]
        company_id = filters.get("companyId") or filters.get("company_id") or "mock-co"
        contacts = []
        for i, title in enumerate(titles[:5]):
            first = ["Ahmed", "Sara", "Omar", "Layla", "Khalid"][i % 5]
            last = ["Al-Rashid", "Hassan", "Al-Sabah", "Mansoor", "Al-Nahyan"][i % 5]
            contacts.append(
                {
                    "id": f"mock-contact-{company_id}-{i}",
                    "firstName": first,
                    "lastName": last,
                    "jobTitle": title,
                    "companyName": company_name,
                    "companyId": company_id,
                    "email": None,
                    "phone": None,
                    "linkedinUrl": None,
                    "source": "zoominfo_mock",
                }
            )
        return contacts

    def _mock_enrich(self, match: dict[str, Any]) -> dict[str, Any]:
        first = match.get("firstName") or "Alex"
        last = match.get("lastName") or "Contact"
        company = (match.get("companyName") or "firm").lower().replace(" ", "")[:20]
        return {
            "id": match.get("id") or f"mock-{first}-{last}",
            "firstName": first,
            "lastName": last,
            "jobTitle": match.get("jobTitle"),
            "companyName": match.get("companyName"),
            "email": f"{first}.{last}@{company or 'example'}.com".lower(),
            "phone": "+971500000000",
            "mobilePhone": "+971500000000",
            "linkedinUrl": match.get("linkedinUrl"),
            "enrichment_confidence": 0.55,
            "source": "zoominfo_mock",
        }
