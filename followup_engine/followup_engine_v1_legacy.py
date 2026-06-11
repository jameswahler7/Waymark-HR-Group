#!/usr/bin/env python3
import os, sys, json, sqlite3, base64, logging
from datetime import datetime, timedelta
from email.mime.text import MIMEText
import anthropic
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DRY_RUN = "--dry-run" in sys.argv

CONFIG = {
    "label_name": "waymark/cold-outreach",
    "followup1_days": 10,   # Day 10 after sent_date
    "followup2_days": 18,   # Day 18 after sent_date
    "db_path": os.path.join(BASE_DIR, "tracker.db"),
    "token_path": os.path.join(BASE_DIR, "token.json"),
    "credentials_path": os.path.join(BASE_DIR, "credentials.json"),
    "calendar_credentials_path": (
        os.environ.get("GOOGLE_CALENDAR_CREDENTIALS_PATH") or
        os.path.join(BASE_DIR, "calendar_credentials.json")
    ),
    "calendar_token_path": (
        os.environ.get("GOOGLE_CALENDAR_TOKEN_PATH") or
        os.path.join(BASE_DIR, "calendar_token.json")
    ),
    "log_path": os.path.join(BASE_DIR, "logs", "followup_engine.log"),
}

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

SALES_CONTEXT = """
You write follow-up cold emails for Jamie Wahler, SHRM-CP — founder of Waymark HR Group, a fractional HR consulting firm serving small manufacturers in Western New York (Erie and Niagara County).

WHO WE TARGET:
- Owners, Founders, and Presidents of WNY manufacturing companies
- Industries: metal fabrication, food & beverage manufacturing, plastics, industrial machinery, medical devices, electronics manufacturing
- These owners are typically handling HR themselves — no dedicated HR staff

WHO WE DO NOT TARGET:
- Companies with an HR Manager or HR Director already on staff
- Trades, construction, restaurants, dental, landscaping (that was the old target — do not reference these)

VALUE PROPOSITION:
- Jamie is a SHRM-CP certified HR professional with 10 years of real HR experience
- She spent 6 years as Director of HR at a WNY manufacturing company — she understands the shop floor, shift worker classification, OSHA recordkeeping, and manufacturing-specific compliance
- Waymark provides fractional HR: handbooks, compliance audits, I-9s, employee relations, terminations, policy development
- AI-assisted recruiting to cut hiring time without paying a $15,000 recruiter fee
- Far less expensive than a full-time HR hire ($80K–$130K/yr vs a fractional retainer)
- Free 30-minute HR audit: waymarkhrgroup.com

MANUFACTURING PAIN POINTS TO DRAW FROM:
- I-9 paperwork not audited in years — easy compliance exposure
- NY paid leave requirements expanded in 2025 — most manufacturers missed the documentation changes
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

SIGNATURE — always use exactly this format:
Jamie Wahler, SHRM-CP
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

if DRY_RUN:
    log.info("*** DRY-RUN MODE — no emails or calendar events will be created ***")


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
    # Migrate: add columns if they don't exist
    migrations = [
        "followup1_sent_at TEXT",
        "followup2_sent_at TEXT",
        "linkedin_url TEXT",
        "phone TEXT",
        "industry TEXT DEFAULT 'manufacturing'",
        "calendar_events_created INTEGER DEFAULT 0",
    ]
    for col_def in migrations:
        col_name = col_def.split()[0]
        try:
            conn.execute(f"ALTER TABLE prospects ADD COLUMN {col_def}")
            conn.commit()
            log.info(f"Migration: added column '{col_name}'")
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


def get_calendar_service():
    creds_path = CONFIG["calendar_credentials_path"]
    token_path = CONFIG["calendar_token_path"]
    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            f"Calendar credentials not found at {creds_path}. "
            "Set GOOGLE_CALENDAR_CREDENTIALS_PATH in .env."
        )
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, CALENDAR_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, CALENDAR_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


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


def _make_calendar_event(title, description, date_str, duration_minutes, reminder_minutes=30):
    """Build a Google Calendar event body starting at 9 AM on date_str."""
    start_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=9, minute=0, second=0)
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    return {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "America/New_York"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "America/New_York"},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": reminder_minutes}],
        },
    }


def create_calendar_events(conn, cal_service, prospect):
    """Create three touch-point reminders in Google Calendar for a prospect."""
    sent = datetime.strptime(prospect["sent_date"], "%Y-%m-%d")
    first_name = (prospect["prospect_name"] or "").split()[0] if prospect["prospect_name"] else "Contact"
    last_name = " ".join((prospect["prospect_name"] or "").split()[1:]) if prospect["prospect_name"] else ""
    full_name = prospect["prospect_name"] or "Contact"
    company = prospect["company_name"] or "their company"
    linkedin = prospect["linkedin_url"] or ""
    phone = prospect["phone"] or ""

    day3 = (sent + timedelta(days=3)).strftime("%Y-%m-%d")
    day5 = (sent + timedelta(days=5)).strftime("%Y-%m-%d")
    day8 = (sent + timedelta(days=8)).strftime("%Y-%m-%d")

    created = []

    if DRY_RUN:
        log.info(f"[DRY-RUN] Would create calendar events for {full_name} — {company}")
        log.info(f"  Event 1 (Day 3, {day3}): LinkedIn Connect — {full_name}")
        log.info(f"  Event 2 (Day 5, {day5}): LinkedIn Message — {full_name}")
        log.info(f"  Event 3 (Day 8, {day8}): Call — {full_name} | {phone or 'no phone'}")
        return True

    # Event 1 — LinkedIn Connect (Day 3), skip if no linkedin_url
    if linkedin:
        connection_note = (
            f"Hi {first_name} — I'm Jamie with Waymark HR Group in WNY. "
            f"I reached out by email recently. We partner with businesses like {company} "
            f"on fractional HR and compliance. Would love to connect!"
        )
        event1 = _make_calendar_event(
            title=f"LinkedIn: Connect with {full_name} — {company}",
            description=f"Profile: {linkedin}\n\nConnection note:\n{connection_note}",
            date_str=day3,
            duration_minutes=15,
        )
        cal_service.events().insert(calendarId="primary", body=event1).execute()
        created.append("LinkedIn Connect")
        log.info(f"Calendar event created: LinkedIn Connect — {full_name} on {day3}")
    else:
        log.info(f"Skipping LinkedIn Connect event for {full_name} — no linkedin_url")

    # Event 2 — LinkedIn Message (Day 5), skip if no linkedin_url
    if linkedin:
        dm_copy = (
            f"Hi {first_name}, thanks for connecting! Quick context — Waymark HR Group works with WNY "
            f"manufacturers in the 25–100 employee range who need real HR expertise without hiring a "
            f"full-time HR director. We're local, we know WNY, and we're the only firm in the area that "
            f"also helps businesses use AI to hire smarter. I have a free 30-minute HR Audit offer out "
            f"right now — no pitch, just an honest look at where things stand. "
            f"Worth 30 minutes? Happy to work around your schedule."
        )
        event2 = _make_calendar_event(
            title=f"LinkedIn: Message {full_name} — {company}",
            description=f"Profile: {linkedin}\n\nDM copy:\n{dm_copy}",
            date_str=day5,
            duration_minutes=15,
        )
        cal_service.events().insert(calendarId="primary", body=event2).execute()
        created.append("LinkedIn Message")
        log.info(f"Calendar event created: LinkedIn Message — {full_name} on {day5}")
    else:
        log.info(f"Skipping LinkedIn Message event for {full_name} — no linkedin_url")

    # Event 3 — Call (Day 8), always created
    phone_display = phone if phone else "No phone — check LinkedIn"
    opening = (
        f"Hi {first_name}? This is Jamie Wahler from Waymark HR Group here in WNY. "
        f"I sent an email and a LinkedIn message over the past week — do you have 60 seconds?"
    )
    pitch = (
        f"We partner with WNY manufacturers as their fractional HR team — real HR expertise "
        f"without the full-time salary. I wanted to offer a free 30-minute HR Audit — "
        f"no obligation, just an honest look at where your HR stands."
    )
    voicemail = (
        f"Hi {first_name}, this is Jamie Wahler from Waymark HR Group in WNY. "
        f"I'd love to offer a complimentary 30-minute HR Audit — no strings attached. "
        f"(716) 225-6347 or just reply to my email."
    )
    event3 = _make_calendar_event(
        title=f"CALL: {full_name} — {company} — {phone_display}",
        description=(
            f"Phone: {phone_display}\n\n"
            f"Opening: {opening}\n\n"
            f"Pitch: {pitch}\n\n"
            f"Voicemail: {voicemail}"
        ),
        date_str=day8,
        duration_minutes=30,
    )
    cal_service.events().insert(calendarId="primary", body=event3).execute()
    created.append("Call")
    log.info(f"Calendar event created: Call — {full_name} on {day8}")

    # Mark calendar events as created
    conn.execute(
        "UPDATE prospects SET calendar_events_created = 1 WHERE id = ?",
        (prospect["id"],)
    )
    conn.commit()
    log.info(f"calendar_events_created = 1 set for {full_name} — {company} (events: {', '.join(created)})")
    return True


def generate_followup(prospect, followup_num):
    client = anthropic.Anthropic()
    day = CONFIG[f"followup{followup_num}_days"]
    first_name = prospect["prospect_name"].split()[0] if prospect["prospect_name"] else "there"
    company = prospect["company_name"] or "their business"

    if followup_num == 1:
        instruction = f"""Write Follow-Up #1 (Day {day}).

