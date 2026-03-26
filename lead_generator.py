"""
lead_generator.py — Waymark HR Group LLC
Searches for small manufacturing and construction companies in Erie and Niagara
Counties (NY), generates personalized sales emails via the Anthropic API, and
saves each email as a Gmail draft for Jamie to review before sending.
"""

import os
import base64
import json
import re
import time
from email.mime.text import MIMEText

import requests
from urllib.parse import urlparse
from dotenv import load_dotenv
import anthropic
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_KEY")
HUNTER_KEY = os.getenv("HUNTER_KEY")

CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "token.json")

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

SENDER_NAME = "Jamie Wahler"
SENDER_EMAIL = "jamie.wahler@waymarkhrgroup.com"

COUNTIES = ["Erie County NY", "Niagara County NY"]
INDUSTRIES = ["manufacturing", "construction"]

# SerpAPI returns up to 10 results per page; adjust if you want more pages.
SERPAPI_URL = "https://serpapi.com/search"


# ---------------------------------------------------------------------------
# Gmail authentication
# ---------------------------------------------------------------------------

def get_gmail_service():
    """Authenticate with Gmail and return a service client."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("[Auth] Refreshing Gmail token...")
            creds.refresh(Request())
        else:
            print("[Auth] Opening browser for Gmail authorization...")
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, GMAIL_SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
        print("[Auth] Token saved.")

    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Lead discovery via SerpAPI
# ---------------------------------------------------------------------------

def search_companies(industry: str, county: str) -> list[dict]:
    """
    Search Google for small companies in the given industry and county.
    Returns a list of raw result dicts from SerpAPI's organic_results.
    """
    query = (
        f"{industry} companies {county} small business 1-100 employees"
    )
    print(f"\n[Search] Query: {query}")

    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": 10,
    }

    try:
        response = requests.get(SERPAPI_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        print(f"  [Error] SerpAPI request failed: {exc}")
        return []

    organic = data.get("organic_results", [])
    print(f"  [Search] Found {len(organic)} organic results.")
    return organic


def extract_leads(organic_results: list[dict], industry: str, county: str) -> list[dict]:
    """
    Convert raw SerpAPI results into structured lead dicts.
    Employee count is unknown from search alone, so we label each lead with
    the search context and let Claude make reasonable assumptions.
    """
    leads = []
    for result in organic_results:
        title = result.get("title", "").strip()
        snippet = result.get("snippet", "").strip()
        link = result.get("link", "").strip()

        # Skip results that are clearly directories, news, or job boards
        skip_keywords = [
            "linkedin.com", "indeed.com", "glassdoor.com", "yelp.com",
            "yellowpages.com", "bbb.org", "manta.com", "dnb.com",
            "wikipedia.org", "facebook.com", "twitter.com",
        ]
        if any(kw in link.lower() for kw in skip_keywords):
            continue

        # Attempt a rough employee-count estimate from snippet text
        size_estimate = _estimate_size(snippet)

        leads.append({
            "company_name": _clean_company_name(title),
            "industry": industry,
            "county": county,
            "size_estimate": size_estimate,   # "small" | "medium" | "unknown"
            "snippet": snippet,
            "url": link,
        })

    return leads


def _estimate_size(text: str) -> str:
    """Rough heuristic: look for employee-count numbers in snippet text."""
    text_lower = text.lower()
    # Patterns like "50 employees", "team of 30", "25+ staff"
    match = re.search(r"(\d+)\s*(?:\+\s*)?(?:employees|staff|workers|team members)", text_lower)
    if match:
        count = int(match.group(1))
        if count <= 25:
            return "small"
        if count <= 100:
            return "medium"
        return "large"  # outside target range — still include, Claude will note
    return "unknown"


def _clean_company_name(title: str) -> str:
    """Strip common suffixes from page titles to get a clean company name."""
    for sep in [" | ", " - ", " – ", " — ", ": "]:
        if sep in title:
            title = title.split(sep)[0]
    return title.strip()


def _target_title(size_estimate: str) -> str:
    """
    Return the appropriate title to address based on company size.
    small  (1-24 employees)  → Owner / CEO / President
    medium (25-100 employees) → HR Manager / Office Manager
    unknown                   → default to Owner / CEO / President (conservative)
    """
    if size_estimate == "medium":
        return "HR Manager or Office Manager"
    return "Owner, CEO, or President"


# ---------------------------------------------------------------------------
# Email generation via Anthropic
# ---------------------------------------------------------------------------

def generate_email(lead: dict, client: anthropic.Anthropic) -> str:
    """
    Use Claude to write a short, personalized sales email for the lead.
    Returns the email body as a plain-text string.
    """
    target_title = _target_title(lead["size_estimate"])

    system_prompt = (
        "You are a professional business development writer for Waymark HR Group LLC, "
        "an HR consulting firm based in Western New York. Your emails are warm, concise, "
        "and focused on practical value — not generic pitches. Write in plain text only "
        "(no markdown, no bullet points, no subject line). Output only the email body."
    )

    user_prompt = f"""Write a short, personalized outreach email to the {target_title} at {lead['company_name']},
