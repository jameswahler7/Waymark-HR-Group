#!/usr/bin/env python3
import os, json, sqlite3, base64, logging
from datetime import datetime, timedelta
from email.mime.text import MIMEText
import anthropic
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG = {
    "label_name": "waymark/cold-outreach",
    "followup1_days": 6,   # Day 5-7 window — midpoint is 6
    "followup2_days": 13,  # Day 12-14 window — midpoint is 13
    "db_path": os.path.join(BASE_DIR, "tracker.db"),
    "token_path": os.path.join(BASE_DIR, "token.json"),
    "credentials_path": os.path.join(BASE_DIR, "credentials.json"),
    "log_path": os.path.join(BASE_DIR, "logs", "followup_engine.log"),
}
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]
SALES_CONTEXT = """
You write follow-up cold emails for James Wahler, SHRM-CP — founder of Waymark HR Group, a fractional HR consulting firm serving small manufacturers in Western New York (Erie and Niagara County).

WHO WE TARGET:
- Owners, Founders, and Presidents of WNY manufacturing companies
- Company size: 25–100 employees
- Industries: metal fabrication, food & beverage manufacturing, plastics, industrial machinery, medical devices, electronics manufacturing
- These owners are typically handling HR themselves — no dedicated HR staff

WHO WE DO NOT TARGET:
- Companies with an HR Manager or HR Director already on staff
- Trades, construction, restaurants, dental, landscaping (that was the old target — do not reference these)

VALUE PROPOSITION:
- James is a SHRM-CP certified HR professional with 10 years of real HR experience
- He spent 6 years as Director of HR at a WNY manufacturing company — he understands the shop floor, shift worker classification, OSHA recordkeeping, and manufacturing-specific compliance
- Waymark provides fractional HR: handbooks, compliance audits, I-9s, employee relations, terminations, policy development
- AI-assisted recruiting to cut hiring time without paying a $15,000 recruiter fee
- Far less expensive than a full-time HR hire ($80K–$130K/yr vs a fractional retainer)
- Free 30-minute HR audit: https://calendly.com/jamie-wahler-waymarkhrgroup/30min

MANUFACTURING PAIN POINTS TO DRAW FROM:
- I-9 paperwork not audited in years — easy compliance exposure
- NY paid leave requirements expanded in 2025 — most manufacturers under 50 employees missed it
- Outdated or nonexistent employee handbooks
- Undocumented terminations and disciplinary actions — high litigation risk
- Misclassified shift workers or independent contractors
- Owner handling all HR themselves alongside running the operation
- Difficulty finding and retaining skilled manufacturing workers in WNY

FOLLOW-UP RULES:
1. Goal = ONE reply. Not a close. Keep it very short.
2. Never restart the conversation. Reference the original email naturally in one sentence max.
3. Lead with something relevant to their world, then bridge to the ask.
4. Single clear ask — never two asks in one email.
5. Never use the old "ATTENTION:" opener or bold the recipient's name.
6. Never sound apologetic. Confident, direct, conversational.
7. No fluff, no filler phrases like "I hope this finds you well."

TONE: Direct, confident, peer-to-peer. Like one professional writing to another.
LENGTH: Follow-up 1 body under 80 words. Follow-up 2 body under 65 words. Shorter is always better.

SIGNATURE — always use exactly this format:
James Wahler, SHRM-CP
Founder | Waymark HR Group
(716) 225-6347 | waymarkhrgroup.com
"""

