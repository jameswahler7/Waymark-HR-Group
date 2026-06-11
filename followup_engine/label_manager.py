"""
label_manager.py — Waymark Cold Email Engine v2

Gmail labels ARE the database. This module owns the 11-label taxonomy under
"Waymark Outbound/" and the state transitions between them.

Spec reference: SECTION 4.

Phase 1 uses only:
  - 01_QUEUED
  - 02_SENT_T1
  - 00_DO_NOT_CONTACT (manual)
  - INVALID_INPUT       (validation rejection)
  - INVALID_INPUT_DUPLICATE
  - ENRICHMENT_FAILED
  - GENERATION_FAILED

All other labels are created at first run so Jamie sees the full pipeline
in Gmail immediately, even before T2-T4 logic is built.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

# Top-level parent label name and per-state sublabels.
PARENT = "Waymark Outbound"

LABEL_DO_NOT_CONTACT  = f"{PARENT}/00_DO_NOT_CONTACT"
LABEL_QUEUED          = f"{PARENT}/01_QUEUED"
LABEL_SENT_T1         = f"{PARENT}/02_SENT_T1"
LABEL_SENT_T2         = f"{PARENT}/03_SENT_T2"
LABEL_SENT_T3         = f"{PARENT}/04_SENT_T3"
LABEL_SENT_T4         = f"{PARENT}/05_SENT_T4"
LABEL_REPLIED         = f"{PARENT}/06_REPLIED 🔥"
LABEL_BOOKED          = f"{PARENT}/07_BOOKED"
LABEL_CLOSED_WON      = f"{PARENT}/08_CLOSED_WON"
LABEL_NOT_INTERESTED  = f"{PARENT}/09_NOT_INTERESTED"
LABEL_CLOSED_LOST     = f"{PARENT}/10_CLOSED_LOST"

# Operational labels for engine failure modes (not part of the 00-10 pipeline).
LABEL_INVALID         = f"{PARENT}/INVALID_INPUT"
LABEL_INVALID_DUP     = f"{PARENT}/INVALID_INPUT_DUPLICATE"
LABEL_ENRICH_FAILED   = f"{PARENT}/ENRICHMENT_FAILED"
LABEL_GEN_FAILED      = f"{PARENT}/GENERATION_FAILED"

# Order matters: pipeline labels first (so they sort correctly in Gmail).
ALL_LABELS: List[str] = [
    LABEL_DO_NOT_CONTACT,
    LABEL_QUEUED,
    LABEL_SENT_T1,
    LABEL_SENT_T2,
    LABEL_SENT_T3,
    LABEL_SENT_T4,
    LABEL_REPLIED,
    LABEL_BOOKED,
    LABEL_CLOSED_WON,
    LABEL_NOT_INTERESTED,
    LABEL_CLOSED_LOST,
    LABEL_INVALID,
    LABEL_INVALID_DUP,
    LABEL_ENRICH_FAILED,
    LABEL_GEN_FAILED,
]

# Per-label background color for Gmail's color picker (8-color palette).
LABEL_COLORS: Dict[str, str] = {
    LABEL_DO_NOT_CONTACT: "#cca6ac",   # muted pink — hard exclude
    LABEL_QUEUED:         "#fad165",   # yellow — waiting on engine
    LABEL_SENT_T1:        "#a4c2f4",   # light blue — first touch sent
    LABEL_SENT_T2:        "#6d9eeb",   # blue — second
    LABEL_SENT_T3:        "#3c78d8",   # deeper blue — pivot
    LABEL_SENT_T4:        "#1c4587",   # navy — breakup
    LABEL_REPLIED:        "#fb4c2f",   # red — Jamie's action item
    LABEL_BOOKED:         "#16a765",   # green — booked
    LABEL_CLOSED_WON:     "#076239",   # dark green — won
    LABEL_NOT_INTERESTED: "#cccccc",   # gray
    LABEL_CLOSED_LOST:    "#666666",   # dark gray
    LABEL_INVALID:        "#ffad47",   # orange — needs attention
    LABEL_INVALID_DUP:    "#ffad47",
    LABEL_ENRICH_FAILED:  "#f691b3",
    LABEL_GEN_FAILED:     "#f691b3",
}

# Valid Gmail label background colors (Gmail rejects any color not on this list).
# Source: Gmail API docs. We pre-filter to ensure we never get a 400.
GMAIL_VALID_BG_COLORS = {
    "#000000", "#434343", "#666666", "#999999", "#cccccc", "#efefef", "#f3f3f3", "#ffffff",
    "#fb4c2f", "#ffad47", "#fad165", "#16a765", "#43d692", "#4a86e8", "#a479e2", "#f691b3",
    "#f6c5be", "#ffe6c7", "#fef1d1", "#b9e4d0", "#c6f3de", "#c9daf8", "#e4d7f5", "#fcdee8",
    "#efa093", "#ffd6a2", "#fce8b3", "#89d3b2", "#a0eac9", "#a4c2f4", "#d0bcf1", "#fbc8d9",
    "#e66550", "#ffbc6b", "#fcda83", "#44b984", "#68dfa9", "#6d9eeb", "#b694e8", "#f7a7c0",
    "#cc3a21", "#eaa041", "#f2c960", "#149e60", "#3dc789", "#3c78d8", "#8e63ce", "#e07798",
    "#ac2b16", "#cf8933", "#d5ae49", "#0b804b", "#2a9c68", "#285bac", "#653e9b", "#b65775",
    "#822111", "#a46a21", "#aa8831", "#076239", "#1a764d", "#1c4587", "#41236d", "#83334c",
    "#464646", "#e7e7e7", "#0d3472", "#b6cff5", "#0d3b44", "#98d7e4", "#3d188e", "#e3d7ff",
    "#711a36", "#fbd3e0", "#8a1c0a", "#f2b2a8", "#7a2e0b", "#ffc8af", "#7a4706", "#ffdeb5",
    "#594c05", "#fbe983", "#684e07", "#fdedc1", "#0b4f30", "#b3efd3", "#04502e", "#a2dcc1",
    "#c2c2c2", "#4986e7", "#2da2bb", "#b99aff", "#994a64", "#f691b2", "#ff7537", "#ffad46",
    "#662e37", "#ebdbde", "#cca6ac", "#094228", "#42d692", "#16a765",
}


class LabelManager:
    """Wraps Gmail label CRUD and the state-machine transitions used by the engine."""

    def __init__(self, service):
        self.service = service
        self._ids: Dict[str, str] = {}  # label name -> Gmail label ID
        self._loaded = False

    # ------------------------- label CRUD -----------------------------------

    def _load(self) -> None:
        labels = (
            self.service.users().labels().list(userId="me").execute().get("labels", [])
        )
        self._ids = {lbl["name"]: lbl["id"] for lbl in labels}
        self._loaded = True

    def ensure_labels(self) -> Dict[str, str]:
        """Create any missing Waymark Outbound labels. Returns name->id map."""
        if not self._loaded:
            self._load()

        for name in ALL_LABELS:
            if name in self._ids:
                continue
            color = LABEL_COLORS.get(name)
            body = {
                "name": name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            }
            if color and color in GMAIL_VALID_BG_COLORS:
                body["color"] = {"backgroundColor": color, "textColor": "#ffffff"}
            try:
                created = (
                    self.service.users()
                    .labels()
                    .create(userId="me", body=body)
                    .execute()
                )
                self._ids[name] = created["id"]
                log.info(f"Created label: {name}")
            except Exception as exc:
                log.error(f"Failed to create label '{name}': {exc}")
                raise

        return dict(self._ids)

    def get_id(self, name: str) -> str:
        if name not in self._ids:
            self._load()
        if name not in self._ids:
            raise KeyError(f"Label not found: {name} (run ensure_labels() first)")
        return self._ids[name]

    # ------------------------- thread / draft fetches -----------------------

    def get_queued_drafts(self) -> List[dict]:
        """Return all Gmail drafts that have the 01_QUEUED label applied.

        Drafts are returned as full message dicts (format=full) so callers
        can parse To: header and body without an extra round-trip.
        """
        queued_id = self.get_id(LABEL_QUEUED)
        # Drafts are messages with the DRAFT system label.
        results = (
            self.service.users()
            .messages()
            .list(userId="me", labelIds=[queued_id, "DRAFT"], maxResults=100)
            .execute()
        )
        message_refs = results.get("messages", [])

        out = []
        for ref in message_refs:
            msg = (
                self.service.users()
                .messages()
                .get(userId="me", id=ref["id"], format="full")
                .execute()
            )
            # Find the underlying draft ID — needed for drafts.send.
            draft_id = self._find_draft_id_for_message(msg["id"])
            out.append({
                "message_id": msg["id"],
                "thread_id": msg["threadId"],
                "draft_id": draft_id,
                "raw_message": msg,
            })
        return out

    def get_threads_in_label(self, label_name: str) -> List[str]:
        """Return list of Gmail thread IDs that currently have `label_name`."""
        label_id = self.get_id(label_name)
        thread_ids: List[str] = []
        page_token = None
        while True:
            params = {"userId": "me", "labelIds": [label_id], "maxResults": 500}
            if page_token:
                params["pageToken"] = page_token
            resp = self.service.users().threads().list(**params).execute()
            thread_ids.extend(t["id"] for t in resp.get("threads", []) or [])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return thread_ids

    def _find_draft_id_for_message(self, message_id: str) -> Optional[str]:
        """Drafts API uses its own ID space. Look it up from message_id."""
        drafts = (
            self.service.users()
            .drafts()
            .list(userId="me", maxResults=500)
            .execute()
            .get("drafts", [])
        )
        for d in drafts:
            if d.get("message", {}).get("id") == message_id:
                return d["id"]
        return None

    # ------------------------- state transitions ----------------------------

    def move_thread(self, thread_id: str, from_label: Optional[str], to_label: str) -> None:
        """Remove `from_label` and add `to_label` to the thread.

        If `from_label` is None, just adds `to_label`. Idempotent.
        """
        add_ids = [self.get_id(to_label)]
        remove_ids = [self.get_id(from_label)] if from_label else []
        try:
            self.service.users().threads().modify(
                userId="me",
                id=thread_id,
                body={"addLabelIds": add_ids, "removeLabelIds": remove_ids},
            ).execute()
            log.info(
                f"Thread {thread_id}: {from_label or '(none)'} -> {to_label}"
            )
        except Exception as exc:
            log.error(f"Failed to move thread {thread_id}: {exc}")
            raise