a {lead['industry']} company in {lead['county']}.

Context about the company (from a web snippet — use what's relevant, ignore what isn't):
{lead['snippet'] or 'No additional context available.'}

Email requirements:
- Friendly, professional tone — as if from a trusted local business neighbor
- 3–4 short paragraphs, no more than 150 words total
- Mention that Waymark HR Group is a Western New York HR firm
- Highlight 1–2 of these services naturally: HR compliance, hiring support, employee handbooks, ongoing HR consulting
- Focus on saving them time and reducing HR headaches — not on features or credentials
- Do NOT use generic openers like "I hope this email finds you well"
- Do NOT include a subject line
- Sign off as:
  Jamie Wahler
  Waymark HR Group LLC
  jamie.wahler@waymarkhrgroup.com"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        messages=[{"role": "user", "content": user_prompt}],
        system=system_prompt,
    )

    return message.content[0].text.strip()


# ---------------------------------------------------------------------------
# Email discovery via Hunter.io
# ---------------------------------------------------------------------------

# Keywords used to rank contacts by title relevance
_SMALL_CO_TITLES = ["owner", "ceo", "president", "founder", "principal"]
_MEDIUM_CO_TITLES = ["hr manager", "human resources manager", "office manager", "hr director"]

HUNTER_DOMAIN_SEARCH_URL = "https://api.hunter.io/v2/domain-search"