Use the following template as your structure, but personalize it naturally using the prospect's
first name, company name, and any relevant context from the original email thread.
Adapt the language so it reads as if written specifically for this person — not a form letter.

TEMPLATE:
Subject: Re: [original subject]

Hi [First Name],

Following up on my note from last week.

One thing worth knowing for manufacturers in NY right now: the state's paid leave requirements
have expanded again in 2025, and the documentation requirements for employers under 50 employees
often get missed entirely — not because owners are careless, but because nobody told them the
rule changed.

I'm happy to send that one-page checklist I mentioned, or if you'd prefer, I can do a free
30-minute HR audit call where we look at your actual situation. Either way, no obligation.

Jamie Wahler, SHRM-CP
Founder | Waymark HR Group
(716) 225-6347 | waymarkhrgroup.com

PERSONALIZATION NOTES:
- First name: {first_name}
- Company: {company}
- Draw from the original email context to make the pain point feel specific to them
- Keep the body under 80 words (not counting signature)
- Do not add filler openers like "I hope this finds you well"
- Do not change the signature format"""

    else:
        instruction = f"""Write Follow-Up #2 (Day {day}). This is the final email — keep it under 5 sentences.

Use the following template as your structure, personalized with the prospect's name and company.

TEMPLATE:
Subject: Re: Re: [original subject]

