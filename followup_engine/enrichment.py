"""
enrichment.py — Waymark Cold Email Engine v2

Automated lead enrichment using Anthropic's server-side web_search tool
(the API-equivalent of Claude Code's native web_fetch/web_search). NO external
enrichment services are used — Apollo, Clay, Hunter, Manus are explicitly
forbidden by spec SECTION 6.

The model is asked to:
  1. Fetch the company website (homepage + /about, /services, /careers)
  2. Search Indeed/ZipRecruiter/careers pages for active job postings
  3. Find LinkedIn company page (employee count, founded year)
  4. Find recent (12-month) news mentions
  5. Synthesize ONE structured JSON object with a single best_anchor string
  6. Pick PRIMARY angle = HIRING if any active posting found, else COMPLIANCE

The model also performs the spec's "anchor specificity self-check": would
this anchor be true of any random WNY HVAC shop? If yes, search deeper or
return best_anchor=null so the orchestrator raises EnrichmentError.

Spec reference: SECTION 6.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

import anthropic

from intake_parser import Lead

log = logging.getLogger(__name__)

# Anthropic model — overridable via env. June 2026 default.
ENRICHMENT_MODEL = os.getenv("WAYMARK_ENRICHMENT_MODEL", "claude-sonnet-4-5")

# Web search tool budget: enough to cover 4-6 searches per lead.
MAX_WEB_SEARCHES = 6

# Primary/secondary URLs are fixed per the v2 spec (the skill file's
# May 2026 version is outdated on this point — spec wins).
HIRING_URL     = "hire.waymarkhrgroup.com"
COMPLIANCE_URL = "protect.waymarkhrgroup.com"


class EnrichmentError(Exception):
    """Raised when enrichment cannot produce a usable, specific anchor."""


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are the enrichment module of the Waymark HR Group cold email engine.

Your job: research ONE Western New York blue-collar business and return a
single JSON object describing what you found. Use the web_search tool
liberally — you have a budget of up to 6 searches.

THE TARGET TRADES (this is who Waymark serves):
- WNY manufacturers (metal fab, plastics, food/bev, electronics, machinery)
- WNY construction trades (plumbing, HVAC, electrical, general contracting)
- Employee count 5-100

THE TWO ANGLES THE ENGINE CAN PITCH:
- HIRING angle  -> hire.waymarkhrgroup.com  (AI Hiring Accelerator, $997)
- COMPLIANCE angle -> protect.waymarkhrgroup.com  (Bulletproof Business System, $3,500)

ANGLE PICKER LOGIC YOU MUST RUN:
- If the company has ANY active job posting on Indeed, ZipRecruiter, LinkedIn
  Jobs, or their own /careers page (posted within the last 30 days):
    primary_angle = "hiring"
    secondary_angle = "compliance"
- Otherwise:
    primary_angle = "compliance"
    secondary_angle = "hiring"

YOUR RESEARCH STEPS (run them in this order, use web_search):
1. Fetch the homepage of the company URL provided. Look for: services,
   tagline, years in business, employee count, location confirmation.
2. Search: "{company name} {city} site:indeed.com" -- look for postings
   in the last 30 days. Note the title and how recently posted.
3. Search: "{company name} hiring jobs" -- catches ZipRecruiter, LinkedIn
   Jobs, the company's own careers page.
4. Search: "{company name} {city} linkedin" -- pull employee count range
   and founded year if available.
5. Search: "{company name} news 2026" or "{company name} expansion award" --
   look for press in the last 12 months.

THE BEST ANCHOR (most important field):
Pick the SINGLE most specific real detail about this company to use as
the email hook. Anchor priority (top wins):
  1. Active job posting in last 30 days (e.g., "two open service tech roles on Indeed posted in the last two weeks")
  2. Recent news in last 90 days
  3. Specific year count + trade (e.g., "38 years running HVAC in Buffalo")
  4. Employee count range (e.g., "running a 22-person crew in Buffalo")
  5. Specific service/specialty pulled from the website

SPECIFICITY SELF-CHECK (CRITICAL):
Before finalizing best_anchor, ask: would this exact phrase be true of any
random WNY company in this trade? If yes, it's TOO GENERIC. Search deeper
or set best_anchor to null. Generic anchors lose us replies — that is the
whole problem we are solving.

EXAMPLES:
  TOO GENERIC: "a Buffalo plumbing company"
  TOO GENERIC: "an HVAC business in WNY"
  TOO GENERIC: "a family-owned trade business"
  SPECIFIC:    "two open Service Technician roles on Indeed, posted in the last 10 days"
  SPECIFIC:    "38 years running residential plumbing across Erie County"
  SPECIFIC:    "featured in Buffalo Business First in April 2026 for the downtown hotel project"

OUTPUT FORMAT (CRITICAL):
Return ONE JSON object — no markdown fences, no commentary, no preamble.
The JSON must exactly match this schema:

{
  "first_name": "<from input>",
  "company_name": "<best guess from homepage / domain>",
  "company_url": "<from input>",
  "city": "<e.g. 'Buffalo, NY' — null if unknown>",
  "state": "NY",
  "trade": "<short phrase, e.g. 'plumbing and HVAC' or 'metal fabrication'>",
  "years_in_business": <integer or null>,
  "employee_count_range": "<e.g. '20-50' or null>",
  "active_job_postings": [
    {"title": "...", "source": "Indeed|ZipRecruiter|LinkedIn|company site",
     "posted_days_ago": <integer or null>, "url": "..."}
  ],
  "recent_news": ["<short blurb 1>", "<short blurb 2>"],
  "primary_angle": "hiring" or "compliance",
  "secondary_angle": "compliance" or "hiring",
  "primary_url": "<one of the two fixed URLs>",
  "secondary_url": "<the other fixed URL>",
  "best_anchor": "<single specific sentence — or null if too generic>",
  "specificity_check_passed": true or false,
  "notes_for_engine": "<one short line of context or null>"
}

If you absolutely cannot find anything specific after exhausting your
search budget, set best_anchor to null and specificity_check_passed to false.
The engine will skip the lead — that is the correct outcome.
"""

