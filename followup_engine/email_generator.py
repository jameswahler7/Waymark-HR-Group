"""
email_generator.py — Waymark Cold Email Engine v2

Generates ONE outbound email at a time using the Anthropic API. The skill
file (WAYMARK_COLD_EMAIL_SKILL.md) is loaded from disk and passed VERBATIM
as the system prompt, followed by a v2 spec appendix that overrides the
skill file's outdated 3-touch sequence with the 4-touch logic.

Phase 1 only generates Touch 1 emails. Touches 2-4 are intentionally not
wired in this module yet (the function signature accepts touch_number but
Phase 1 hard-pins it to 1).

Post-generation validation (spec SECTION 7):
  * JSON parse check
  * Body word count within touch range
  * Banned word / banned phrase scan
  * Link presence check (T1: zero links; T2-T4: correct URL present)
  * Up to 2 regeneration attempts on validation failure

Spec reference: SECTION 7.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional, Tuple

import anthropic

log = logging.getLogger(__name__)

GENERATION_MODEL = os.getenv("WAYMARK_GENERATION_MODEL", "claude-sonnet-4-5")
MAX_REGEN_ATTEMPTS = 2  # spec: 2 retries before labeling GENERATION_FAILED

# Word count ranges per touch (body only, signature and PS excluded).
WORD_COUNT_RANGES = {
    1: (80, 130),
    2: (60, 100),
    3: (80, 110),
    4: (60, 90),
}

# Canonical PS line for follow-up touches (T2/T3/T4). T1 keeps the scarcity/
# slots formulas from the skill file (real scarcity reads as honest on a cold
# open; on a follow-up, proof of work outperforms scarcity).
#
# This line is FORCED after generation -- whatever PS the model writes for
# T2/T3/T4 is stripped and replaced with this exact string.
T234_PS_LINE = (
    "P.S. Last WNY shop I audited had 3 handbook gaps that would've cost "
    "$50K+ to defend. They had no idea."
)

# Retired PS copy. The model should not regenerate any variant of these.
# Scanned against the FULL body (including the PS line itself).
RETIRED_PS_PATTERNS = [
    (
        re.compile(r"i work with\s+\S+\s+wny shops", re.IGNORECASE),
        "retired PS: 'I work with [X] WNY shops'",
    ),
    (
        re.compile(r"capacity for one more this month", re.IGNORECASE),
        "retired PS: 'capacity for one more this month'",
    ),
]

# Matches a trailing "blank-line + P.S. ..." block at the end of a body.
# Used to swap the model-written PS for the canonical T2/T3/T4 PS line.
_TRAILING_PS_RE = re.compile(
    r"\n\s*\n\s*p\.?\s*s\.?\b.*$",
    re.IGNORECASE | re.DOTALL,
)

# Spec SECTION 3 + skill file PART 3.
BANNED_WORDS = {
    "scale", "double", "triple", "guarantee", "risk-free", "passive income",
    "game-changer", "game changer", "revolutionary", "cutting-edge", "cutting edge",
    "synergy", "leverage", "skyrocket", "explode", "crush", "dominate",
    "partnership", "opportunity", "exciting",
}

BANNED_PHRASES = [
    "i hope this email finds you well",
    "i hope this finds you well",
    "i came across your company",
    "i'd love to connect",
    "i would love to connect",
    "quick 15 minutes",
    "quick 15-minute",
    "circling back",
    "just following up",
    "touching base",
    "checking in",
]

_LINK_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


class GenerationError(Exception):
    """Raised when email generation cannot produce a valid email after retries."""


# ---------------------------------------------------------------------------
# System prompt assembly
# ---------------------------------------------------------------------------

_V2_APPENDIX = """\
========================================================================
WAYMARK v2 ENGINE APPENDIX — overrides any conflicting rule in the skill above
========================================================================

You are generating ONE email for the Waymark HR Group cold outreach engine.

The skill above describes a 3-touch sequence. THIS ENGINE USES 4 TOUCHES.
Use the skill for ALL content rules (subject, hook, value, CTA, PS, banned
words, formatting, personalization) but apply these per-touch overrides:

TOUCH 1 (Day 0) — First contact.
  * CTA: reply-generating question only.
  * ZERO LINKS. Do NOT paste any URL anywhere in the body.
  * Use the PRIMARY angle for this lead.
  * 80-130 words body.

TOUCH 2 (+3 biz days) — Soft follow-up.
  * Subject: "re: {original T1 subject}"
  * Lighter tone. Reinforce primary angle from a slightly different angle.
  * INCLUDE the primary URL as a plain text line: "Worth a look? -> {primary_url}"
  * 60-100 words body.

TOUCH 3 (+5 biz days from T2) — THE PIVOT.
  * Subject: "quick thought, {first_name}" or "{company} / {secondary topic}"
  * Open with: "One more thought before I close this out — "
  * PIVOT to the SECONDARY angle (opposite of T1/T2).
  * INCLUDE the secondary URL.
  * CTA: a single question relevant to the secondary angle.
  * 80-110 words body.

TOUCH 4 (+4 biz days from T3) — THE BREAKUP.
  * Subject: "closing the loop, {first_name}"
  * Gracious, no pressure, no guilt-trip.
  * Mention BOTH angles briefly in one line.
  * One URL only, casually placed: "Free check is always at {primary_url} when you want it"
  * NO CTA question. Just a graceful exit.
  * 60-90 words body.

URL ASSIGNMENT (engine-enforced — these will be checked after generation):
  * HIRING angle  -> hire.waymarkhrgroup.com
  * COMPLIANCE angle -> protect.waymarkhrgroup.com
  (The skill file shows protect.waymarkhrgroup.com for both. That is outdated. Use the URL the engine passes you for this touch.)

PERSONALIZATION (NON-NEGOTIABLE):
  * Every email MUST reference the BEST ANCHOR passed in below.
  * The hook (lines 1-2) is where the anchor goes. Make it sound natural.
  * No generic openers. No flattery.

SIGNATURE (the body must end EXACTLY with this format, on three lines):
  Jamie Wahler
  Waymark HR Group | SHRM-Certified
  716-225-6347

  P.S. <see PER-TOUCH PS RULES below>

PER-TOUCH PS RULES (the engine validates and, for T2-T4, force-replaces):

  TOUCH 1 (cold open): Use one of the skill file's approved T1 PS formulas.
  Real scarcity is the right tool on a cold open. Examples:
    "P.S. I take 3 new clients per month. One slot open for {Month}."
    "P.S. SHRM-Certified, 10 years in WNY HR. All work is hands-on -- no outsourcing."

  TOUCH 2, 3, AND 4 (follow-ups): Use this EXACT line, verbatim:
    P.S. Last WNY shop I audited had 3 handbook gaps that would've cost $50K+ to defend. They had no idea.
  The engine will overwrite your PS with this line on T2-T4 anyway, but write
  it correctly the first time. Proof of work beats scarcity on a follow-up.

  RETIRED PS COPY -- NEVER USE on any touch (engine validation will reject):
    "I work with [X] WNY shops right now. Have capacity for one more this month."
    Any close variant of the above.

OUTPUT FORMAT (CRITICAL):
Return ONE JSON object — no markdown fences, no preamble, no commentary:

{
  "subject": "...",
  "body": "...",
  "touch_number": <integer>
}

The body must contain newlines as actual \\n characters in the JSON string.
"""


def _load_skill_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _build_system_prompt(skill_file_path: str) -> str:
    skill = _load_skill_file(skill_file_path)
    return skill + "\n\n" + _V2_APPENDIX


# ---------------------------------------------------------------------------
# User prompt
# ---------------------------------------------------------------------------

def _build_user_prompt(
    enrichment: dict,
    touch_number: int,
    url_for_this_touch: Optional[str],
    angle_for_this_touch: str,
    extra_violation_note: Optional[str] = None,
    forced_subject: Optional[str] = None,
) -> str:
    job_postings = json.dumps(enrichment.get("active_job_postings", []), ensure_ascii=False)
    recent_news = json.dumps(enrichment.get("recent_news", []), ensure_ascii=False)

    url_block = (
        f"URL for this touch: {url_for_this_touch}"
        if url_for_this_touch
        else "URL for this touch: NONE — touch 1 has no links anywhere in the body."
    )

    base = f"""\