Hi [First Name],

I'll keep this brief — this is my last note.

If HR compliance ever becomes a priority — a complaint, an audit, a key employee situation,
or just wanting to make sure your policies are current — I'm a local SHRM-certified HR
professional who has done this work in manufacturing for over a decade.

Free 30-minute audit if you ever want a second set of eyes: waymarkhrgroup.com

Best,
Jamie Wahler, SHRM-CP
Waymark HR Group | (716) 225-6347

PERSONALIZATION NOTES:
- First name: {first_name}
- Company: {company}
- Keep total body under 65 words (not counting signature)
- "Best," goes above the signature on its own line
- Do not add filler openers or closing pleasantries"""

    prompt = f"""{SALES_CONTEXT}

{instruction}

ORIGINAL EMAIL (Day 0):
Subject: {prospect['subject']}
To: {prospect['prospect_name'] or prospect['email_address']}
---
{prospect['original_body']}
---

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


COLS = [
    "id", "gmail_message_id", "prospect_name", "company_name", "email_address",
    "subject", "sent_date", "original_body", "followup1_due", "followup1_draft_id",
    "followup1_created_at", "followup2_due", "followup2_draft_id", "followup2_created_at",
    "status", "followup1_sent_at", "followup2_sent_at",
    "linkedin_url", "phone", "industry", "calendar_events_created",
]