def find_email_hunter(lead: dict) -> str:
    """
    Query Hunter.io's domain-search API for the company's website domain and
    return the best-matching contact email, or an empty string if none found.

    Matching priority:
      1. Email whose position matches the preferred titles for this company size
      2. Highest-confidence email among all results (fallback)
    """
    if not HUNTER_KEY:
        return ""

    domain = _extract_domain(lead.get("url", ""))
    if not domain:
        return ""

    try:
        response = requests.get(
            HUNTER_DOMAIN_SEARCH_URL,
            params={"domain": domain, "api_key": HUNTER_KEY},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        print(f"  [Hunter] Request failed: {exc}")
        return ""

    emails = data.get("data", {}).get("emails", [])
    if not emails:
        return ""

    preferred_titles = (
        _MEDIUM_CO_TITLES if lead["size_estimate"] == "medium" else _SMALL_CO_TITLES
    )

    # Try to find a title match (case-insensitive substring)
    for email_obj in emails:
        position = (email_obj.get("position") or "").lower()
        if any(title in position for title in preferred_titles):
            return email_obj.get("value", "")

    # Fallback: highest-confidence result (list comes pre-sorted by Hunter)
    return emails[0].get("value", "")


def _extract_domain(url: str) -> str:
    """Return the bare domain (e.g. 'acme.com') from a full URL."""
    if not url:
        return ""
    parsed = urlparse(url if url.startswith("http") else f"https://{url}")
    # Strip leading 'www.'
    return parsed.netloc.lstrip("www.") or ""


# ---------------------------------------------------------------------------
# Gmail draft creation
# ---------------------------------------------------------------------------

def create_draft(service, to_email: str, subject: str, body: str) -> dict:
    """Create a Gmail draft. to_email can be a placeholder if unknown."""
    mime_message = MIMEText(body, "plain")
    mime_message["to"] = to_email
    mime_message["from"] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    mime_message["subject"] = subject

    raw = base64.urlsafe_b64encode(mime_message.as_bytes()).decode()
    draft = service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}},
    ).execute()
    return draft


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  Waymark HR Group — Lead Generator")
    print("=" * 60)

    # Validate keys
    if not SERPAPI_KEY:
        print("[Fatal] SERPAPI_KEY not found in .env — exiting.")
        return
    if not ANTHROPIC_KEY:
        print("[Fatal] ANTHROPIC_KEY not found in .env — exiting.")
        return
    if not HUNTER_KEY:
        print("[Warn ] HUNTER_KEY not found in .env — email lookup will be skipped.")

    # Initialize clients
    print("\n[Init] Connecting to Gmail...")
    gmail_service = get_gmail_service()
    print("[Init] Gmail ready.")

    print("[Init] Connecting to Anthropic...")
    anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    print("[Init] Anthropic ready.")

    # Collect all leads
    all_leads = []
    for county in COUNTIES:
        for industry in INDUSTRIES:
            results = search_companies(industry, county)
            leads = extract_leads(results, industry, county)
            print(f"  [Parse] Extracted {len(leads)} leads from results.")
            all_leads.extend(leads)
            time.sleep(1)  # polite delay between SerpAPI calls

    # Deduplicate by company name (case-insensitive)
    seen = set()
    unique_leads = []
    for lead in all_leads:
        key = lead["company_name"].lower()
        if key not in seen:
            seen.add(key)
            unique_leads.append(lead)

    print(f"\n[Pipeline] {len(unique_leads)} unique leads to process.")
    print("-" * 60)

    success_count = 0
    failure_count = 0

    for i, lead in enumerate(unique_leads, start=1):
        company = lead["company_name"]
        print(f"\n[{i}/{len(unique_leads)}] Processing: {company}")
        print(f"  Industry : {lead['industry'].title()}")
        print(f"  County   : {lead['county']}")
        print(f"  Size est.: {lead['size_estimate']}")
        print(f"  Target   : {_target_title(lead['size_estimate'])}")

        # Generate email
        try:
            print("  [Claude] Generating email...")
            email_body = generate_email(lead, anthropic_client)
            print("  [Claude] Email generated.")
        except Exception as exc:
            print(f"  [Error] Email generation failed: {exc}")
            failure_count += 1
            continue

        # Look up a contact email via Hunter.io
        print("  [Hunter] Searching for contact email...")
        recipient_email = find_email_hunter(lead)
        if recipient_email:
            print(f"  [Hunter] Email found: {recipient_email}")
        else:
            print("  [Hunter] No email found — draft will have blank To field.")

        # Build subject line
        subject = (
            f"HR Support for {company} — Waymark HR Group"
        )

        # Save as Gmail draft; use discovered email if available.
        try:
            print("  [Gmail] Saving draft...")
            draft = create_draft(gmail_service, recipient_email, subject, email_body)
            draft_id = draft.get("id", "unknown")
            print(f"  [Gmail] Draft saved (ID: {draft_id}).")
            success_count += 1
        except Exception as exc:
            print(f"  [Error] Gmail draft failed: {exc}")
            print(f"  [Info ] Email body was:\n{email_body}\n")
            failure_count += 1
            continue

        # Small delay to stay within API rate limits
        time.sleep(0.5)

    # Summary
    print("\n" + "=" * 60)
    print(f"  Done. {success_count} drafts saved, {failure_count} failed.")
    print("  Open Gmail > Drafts to review and send.")
    print("=" * 60)


if __name__ == "__main__":
    main()
