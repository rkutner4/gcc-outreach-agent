"""Gmail OAuth helper behaviour (no live network calls)."""

from __future__ import annotations

from agent.gmail_sender import SCOPES, gmail_status, login_instructions


def test_gmail_status_reports_missing_files(tmp_path, monkeypatch):
    creds = tmp_path / "credentials" / "gmail_client_secret.json"
    token = tmp_path / "credentials" / "gmail_token.json"

    class FakeSettings:
        gmail_credentials_path = str(creds)
        gmail_token_path = str(token)
        sender_email = "sender@example.com"
        root_dir = tmp_path

    status = gmail_status(FakeSettings())
    assert status["client_secret_exists"] is False
    assert status["token_exists"] is False
    assert status["configured"] is False
    assert status["sender_email"] == "sender@example.com"


def test_login_instructions_mention_paths(tmp_path):
    creds = tmp_path / "credentials" / "gmail_client_secret.json"
    token = tmp_path / "credentials" / "gmail_token.json"

    class FakeSettings:
        gmail_credentials_path = str(creds)
        gmail_token_path = str(token)
        sender_email = ""
        root_dir = tmp_path

    text = login_instructions(FakeSettings())
    assert str(creds) in text
    assert str(token) in text
    assert "gmail-login" in text


def test_scopes_include_send_and_readonly():
    assert "https://www.googleapis.com/auth/gmail.send" in SCOPES
    assert "https://www.googleapis.com/auth/gmail.readonly" in SCOPES
