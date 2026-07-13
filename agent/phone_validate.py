"""GCC phone format validation via phonenumbers (+ optional KhaleejiAPI)."""

from __future__ import annotations

from dataclasses import dataclass

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat

from agent.config import get_settings

REGION_HINTS = {
    "UAE": "AE",
    "KSA": "SA",
    "Kuwait": "KW",
    "Bahrain": "BH",
}


@dataclass
class PhoneValidation:
    valid: bool
    e164: str | None
    region: str | None
    reason: str = ""


def validate_phone(raw: str | None, *, country: str | None = None) -> PhoneValidation:
    if not raw or not str(raw).strip():
        return PhoneValidation(False, None, None, "empty")
    region = REGION_HINTS.get(country or "", None)
    try:
        parsed = phonenumbers.parse(str(raw).strip(), region)
    except NumberParseException as exc:
        return PhoneValidation(False, None, None, str(exc))

    if not phonenumbers.is_possible_number(parsed):
        return PhoneValidation(False, None, None, "not_possible")
    if not phonenumbers.is_valid_number(parsed):
        return PhoneValidation(False, None, region, "invalid")

    e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    region_code = phonenumbers.region_code_for_number(parsed)

    # Optional remote validation
    settings = get_settings()
    if settings.khaleeji_api_key:
        try:
            import httpx

            resp = httpx.get(
                "https://khaleejiapi.dev/api/v1/phone/validate",
                params={"phone": e164},
                headers={"Authorization": f"Bearer {settings.khaleeji_api_key}"},
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("valid") is False:
                    return PhoneValidation(False, e164, region_code, "khaleeji_invalid")
        except Exception:  # noqa: BLE001
            pass

    return PhoneValidation(True, e164, region_code, "ok")