def run():
    log.info("Waymark Follow-Up Engine Starting")
    conn = init_db()
    service = get_gmail_service()
    label_id = get_or_create_label(service, CONFIG["label_name"])
    today_str = datetime.now().date().strftime("%Y-%m-%d")

    # --- Scan Gmail for new labeled sent emails ---
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
        if DRY_RUN:
            log.info(f"[DRY-RUN] Would track: {d['company_name'] or d['email_address']} | FU1 due: {fu1} | FU2 due: {fu2}")
        else:
            conn.execute(
                "INSERT INTO prospects (gmail_message_id, prospect_name, company_name, email_address, "
                "subject, sent_date, original_body, followup1_due, followup2_due) VALUES (?,?,?,?,?,?,?,?,?)",
                (msg_id, d["prospect_name"], d["company_name"], d["email_address"],
                 d["subject"], d["sent_date"], d["body"], fu1, fu2)
            )
            conn.commit()
            log.info(f"Tracked: {d['company_name'] or d['email_address']} | FU1 due: {fu1} | FU2 due: {fu2}")
        new_count += 1
    log.info(f"New prospects tracked: {new_count}")

    # --- Google Calendar: create touch-point events for new prospects ---
    needs_calendar = conn.execute(
        "SELECT * FROM prospects WHERE status = 'active' AND calendar_events_created = 0"
    ).fetchall()
    if needs_calendar:
        log.info(f"Calendar events needed for {len(needs_calendar)} prospect(s)")
        try:
            cal_service = get_calendar_service()
            for row in needs_calendar:
                p = dict(zip(COLS, row))
                try:
                    create_calendar_events(conn, cal_service, p)
                except Exception as cal_err:
                    log.error(f"Calendar event creation failed for {p.get('email_address')}: {cal_err}")
        except Exception as cal_init_err:
            log.error(f"Calendar service unavailable — skipping all calendar events: {cal_init_err}")
    else:
        log.info("No prospects need calendar events")

    # --- Draft Follow-Up #1 (Day 10) ---
    due_fu1 = conn.execute(
        "SELECT * FROM prospects WHERE status = 'active' AND followup1_due <= ? "
        "AND followup1_draft_id IS NULL AND followup1_sent_at IS NULL",
        (today_str,)
    ).fetchall()
    due_fu2 = conn.execute(
        "SELECT * FROM prospects WHERE status = 'active' AND followup2_due <= ? "
        "AND followup1_draft_id IS NOT NULL AND followup2_draft_id IS NULL AND followup2_sent_at IS NULL",
        (today_str,)
    ).fetchall()
    log.info(f"Due today — Day 10 follow-ups: {len(due_fu1)} | Day 18 follow-ups: {len(due_fu2)}")

    for row in due_fu1:
        p = dict(zip(COLS, row))
        log.info(f"Writing Day 10 follow-up for {p['company_name'] or p['email_address']}")
        if DRY_RUN:
            log.info(f"[DRY-RUN] Would generate and draft FU1 for {p['email_address']}")
            continue
        try:
            subject, body = generate_followup(p, followup_num=1)
            draft_id, thread_id = create_draft(service, p["email_address"], subject, body)
            conn.execute(
                "UPDATE prospects SET followup1_draft_id=?, followup1_created_at=? WHERE id=?",
                (draft_id, datetime.now().isoformat(), p["id"])
            )
            conn.commit()
            log.info(f"Draft saved: {subject}")
            try:
                service.users().threads().modify(
                    userId='me', id=thread_id, body={'addLabelIds': ['Label_1']}
                ).execute()
                log.info(f"Label 'waymark/cold-outreach' applied to thread {thread_id}")
            except Exception as label_err:
                log.warning(f"Failed to apply label to thread {thread_id}: {label_err}")
        except Exception as e:
            log.error(f"Failed FU1 for {p['email_address']}: {e}")

    # --- Draft Follow-Up #2 (Day 18) ---
    for row in due_fu2:
        p = dict(zip(COLS, row))
        log.info(f"Writing Day 18 follow-up for {p['company_name'] or p['email_address']}")
        if DRY_RUN:
            log.info(f"[DRY-RUN] Would generate and draft FU2 for {p['email_address']}")
            continue
        try:
            subject, body = generate_followup(p, followup_num=2)
            draft_id, thread_id = create_draft(service, p["email_address"], subject, body)
            conn.execute(
                "UPDATE prospects SET followup2_draft_id=?, followup2_created_at=? WHERE id=?",
                (draft_id, datetime.now().isoformat(), p["id"])
            )
            conn.commit()
            log.info(f"Draft saved: {subject}")
            try:
                service.users().threads().modify(
                    userId='me', id=thread_id, body={'addLabelIds': ['Label_1']}
                ).execute()
                log.info(f"Label 'waymark/cold-outreach' applied to thread {thread_id}")
            except Exception as label_err:
                log.warning(f"Failed to apply label to thread {thread_id}: {label_err}")
        except Exception as e:
            log.error(f"Failed FU2 for {p['email_address']}: {e}")

    conn.close()
    log.info("Engine complete")


if __name__ == "__main__":
    run()
