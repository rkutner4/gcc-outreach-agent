"""Sales Navigator CSV import — data only, no LinkedIn automation."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable


ACCOUNT_NAME_KEYS = (
    "Company",
    "Company Name",
    "Account Name",
    "Organization",
    "Name",
)
ACCOUNT_DOMAIN_KEYS = ("Website", "Domain", "Company Domain", "Company Website")
ACCOUNT_GEO_KEYS = ("Location", "Headquarters", "HQ Location", "Company Location")

LEAD_NAME_KEYS = ("First Name", "Last Name", "Full Name", "Name")
LEAD_TITLE_KEYS = ("Title", "Job Title", "Position")
LEAD_COMPANY_KEYS = ("Company", "Company Name", "Account Name")
LEAD_LINKEDIN_KEYS = ("LinkedIn URL", "Profile URL", "Person Linkedin Url", "URL")
LEAD_EMAIL_KEYS = ("Email", "Email Address", "Work Email")


def _pick(row: dict[str, str], keys: Iterable[str]) -> str | None:
    lower_map = {k.lower().strip(): v for k, v in row.items() if k}
    for key in keys:
        val = lower_map.get(key.lower())
        if val and str(val).strip():
            return str(val).strip()
    return None


def _normalize_header_row(row: dict[str, str | None]) -> dict[str, str]:
    return {str(k).strip(): (v or "").strip() for k, v in row.items() if k}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [_normalize_header_row(row) for row in reader]


def parse_account_row(row: dict[str, str]) -> dict[str, Any] | None:
    name = _pick(row, ACCOUNT_NAME_KEYS)
    if not name:
        return None
    location = _pick(row, ACCOUNT_GEO_KEYS) or ""
    country = None
    city = None
    loc_l = location.lower()
    if "abu dhabi" in loc_l or "dubai" in loc_l or "united arab" in loc_l or "uae" in loc_l:
        country = "UAE"
        if "abu dhabi" in loc_l:
            city = "Abu Dhabi"
        elif "dubai" in loc_l:
            city = "Dubai"
    elif "saudi" in loc_l or "riyadh" in loc_l or "ksa" in loc_l:
        country = "KSA"
    elif "kuwait" in loc_l:
        country = "Kuwait"
    elif "bahrain" in loc_l or "manama" in loc_l:
        country = "Bahrain"

    return {
        "name": name,
        "domain": _pick(row, ACCOUNT_DOMAIN_KEYS),
        "country": country,
        "city": city,
        "source": "salesnav",
        "raw_location": location,
    }


def parse_lead_row(row: dict[str, str]) -> dict[str, Any] | None:
    full = _pick(row, ("Full Name", "Name"))
    first = _pick(row, ("First Name",))
    last = _pick(row, ("Last Name",))
    if full:
        name = full
    elif first or last:
        name = " ".join(p for p in [first, last] if p)
    else:
        return None

    return {
        "name": name,
        "first_name": first,
        "last_name": last,
        "title": _pick(row, LEAD_TITLE_KEYS),
        "company_name": _pick(row, LEAD_COMPANY_KEYS),
        "linkedin_url": _pick(row, LEAD_LINKEDIN_KEYS),
        "email": _pick(row, LEAD_EMAIL_KEYS),
        "source": "salesnav",
    }


def import_accounts_from_dir(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    results: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.csv")):
        for row in read_csv_rows(path):
            parsed = parse_account_row(row)
            if parsed:
                parsed["import_file"] = path.name
                results.append(parsed)
    return results


def import_leads_from_dir(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    results: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.csv")):
        for row in read_csv_rows(path):
            parsed = parse_lead_row(row)
            if parsed:
                parsed["import_file"] = path.name
                results.append(parsed)
    return results