_USER_TEMPLATE = """\
Research this Waymark cold email lead.

INPUT:
- first_name: {first_name}
- company_url: {company_url}
- recipient_email: {email}

Output the JSON object now.
"""


# ---------------------------------------------------------------------------
# Response handling
# ---------------------------------------------------------------------------

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _strip_text_from_response(resp) -> str:
    """Concatenate all text content blocks from a Messages API response."""
    parts = []
    for block in resp.content or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def _parse_json_object(raw: str) -> dict:
    raw = raw.strip().replace("```json", "").replace("```", "").strip()
    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Fall back: extract the largest {...} block
    m = _JSON_BLOCK_RE.search(raw)
    if not m:
        raise EnrichmentError(f"Enrichment did not return JSON. Got: {raw[:200]!r}")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise EnrichmentError(f"Enrichment JSON failed to parse: {exc}; raw={raw[:200]!r}")


def _ensure_url_pair(enrichment: dict) -> None:
    """Force primary_url / secondary_url to match the v2 spec angle mapping.

    The skill file (May 2026) has both angles pointing to protect.waymarkhrgroup.com;
    the v2 spec (June 2026) splits them. Spec wins per Jamie's confirmation.
    """
    angle = (enrichment.get("primary_angle") or "").lower().strip()
    if angle not in ("hiring", "compliance"):
        # Default to compliance if the model returned something unexpected.
        angle = "compliance"
        enrichment["primary_angle"] = "compliance"
        enrichment["secondary_angle"] = "hiring"

    if angle == "hiring":
        enrichment["primary_url"] = HIRING_URL
        enrichment["secondary_url"] = COMPLIANCE_URL
        enrichment["secondary_angle"] = "compliance"
    else:
        enrichment["primary_url"] = COMPLIANCE_URL
        enrichment["secondary_url"] = HIRING_URL
        enrichment["secondary_angle"] = "hiring"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def enrich_lead(lead: Lead, *, client: Optional[anthropic.Anthropic] = None) -> dict:
    """Run automated enrichment on a Lead and return a validated dict.

    Raises EnrichmentError on:
      * API failure
      * Unparseable JSON
      * best_anchor null/empty or specificity check failed
    """
    client = client or anthropic.Anthropic()

    user_msg = _USER_TEMPLATE.format(
        first_name=lead.first_name,
        company_url=lead.company_url,
        email=lead.email,
    )

    log.info(f"Enriching {lead.email} ({lead.company_url}) with model {ENRICHMENT_MODEL}")

    try:
        resp = client.messages.create(
            model=ENRICHMENT_MODEL,
            max_tokens=2000,
            system=_SYSTEM_PROMPT,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": MAX_WEB_SEARCHES,
            }],
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.APIError as exc:
        raise EnrichmentError(f"Anthropic API error during enrichment: {exc}") from exc

    raw_text = _strip_text_from_response(resp)
    if not raw_text:
        raise EnrichmentError("Enrichment returned no text content")

    enrichment = _parse_json_object(raw_text)

    # Pin URLs to the spec mapping no matter what the model said.
    _ensure_url_pair(enrichment)

    # Ensure first_name and company_url echo what we passed in.
    enrichment["first_name"] = lead.first_name
    enrichment["company_url"] = lead.company_url

    # Specificity gate — spec SECTION 6.
    best = (enrichment.get("best_anchor") or "").strip()
    passed = bool(enrichment.get("specificity_check_passed", True))
    if not best or not passed:
        raise EnrichmentError(
            f"No specific anchor produced for {lead.company_url} "
            f"(best_anchor={best!r}, specificity_check_passed={passed})"
        )

    return enrichment
