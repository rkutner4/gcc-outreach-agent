"""Identity normalization for contact dedupe and send-once enforcement.

Discovery re-runs from scratch on every pipeline pass, so the same person can
surface repeatedly under different spellings, sources, or queries. These helpers
produce stable keys so duplicate rows collapse and nobody receives a second
"initial" email.
"""

from __future__ import annotations

import re
import unicodedata

# Titles that appear inline in ZoomInfo / Sales Navigator exports.
HONORIFICS = {
    "mr",
    "mrs",
    "ms",
    "miss",
    "dr",
    "prof",
    "professor",
    "eng",
    "engineer",
    "sheikh",
    "shaikh",
    "sh",
    "hh",
    "he",
    "sir",
}

_ANGLE_ADDR_RE = re.compile(r"<([^>]+)>")
_NON_WORD_RE = re.compile(r"[^a-z0-9\s]+")
_REPEATED_CHAR_RE = re.compile(r"(.)\1+")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_email(raw: str | None) -> str | None:
    """Lowercase a display-form or bare address; None if it isn't one.

    Deliberately does not strip dots or ``+tags`` — those are Gmail conventions
    and are significant on the corporate domains this pipeline targets.
    """
    if not raw:
        return None
    text = str(raw).strip()
    match = _ANGLE_ADDR_RE.search(text)
    if match:
        text = match.group(1)
    text = text.strip().strip("<>").lower()
    if text.count("@") != 1:
        return None
    local, _, domain = text.partition("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        return None
    return text


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def name_key(raw: str | None) -> str | None:
    """Order-independent match key for a personal name.

    Folds the variation that actually shows up in GCC contact data: accents,
    hyphenation (``Al-Rashid`` / ``Al Rashid``), doubled consonants
    (``Mohammed`` / ``Mohamed``), honorifics, and ``Last, First`` ordering from
    CSV exports.
    """
    if not raw:
        return None
    text = _strip_accents(str(raw)).lower()
    text = _NON_WORD_RE.sub(" ", text)
    tokens = [t for t in _WHITESPACE_RE.split(text) if t and t not in HONORIFICS]
    tokens = [_REPEATED_CHAR_RE.sub(r"\1", t) for t in tokens]
    if not tokens:
        return None
    return " ".join(sorted(tokens))


def normalize_linkedin(raw: str | None) -> str | None:
    """Reduce a LinkedIn profile URL to a comparable ``in/<slug>`` form."""
    if not raw:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^([a-z]{2,3}\.)?linkedin\.com/", "", text)
    text = text.split("?", 1)[0].rstrip("/")
    return text or None
