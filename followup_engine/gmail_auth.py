"""
gmail_auth.py — Waymark Cold Email Engine v2

Shared Gmail OAuth helper. Uses the same credentials.json / token.json
already present in the followup_engine directory.

Scopes:
  - gmail.readonly  — read drafts, threads, labels, messages
  - gmail.modify    — apply/remove labels, send messages (modify covers send)
  - gmail.compose   — create drafts (intake reads existing drafts)

gmail.modify is sufficient for users.drafts.send and users.messages.send,
so no new OAuth scope is required compared to the v1 legacy engine.
"""
from __future__ import annotations

import os
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]


def get_gmail_service(base_dir: Optional[str] = None):
    """Authenticate with Gmail and return a service client.

    Reuses the existing credentials.json / token.json in the followup_engine
    directory. If the saved token's scopes don't cover GMAIL_SCOPES the user
    will be prompted to re-authorize in a browser.
    """
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    creds_path = os.path.join(base_dir, "credentials.json")
    token_path = os.path.join(base_dir, "token.json")

    creds = None
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, GMAIL_SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def get_sender_address(service) -> str:
    """Return the authenticated user's email address."""
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")
