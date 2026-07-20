"""Normalization behaviour that the send-once guarantee depends on."""

from __future__ import annotations

import pytest

from agent.identity import name_key, normalize_email, normalize_linkedin


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Person@Example.COM", "person@example.com"),
        ("  person@example.com  ", "person@example.com"),
        ("Ahmed Al-Rashid <A.Rashid@Example.ae>", "a.rashid@example.ae"),
        ("<person@example.com>", "person@example.com"),
        # Corporate domains use dots and plus signs meaningfully — do not fold them.
        ("first.last+gcc@example.com", "first.last+gcc@example.com"),
    ],
)
def test_normalize_email_folds_case_and_display_form(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", None, "not-an-email", "no-domain@", "@no-local.com", "two@at@signs.com", "a@b"],
)
def test_normalize_email_rejects_non_addresses(raw):
    assert normalize_email(raw) is None


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Mohammed Al-Rashid", "Mohamed Al Rashid"),  # doubled letters + hyphenation
        ("Al-Rashid, Mohammed", "Mohammed Al-Rashid"),  # CSV "Last, First" ordering
        ("Dr. Sara Hassan", "Sara Hassan"),  # honorific
        ("Omar  Al-Sabah", "omar al-sabah"),  # whitespace + case
    ],
)
def test_name_key_matches_known_spelling_variants(left, right):
    assert name_key(left) == name_key(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Ahmed Hassan", "Sara Hassan"),
        ("Omar Al-Sabah", "Omar Al-Nahyan"),
    ],
)
def test_name_key_keeps_distinct_people_distinct(left, right):
    assert name_key(left) != name_key(right)


def test_name_key_handles_empty_input():
    assert name_key(None) is None
    assert name_key("  ") is None
    assert name_key("Dr.") is None  # honorific only, nothing left


def test_normalize_linkedin_strips_scheme_subdomain_and_query():
    canonical = "in/someone"
    assert normalize_linkedin("https://www.linkedin.com/in/someone/") == canonical
    assert normalize_linkedin("http://ae.linkedin.com/in/someone?trk=abc") == canonical
    assert normalize_linkedin("linkedin.com/in/someone") == canonical
    assert normalize_linkedin(None) is None
