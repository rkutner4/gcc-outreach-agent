"""Personal WhatsApp session helpers (QR login placeholder + session paths).

Full Baileys/neonize integration can be enabled when the native dependency
is installed. Until then, the sender uses a safe dry-run / draft mode and
stores session material under data/whatsapp_session/.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from agent.config import Settings, get_settings

logger = logging.getLogger(__name__)


def session_dir(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    path = settings.whatsapp_session_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_status_path(settings: Settings | None = None) -> Path:
    return session_dir(settings) / "status.json"


def is_linked(settings: Settings | None = None) -> bool:
    path = session_status_path(settings)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("linked"))
    except Exception:  # noqa: BLE001
        return False


def mark_linked(phone_hint: str = "", settings: Settings | None = None) -> dict:
    """Mark session as linked after user completes QR pairing outside/in-app."""
    payload = {
        "linked": True,
        "phone_hint": phone_hint,
        "linked_at": datetime.now(timezone.utc).isoformat(),
        "backend": "session_file",
        "note": (
            "Personal WhatsApp linked-session marker. Replace with neonize/Baileys "
            "runtime for live sends. Keep dry-run on until verified."
        ),
    }
    path = session_status_path(settings)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Placeholder credentials file (not a real WhatsApp secret)
    (session_dir(settings) / "session.placeholder").write_text(
        "Replace with real multidevice session store when neonize is enabled.\n",
        encoding="utf-8",
    )
    return payload


def unlink(settings: Settings | None = None) -> None:
    path = session_status_path(settings)
    if path.exists():
        path.unlink()


def login_instructions() -> str:
    return (
        "Personal WhatsApp linking:\n"
        "1) Run: python cli.py whatsapp-login\n"
        "2) This writes a local linked-session marker under data/whatsapp_session/.\n"
        "3) For live sending, install/configure neonize (Baileys) and replace the "
        "placeholder session with a real QR multidevice login.\n"
        "4) Keep DRY_RUN=true until a live session is confirmed.\n"
        "Note: unofficial personal WhatsApp automation can violate WhatsApp ToS."
    )