os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(CONFIG["log_path"]),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect(CONFIG["db_path"])
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prospects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gmail_message_id TEXT UNIQUE NOT NULL,
            prospect_name TEXT,
            company_name TEXT,
            email_address TEXT NOT NULL,
            subject TEXT,
            sent_date TEXT NOT NULL,
            original_body TEXT,
            followup1_due TEXT,
            followup1_draft_id TEXT,
            followup1_created_at TEXT,
            followup2_due TEXT,
            followup2_draft_id TEXT,
            followup2_created_at TEXT,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.commit()
    # Migrate: add sent_at columns if they don't exist
    for col in ["followup1_sent_at", "followup2_sent_at"]:
        try:
            conn.execute(f"ALTER TABLE prospects ADD COLUMN {col} TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
    return conn

def get_gmail_service():
    creds = None
    if os.path.exists(CONFIG["token_path"]):
        creds = Credentials.from_authorized_user_file(CONFIG["token_path"], GMAIL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CONFIG["credentials_path"], GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(CONFIG["token_path"], "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)

def get_or_create_label(service, label_name):
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for label in labels:
        if label["name"].lower() == label_name.lower():
            return label["id"]
    new_label = service.users().labels().create(
        userId="me",
        body={
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
            "color": {"backgroundColor": "#16a765", "textColor": "#ffffff"}
        }
    ).execute()
    log.info(f"Created Gmail label: {label_name}")
    return new_label["id"]

def get_labeled_sent_emails(service, label_id):
    results = service.users().messages().list(
        userId="me", labelIds=[label_id, "SENT"], q="-in:trash", maxResults=500
    ).execute()
    return results.get("messages", [])

def get_message_details(service, msg_id):
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
    body = ""
    payload = msg["payload"]
    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                data = part["body"].get("data", "")
                body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                break
    elif payload.get("body", {}).get("data"):
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    sent_date = datetime.fromtimestamp(int(msg["internalDate"]) / 1000).strftime("%Y-%m-%d")
    to_header = headers.get("To", "")
    email_address = to_header
    prospect_name = ""
    if "<" in to_header:
        prospect_name = to_header.split("<")[0].strip().strip('"')
        email_address = to_header.split("<")[1].strip(">").strip()
    subject = headers.get("Subject", "")
    company_name = ""
    for pattern in [" for ", " - ", " | "]:
        if pattern.lower() in subject.lower():
            company_name = subject.lower().split(pattern.lower())[-1].strip().title()
            break
    return {
        "message_id": msg_id,
        "subject": subject,
        "email_address": email_address,
        "prospect_name": prospect_name,
        "company_name": company_name,
        "sent_date": sent_date,
        "body": body.strip(),
    }

def create_draft(service, to_email, subject, body):
    message = MIMEText(body, "plain")
    message["to"] = to_email
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    return draft["id"], draft["message"]["threadId"]

def generate_followup(prospect, followup_num):
    client = anthropic.Anthropic()
    day = CONFIG[f"followup{followup_num}_days"]
    if followup_num == 1:
        instruction = f"""Write Follow-Up #1 (Day {day}) — Touch 1 of 2.

This is a short, warm re-engagement. The goal is one reply — not a close.

Structure:
1. One sentence referencing the original email naturally (do not restart the conversation).
2. One relevant manufacturing pain point — pick the most fitting one based on the original email and company details. Examples: NY paid leave documentation, I-9 audit exposure, undocumented termination risk, difficulty finding manufacturing workers.
3. Close with this exact offer: offer to send a one-page checklist of the 5 NY employment law requirements that trip up manufacturers most often — OR if they prefer, a free 30-minute HR audit call at https://calendly.com/jamie-wahler-waymarkhrgroup/30min. Frame both as no obligation.

Body under 80 words, not counting signature. No "Thank you for your time." No filler openers."""
    else:
        instruction = f"""Write Follow-Up #2 (Day {day}) — Touch 2 of 2. This is the final email.

Keep it brief and confident. Give them a graceful exit. Do not push hard.

Structure:
1. One line: this is the last note.
2. One sentence: if HR ever becomes a priority (complaint, audit, employee issue, outdated policies), James is available.
3. Close with the free audit link: https://calendly.com/jamie-wahler-waymarkhrgroup/30min and note the offer stands whenever they're ready.
4. Sign off with "Best," above the signature.

Body under 65 words, not counting signature. No "Thank you for your time." No filler."""

    prompt = f"""{SALES_CONTEXT}

{instruction}

ORIGINAL EMAIL (Day 0):
Subject: {prospect['subject']}
To: {prospect['prospect_name'] or prospect['email_address']}
---
{prospect['original_body']}
---

PROSPECT DETAILS:
First name: {prospect['prospect_name'].split()[0] if prospect['prospect_name'] else 'there'}
Company: {prospect['company_name'] or 'their business'}
Email: {prospect['email_address']}

Return ONLY valid JSON — no markdown, no extra text, no code fences:
{{"subject": "Re: {prospect['subject']}", "body": "Full email body with signature at the end."}}"""

    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    data = json.loads(raw)
    return data["subject"], data["body"]

COLS = ["id","gmail_message_id","prospect_name","company_name","email_address","subject","sent_date","original_body","followup1_due","followup1_draft_id","followup1_created_at","followup2_due","followup2_draft_id","followup2_created_at","status","followup1_sent_at","followup2_sent_at"]

def run():
    log.info("Waymark Follow-Up Engine Starting")
    conn = init_db()
    service = get_gmail_service()
    label_id = get_or_create_label(service, CONFIG["label_name"])
    today_str = datetime.now().date().strftime("%Y-%m-%d")
    log.info("Scanning Gmail for waymark/cold-outreach labeled emails")
    messages = get_labeled_sent_emails(service, label_id)
    new_count = 0
    for msg_ref in messages:
        msg_id = msg_ref["id"]
        if conn.execute("SELECT 1 FROM prospects WHERE gmail_message_id = ?", (msg_id,)).fetchone():
            continue
        d = get_message_details(service, msg_id)
        sent = datetime.strptime(d["sent_date"], "%Y-%m-%d")
        if sent.date() < datetime.strptime("2026-04-19", "%Y-%m-%d").date():
            continue
        fu1 = (sent + timedelta(days=CONFIG["followup1_days"])).strftime("%Y-%m-%d")
        fu2 = (sent + timedelta(days=CONFIG["followup2_days"])).strftime("%Y-%m-%d")
        conn.execute("INSERT INTO prospects (gmail_message_id, prospect_name, company_name, email_address, subject, sent_date, original_body, followup1_due, followup2_due) VALUES (?,?,?,?,?,?,?,?,?)",
            (msg_id, d["prospect_name"], d["company_name"], d["email_address"], d["subject"], d["sent_date"], d["body"], fu1, fu2))
        conn.commit()
        new_count += 1
        log.info(f"Tracked: {d['company_name'] or d['email_address']} | FU1 due: {fu1} | FU2 due: {fu2}")
    log.info(f"New prospects tracked: {new_count}")
    due_fu1 = conn.execute("SELECT * FROM prospects WHERE status = 'active' AND followup1_due <= ? AND followup1_draft_id IS NULL", (today_str,)).fetchall()
    due_fu2 = conn.execute("SELECT * FROM prospects WHERE status = 'active' AND followup2_due <= ? AND followup1_draft_id IS NOT NULL AND followup2_draft_id IS NULL", (today_str,)).fetchall()
    log.info(f"Due today — Day 6 follow-ups: {len(due_fu1)} | Day 13 follow-ups: {len(due_fu2)}")
    for row in due_fu1:
        p = dict(zip(COLS, row))
        if p.get("followup1_draft_id"):
            log.info(f"Skipping {p['email_address']} — draft already exists.")
            continue
        if p.get("followup1_sent_at"):
            log.info(f"Skipping {p['email_address']} — follow-up already sent.")
            continue
        log.info(f"Writing Day 6 follow-up for {p['company_name'] or p['email_address']}")
        try:
            subject, body = generate_followup(p, followup_num=1)
            draft_id, thread_id = create_draft(service, p["email_address"], subject, body)
            conn.execute("UPDATE prospects SET followup1_draft_id=?, followup1_created_at=? WHERE id=?", (draft_id, datetime.now().isoformat(), p["id"]))
            conn.commit()
            log.info(f"Draft saved: {subject}")
            try:
                service.users().threads().modify(
                    userId='me',
                    id=thread_id,
                    body={'addLabelIds': ['Label_1']}
                ).execute()
                log.info(f"Label 'waymark/cold-outreach' applied to thread {thread_id}")
            except Exception as label_err:
                log.warning(f"Failed to apply label to thread {thread_id}: {label_err}")
        except Exception as e:
            log.error(f"Failed: {e}")
    for row in due_fu2:
        p = dict(zip(COLS, row))
        if p.get("followup2_draft_id"):
            log.info(f"Skipping {p['email_address']} — draft already exists.")
            continue
        if p.get("followup2_sent_at"):
            log.info(f"Skipping {p['email_address']} — follow-up already sent.")
            continue
        log.info(f"Writing Day 13 follow-up for {p['company_name'] or p['email_address']}")
        try:
            subject, body = generate_followup(p, followup_num=2)
            draft_id, thread_id = create_draft(service, p["email_address"], subject, body)
            conn.execute("UPDATE prospects SET followup2_draft_id=?, followup2_created_at=? WHERE id=?", (draft_id, datetime.now().isoformat(), p["id"]))
            conn.commit()
            log.info(f"Draft saved: {subject}")
            try:
                service.users().threads().modify(
                    userId='me',
                    id=thread_id,
                    body={'addLabelIds': ['Label_1']}
                ).execute()
                log.info(f"Label 'waymark/cold-outreach' applied to thread {thread_id}")
            except Exception as label_err:
                log.warning(f"Failed to apply label to thread {thread_id}: {label_err}")
        except Exception as e:
            log.error(f"Failed: {e}")
    conn.close()
    log.info("Engine complete")

if __name__ == "__main__":
    run()