Generate Touch {touch_number} for this lead. Follow every rule in the skill
above AND the v2 appendix.

LEAD DATA (from enrichment):
- first_name: {enrichment.get('first_name')}
- company_name: {enrichment.get('company_name')}
- trade: {enrichment.get('trade')}
- city: {enrichment.get('city')}
- years_in_business: {enrichment.get('years_in_business')}
- employee_count_range: {enrichment.get('employee_count_range')}
- active_job_postings: {job_postings}
- recent_news: {recent_news}
- BEST ANCHOR (use in hook, mandatory): {enrichment.get('best_anchor')}

ANGLE FOR THIS TOUCH: {angle_for_this_touch}
- primary_angle (T1/T2): {enrichment.get('primary_angle')}
- secondary_angle (T3): {enrichment.get('secondary_angle')}
- primary_url: {enrichment.get('primary_url')}
- secondary_url: {enrichment.get('secondary_url')}

{url_block}

Output the JSON object now. No markdown. No preamble.
"""
    if forced_subject:
        base += (
            f"\nNOTE: The engine will overwrite the subject with {forced_subject!r} "
            "after generation. Write a subject anyway (the model may use it as a draft) "
            "but focus your effort on the body.\n"
        )
    if extra_violation_note:
        base += f"\nIMPORTANT — previous attempt failed validation: {extra_violation_note}\nFix that issue this time.\n"
    return base


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def _strip_text(resp) -> str:
    parts = []
    for block in resp.content or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def _parse_email_json(raw: str) -> dict:
    cleaned = raw.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = _JSON_BLOCK_RE.search(cleaned)
    if not m:
        raise GenerationError(f"Could not parse JSON from model output: {cleaned[:200]!r}")
    return json.loads(m.group(0))


def _body_word_count(body: str) -> int:
    """Count words in the body, excluding the signature block + PS line."""
    # Split the body at the first occurrence of "Jamie Wahler" (signature start).
    cut_markers = ["\nJamie Wahler", "\njamie wahler", "\nJamie\n"]
    body_for_count = body
    for marker in cut_markers:
        idx = body.find(marker)
        if idx > 0:
            body_for_count = body[:idx]
            break
    words = re.findall(r"\b[\w'\-]+\b", body_for_count)
    return len(words)


def _scan_banned(text: str) -> Optional[str]:
    """Return a description of the first banned word/phrase found, or None.

    Skip the signature/PS block when scanning — the model may legitimately
    say things like 'I take 3 new clients' which would otherwise trip false
    positives.
    """
    lowered = text.lower()
    # Cut off at signature so PS line scarcity doesn't false-positive on
    # words like 'opening' / 'capacity'.
    for marker in ["\njamie wahler", "\njamie\n"]:
        idx = lowered.find(marker)
        if idx > 0:
            lowered = lowered[:idx]
            break

    for word in BANNED_WORDS:
        # Match whole-word only (so 'scaling' doesn't trip on 'scale').
        pattern = r"\b" + re.escape(word) + r"\b"
        if re.search(pattern, lowered):
            return f"banned word: {word!r}"
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            return f"banned phrase: {phrase!r}"
    return None


def _has_link(body: str) -> bool:
    return bool(_LINK_RE.search(body))


def _scan_retired_ps(text: str) -> Optional[str]:
    """Scan the FULL body (including PS line) for retired copy patterns.

    Unlike _scan_banned, this does NOT stop at the signature line, because
    retired PS copy lives below the signature.
    """
    for pat, desc in RETIRED_PS_PATTERNS:
        if pat.search(text):
            return desc
    return None


def _force_followup_ps(body: str, ps_line: str) -> str:
    """For T2/T3/T4: strip any model-written PS and append the canonical PS.

    Expected body shape per the v2 appendix:
        <opener + body>
        Jamie Wahler
        Waymark HR Group | SHRM-Certified
        716-225-6347

        P.S. <model-written, may match or not>

    We strip the trailing blank-line + P.S. block (multi-line PS supported via
    re.DOTALL) and append the canonical line with proper spacing. If the
    model omitted a PS entirely, we just append.
    """
    body = body.rstrip()
    body = _TRAILING_PS_RE.sub("", body).rstrip()
    return body + "\n\n" + ps_line + "\n"


def _subject_ok(subject: str, *, skip_word_count: bool = False) -> Optional[str]:
    """Return reason string if subject violates rules, else None.

    When the orchestrator forces the subject (e.g. T2's "re: {T1 subject}"
    or T4's "closing the loop, {first_name}"), we skip the 2-5 word check
    since the chain can naturally extend beyond 5 words.
    """
    if not subject or not subject.strip():
        return "subject is empty"
    if "!" in subject:
        return "subject contains an exclamation point"
    if skip_word_count:
        return None
    words = subject.strip().split()
    if not (2 <= len(words) <= 5):
        return f"subject has {len(words)} words; must be 2-5"
    return None


def _validate(
    email: dict,
    touch_number: int,
    expected_url: Optional[str],
    *,
    subject_is_forced: bool = False,
) -> Optional[str]:
    """Return None if valid, or a human-readable violation string."""
    subject = email.get("subject", "")
    body = email.get("body", "")

    if not subject:
        return "missing subject"
    if not body:
        return "missing body"

    subj_problem = _subject_ok(subject, skip_word_count=subject_is_forced)
    if subj_problem:
        return subj_problem

    word_count = _body_word_count(body)
    lo, hi = WORD_COUNT_RANGES[touch_number]
    # Allow small slop (-5/+5) before regenerating — the regen-once cost is
    # nontrivial and the spec word counts are guidelines.
    if word_count < lo - 5 or word_count > hi + 5:
        return f"body word count {word_count} outside touch {touch_number} range {lo}-{hi}"

    banned = _scan_banned(body) or _scan_banned(subject)
    if banned:
        return banned

    retired = _scan_retired_ps(body) or _scan_retired_ps(subject)
    if retired:
        return retired

    has_link = _has_link(body)
    if touch_number == 1 and has_link:
        return "touch 1 must have ZERO links in the body"
    if touch_number in (2, 3, 4):
        if not expected_url:
            return f"touch {touch_number} requires a URL but none was provided"
        if expected_url.lower() not in body.lower():
            return f"touch {touch_number} body must include URL {expected_url!r}"
        if touch_number == 1 and has_link:
            return "touch 1 must have ZERO links"

    return None


# ---------------------------------------------------------------------------
# Public entry point — Phase 1: T1 only
# ---------------------------------------------------------------------------

def generate_t1(
    enrichment: dict,
    skill_file_path: str,
    *,
    client: Optional[anthropic.Anthropic] = None,
) -> dict:
    """Generate a Touch 1 email for an enriched lead.

    Returns dict {"subject": str, "body": str, "touch_number": 1}.

    Raises GenerationError after MAX_REGEN_ATTEMPTS unsuccessful tries.
    """
    return _generate(
        enrichment=enrichment,
        touch_number=1,
        url_for_this_touch=None,  # T1 has no link
        angle_for_this_touch=enrichment.get("primary_angle") or "compliance",
        skill_file_path=skill_file_path,
        client=client,
    )


def generate_t2(
    enrichment: dict,
    t1_subject: str,
    skill_file_path: str,
    *,
    client: Optional[anthropic.Anthropic] = None,
) -> dict:
    """Generate Touch 2 (Day +3 business days). Primary angle reinforced, primary URL.

    Subject is forced to "re: {T1 subject}" so the Gmail client threads it
    correctly. The body is engine-generated.
    """
    primary_url = enrichment.get("primary_url")
    forced_subject = f"re: {t1_subject}" if t1_subject else None
    return _generate(
        enrichment=enrichment,
        touch_number=2,
        url_for_this_touch=primary_url,
        angle_for_this_touch=enrichment.get("primary_angle") or "compliance",
        skill_file_path=skill_file_path,
        client=client,
        forced_subject=forced_subject,
    )


def generate_t3(
    enrichment: dict,
    skill_file_path: str,
    *,
    client: Optional[anthropic.Anthropic] = None,
) -> dict:
    """Generate Touch 3 (Day +8, i.e. +5 business days after T2). THE PIVOT.

    Uses the SECONDARY angle (opposite of T1/T2) and the secondary URL.
    Subject is engine-generated (model writes "quick thought, {name}" or
    "{company} / {topic}").
    """
    secondary_url = enrichment.get("secondary_url")
    return _generate(
        enrichment=enrichment,
        touch_number=3,
        url_for_this_touch=secondary_url,
        angle_for_this_touch=enrichment.get("secondary_angle") or "hiring",
        skill_file_path=skill_file_path,
        client=client,
    )


def generate_t4(
    enrichment: dict,
    skill_file_path: str,
    *,
    client: Optional[anthropic.Anthropic] = None,
) -> dict:
    """Generate Touch 4 (Day +12, +4 business days after T3). THE BREAKUP.

    Both angles mentioned briefly. Primary URL only, casual placement.
    Subject is forced to "closing the loop, {first_name}".
    """
    primary_url = enrichment.get("primary_url")
    first_name = (enrichment.get("first_name") or "").strip()
    forced_subject = f"closing the loop, {first_name}" if first_name else "closing the loop"
    return _generate(
        enrichment=enrichment,
        touch_number=4,
        url_for_this_touch=primary_url,
        angle_for_this_touch=enrichment.get("primary_angle") or "compliance",
        skill_file_path=skill_file_path,
        client=client,
        forced_subject=forced_subject,
    )


def _generate(
    *,
    enrichment: dict,
    touch_number: int,
    url_for_this_touch: Optional[str],
    angle_for_this_touch: str,
    skill_file_path: str,
    client: Optional[anthropic.Anthropic],
    forced_subject: Optional[str] = None,
) -> dict:
    client = client or anthropic.Anthropic()
    system_prompt = _build_system_prompt(skill_file_path)
    subject_is_forced = forced_subject is not None

    last_violation: Optional[str] = None
    for attempt in range(1 + MAX_REGEN_ATTEMPTS):
        user_prompt = _build_user_prompt(
            enrichment=enrichment,
            touch_number=touch_number,
            url_for_this_touch=url_for_this_touch,
            angle_for_this_touch=angle_for_this_touch,
            extra_violation_note=last_violation,
            forced_subject=forced_subject,
        )
        log.info(
            f"Generating T{touch_number} (attempt {attempt + 1}/{1 + MAX_REGEN_ATTEMPTS}) "
            f"with model {GENERATION_MODEL}"
        )
        try:
            resp = client.messages.create(
                model=GENERATION_MODEL,
                max_tokens=1200,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.APIError as exc:
            raise GenerationError(f"Anthropic API error: {exc}") from exc

        raw = _strip_text(resp)
        try:
            email = _parse_email_json(raw)
        except Exception as exc:
            last_violation = f"JSON parse failed: {exc}"
            log.warning(last_violation)
            continue

        email["touch_number"] = touch_number  # pin
        if subject_is_forced:
            email["subject"] = forced_subject  # overwrite whatever the model wrote

        # Force the canonical proof-of-work PS on follow-up touches.
        # T1 keeps whatever PS the model wrote (real scarcity formula).
        if touch_number in (2, 3, 4):
            email["body"] = _force_followup_ps(email["body"], T234_PS_LINE)

        problem = _validate(
            email, touch_number, url_for_this_touch,
            subject_is_forced=subject_is_forced,
        )
        if problem is None:
            log.info(
                f"T{touch_number} OK on attempt {attempt + 1}: "
                f"{_body_word_count(email['body'])} words, subject={email['subject']!r}"
            )
            return email

        last_violation = problem
        log.warning(f"T{touch_number} validation failed: {problem}")

    raise GenerationError(
        f"T{touch_number} failed validation after {1 + MAX_REGEN_ATTEMPTS} attempts. "
        f"Last violation: {last_violation}"
    )
