# WAYMARK HR GROUP — GMAIL COLD EMAIL ENGINE
## Master Build Spec for Claude Code — v2.0

**Owner:** Jamie Wahler · Waymark HR Group LLC · (he/him)
**Sending account:** Google Workspace @ waymarkhrgroup.com
**Volume target:** 25 outbound sends per day, 5 days/week (M–F)
**Framework:** Alex Hormozi $100M Leads — Cold Outreach pillar of the Core Four
**Goal:** Manufacture qualified conversations with WNY blue-collar business owners at the Rule of 100 scale (adjusted to 25/day) for the 100-day push toward $25K profit by 12/31/26

---

## SECTION 0 — READ THIS FIRST OR DON'T BUILD

Claude Code: before you write a single line of code, **read `/mnt/project/WAYMARK_COLD_EMAIL_SKILL.md` in full.** That file is the source of truth for email content — subject lines, hook structure, value section, CTA rules, PS lines, banned words, formatting. Do not paraphrase it. Do not "improve" it. Pass it verbatim as the system prompt when generating emails.

Note: the skill file currently describes a 3-touch sequence. **This spec overrides that with a 4-touch sequence** (see Section 2). When generating emails, follow the skill file for content rules AND this spec for sequence/touch logic.

If the skill file and this spec ever conflict on content rules, the skill file wins. If they conflict on architecture or sequence timing, this spec wins.

---

## SECTION 1 — THE MISSION

You are not building a marketing automation tool. You are not building Mailchimp. You are not building a "drip campaign" platform.

You are building a **conversation manufacturing machine** that:

1. Reads queued leads from Gmail labels (input = email + URL + first name)
2. Researches each company automatically using web_fetch + web_search (no external enrichment tool)
3. Picks the angle automatically based on what it finds
4. Generates one Hormozi-grade personalized email per lead using the Anthropic API
5. Sends from Jamie's Workspace inbox, paced like a human
6. Watches for replies and alerts Jamie within 5 minutes when a real human replies
7. Automatically runs the 4-touch sequence end-to-end if no reply
8. Tracks every lead's state through Gmail labels — labels ARE the database
9. Emails Jamie a daily report at 5:30 PM ET

The goal of every email is **a reply.** Not a click. Not a meeting. A reply. Once a human replies, the engine STOPS the sequence and hands off to Jamie. Conversations close. Cold sequences don't.

Jamie's daily work: **drop 25 drafts into the queue in the morning (~4 minutes), handle reply notifications when the phone buzzes.** Nothing else.

---

## SECTION 2 — THE 4-TOUCH SEQUENCE

This is the new sequence. Memorize it. Every piece of logic in this engine references it.

| Touch | Timing | Purpose | Angle | URL |
|---|---|---|---|---|
| **T1** | Day 0 | Hook + value + reply-generating question | PRIMARY (auto-picked) | NONE — no links in T1 |
| **T2** | +3 business days from T1 | Soft follow-up, reinforce primary angle | PRIMARY (same as T1) | Primary URL |
| **T3** | +5 business days from T2 | **PIVOT** to the secondary angle — different pain, fresh anchor | SECONDARY (opposite of T1/T2) | Secondary URL |
| **T4** | +4 business days from T3 | Breakup email. "Last note from me." | BOTH (mention both briefly) | Primary URL only, casually placed |

Total span: ~12 business days from T1 to T4 (~2.5 calendar weeks).

### Angle definitions
- **HIRING angle** → lead magnet is the AI Hiring Kit → URL = `hire.waymarkhrgroup.com`
- **COMPLIANCE angle** → lead magnet is the Employer Protection Scorecard → URL = `protect.waymarkhrgroup.com`

### Angle picker (automatic, runs once per lead during enrichment)
- If active job postings are found for the company on Indeed/ZipRecruiter/company careers page → **PRIMARY = HIRING**, SECONDARY = COMPLIANCE
- If NO active hiring signal found → **PRIMARY = COMPLIANCE**, SECONDARY = HIRING

The primary angle is locked in once chosen — T1 and T2 use it. T3 always pivots to the secondary.

### Touch-by-touch content rules

**T1 — Day 0**
- Hook references ONE specific anchor pulled from enrichment (open role, years in business, recent news, etc.)
- Value sentence specific to the primary angle (NY compliance cost OR recruiter fee / time-to-hire pain)
- Mentions the free check exists but **does NOT paste any URL**
- CTA = a reply-generating question
- PS = real scarcity ("3 clients/month, one slot open for {month}")
- 80–130 words body

**T2 — +3 business days**
- Subject: `re: {T1 subject}`
- Sent as a reply on the same Gmail thread (preserves `In-Reply-To` and `References` headers)
- Tone: lighter, "wanted to follow up quickly"
- Reinforces the primary angle with a slightly different angle of the same pain
- **Includes the primary URL** as a plain text line: `Worth a look? → {primary_url}`
- 60–100 words

**T3 — +5 business days from T2 — THE PIVOT**
- Subject: `quick thought, {first_name}` or `{company} / {secondary_topic}` (engine picks)
- Sent as a reply on the same Gmail thread
- Opens with: "One more thought before I close this out — "
- Pivots to the secondary angle: if T1/T2 were compliance, T3 raises the hiring/recruiting pain; if T1/T2 were hiring, T3 raises the compliance/lawsuit risk
- Specific value sentence for the secondary angle
- **Includes the secondary URL**: `If that's more relevant, the check for that is at {secondary_url}`
- CTA = a single question relevant to the secondary angle
- 80–110 words

**T4 — +4 business days from T3 — THE BREAKUP**
- Subject: `closing the loop, {first_name}`
- Sent as a reply on the same Gmail thread
- Tone: gracious, no pressure, no guilt-trip
- Acknowledges they're busy
- Mentions BOTH angles briefly in one line: "If compliance or hiring ever comes up — I'm local, SHRM-certified, easy to reach"
- One URL only, casual: "Free check is always at {primary_url} when you want it"
- 60–90 words
- After T4 is sent, thread is moved to `10_CLOSED_LOST` after 14 calendar days of no reply

---

## SECTION 3 — HORMOZI CONSTRAINTS (NON-NEGOTIABLE)

These are the rails. Every line of code, every prompt, every send schedule must respect these.

### Email content constraints
- **Body length:** 60–130 words depending on touch (see Section 2). Hard cap 130.
- **Subject length:** 2–5 words, mostly lowercase, no exclamation points, no clickbait, no numbers promising results.
- **Format:** Plain text only. No HTML. No images. No tracking pixels. Raw URLs only — no t.co, bit.ly, or any redirect/shortener.
- **Touch 1 links:** ZERO. The URL only appears starting at Touch 2.
- **Signature:** First name + last name · Company name · Phone number · (optional) one-line SHRM credential. Nothing else. No image logo. No legal disclaimer. No LinkedIn badge.
- **Personalization requirement:** Every email must reference at least ONE specific real detail about the recipient's business pulled from enrichment.
- **Banned words:** scale, double, triple, guarantee, risk-free, passive income, game-changer, revolutionary, cutting-edge, synergy, leverage, skyrocket, explode, crush, dominate, partnership, opportunity, exciting.
- **Banned phrases:** "I hope this email finds you well", "I came across your company", "I'd love to connect", "quick 15 minutes", "circling back", "just following up", "touching base", "checking in".

### Send pacing constraints
- **Daily cap:** Hard maximum 25 sends per day across ALL touches combined (T1 + T2 + T3 + T4 sends count against the same cap). Engine refuses to exceed.
- **Send window:** 9:00 AM – 4:30 PM Eastern Time. Never outside that window.
- **Send days:** Monday–Friday only.
- **Inter-send gap:** Randomized between 12 and 28 minutes. Never two sends within 10 minutes of each other.
- **Never burst:** No more than 4 sends in any rolling 60-minute window.
- **Holiday awareness:** No sends on US federal holidays. No sends on the business day before/after Thanksgiving or Christmas.

### Reply handling constraints
- **Speed-to-lead alert:** Push notification to Jamie within 5 minutes of a real reply.
- **Sequence stops:** The moment a real reply is detected on a sent thread, ALL scheduled follow-ups for that thread are cancelled. Engine never touches that thread again.
- **Out-of-office filter:** OOO/autoreply replies do NOT count. Sequence continues. (Filter logic in Section 7.)

### Send-order priority (when the queue has multiple eligible threads)
1. Eligible T4 sends (breakups) — FIRST
2. Eligible T3 sends (pivots) — SECOND
3. Eligible T2 sends (follow-ups) — THIRD
4. New T1 sends (cold opens) — LAST

Warmer threads beat colder threads. Always finish the conversations you started before opening new ones.

---

## SECTION 4 — ARCHITECTURE: GMAIL LABEL STATE MACHINE

Gmail labels ARE the database. No external CRM. No spreadsheet. No SQLite (except for the small operational cache in Section 11). The state of every lead is its current Gmail label. The engine is a state machine that moves threads between labels.

### Label taxonomy — create these on first run

```
Waymark Outbound/
  ├── 00_DO_NOT_CONTACT       # Hard exclude — engine never touches
  ├── 01_QUEUED               # Lead drafted by Jamie, needs enrichment + T1
  ├── 02_SENT_T1              # Touch 1 sent, awaiting reply or +3d
  ├── 03_SENT_T2              # Touch 2 sent, awaiting reply or +5d
  ├── 04_SENT_T3              # Touch 3 sent, awaiting reply or +4d
  ├── 05_SENT_T4              # Touch 4 (breakup) sent — sequence complete
  ├── 06_REPLIED 🔥           # PRIORITY — real human replied, Jamie's job
  ├── 07_BOOKED               # Game Plan session booked
  ├── 08_CLOSED_WON           # Became paying customer
  ├── 09_NOT_INTERESTED       # Polite no — archive forever
  └── 10_CLOSED_LOST          # Sequence ended without conversion
```

Two-digit numbering ensures correct alphabetical sort in Gmail.

### State transitions
```
01_QUEUED ──[enrich + T1 sent]──▶ 02_SENT_T1
02_SENT_T1 ──[+3 biz days, no reply]──▶ 03_SENT_T2
03_SENT_T2 ──[+5 biz days, no reply]──▶ 04_SENT_T3
04_SENT_T3 ──[+4 biz days, no reply]──▶ 05_SENT_T4
05_SENT_T4 ──[+14 cal days, no reply]──▶ 10_CLOSED_LOST

Any state ──[real reply detected]──▶ 06_REPLIED 🔥
06_REPLIED 🔥 ──[Jamie manually labels]──▶ 07_BOOKED / 08_CLOSED_WON / 09_NOT_INTERESTED

Any state ──[Jamie manually labels]──▶ 00_DO_NOT_CONTACT (engine ignores forever)
```

### Critical rules
- The engine only ACTS on threads with labels `01_QUEUED`, `02_SENT_T1`, `03_SENT_T2`, or `04_SENT_T3`.
- The engine NEVER touches threads with `06_REPLIED 🔥`, `07_BOOKED`, `08_CLOSED_WON`, `09_NOT_INTERESTED`, `10_CLOSED_LOST`, or `00_DO_NOT_CONTACT`.
- Threads in `05_SENT_T4` are moved to `10_CLOSED_LOST` after 14 calendar days of silence.
- Once a thread leaves a label, the old label is removed (a thread has exactly ONE Waymark Outbound label at a time, except `06_REPLIED 🔥` which stays until Jamie manually relabels it).

---

## SECTION 5 — LEAD INTAKE FORMAT (NO YAML)

Jamie adds new leads by creating a Gmail draft. The format is **dead simple — three lines in the body**:

```
TO:      bob@buffaloplumbing.com
SUBJECT: (leave blank — engine writes it)
BODY:
Bob
https://buffaloplumbing.com
(optional notes for Jamie's own reference go here)
```

That's it. The engine reads:

1. **Recipient email** from the To: header (Gmail provides this directly via API)
2. **First name** from the first line of the body (single word, alphabetic only)
3. **Company URL** from the second line of the body (must start with `http://` or `https://`)
4. **Anything else** in the body is treated as Jamie's personal notes — the engine ignores it (but it stays in the thread for Jamie's future reference)

After drafting, Jamie applies the label `01_QUEUED`. Engine takes it from there.

### Validation (engine runs this before processing)
- If To: address is missing or malformed → label thread `INVALID_INPUT`, alert Jamie
- If first body line is missing or not a clean first name (1–20 alphabetic characters, may include hyphens or apostrophes) → label `INVALID_INPUT`
- If second body line is not a valid URL → label `INVALID_INPUT`
- If To: domain is in the consumer blocklist (`gmail.com`, `yahoo.com`, `hotmail.com`, `outlook.com`, `aol.com`, `icloud.com`, `me.com`) → label `INVALID_INPUT` (these are not business owners)
- If email address is already in `00_DO_NOT_CONTACT` history → label `INVALID_INPUT_DUPLICATE`

### Why first name is required (per Jamie's request)
Enrichment can scrape "About Us" pages and still get the owner's name wrong — especially on company sites that list multiple people or use marketing-team headshots. The five seconds Jamie spends typing "Bob" on line one guarantees every personalization downstream uses the right name. No engine should be guessing this from scraped data.

---

## SECTION 6 — AUTOMATED ENRICHMENT (Claude Code native)

When a thread in `01_QUEUED` comes up for processing, run enrichment using Claude Code's native `web_fetch` and `web_search` tools — NO external enrichment service, NO Manus, NO Apollo, NO Clay.

### Enrichment steps (run in parallel where possible)

1. **Fetch company website** — `web_fetch({company_url})`. Pull and read:
   - Homepage (services, tagline, years in business if mentioned)
   - `/about`, `/about-us`, `/our-story` if present
   - `/services`, `/what-we-do`, `/capabilities` if present
   - `/careers`, `/jobs`, `/employment`, `/join-our-team` if present (hiring signal)
   - `/contact` for location confirmation

2. **Search for active job postings** — `web_search("{company name} {city} site:indeed.com")` and `web_search("{company name} hiring jobs")`. Look for:
   - Active Indeed postings in last 30 days
   - ZipRecruiter postings
   - LinkedIn job posts

3. **Search for LinkedIn company page** — `web_search("{company name} {city} linkedin company")`. Pull employee count range, recent posts, founded year.

4. **Search for recent news** — `web_search("{company name} {city} 2026")` and `web_search("{company name} news expansion award")`. Look for press in the last 12 months.

### Enrichment output (structured, passed to email generator)
After enrichment, produce a single JSON object:

```json
{
  "first_name": "Bob",
  "company_name": "Buffalo Plumbing & Heating",
  "company_url": "https://buffaloplumbing.com",
  "city": "Buffalo, NY",
  "trade": "plumbing and HVAC",
  "years_in_business": 38,
  "employee_count_range": "20-50",
  "active_job_postings": [
    {"title": "Service Technician", "source": "Indeed", "posted_days_ago": 7},
    {"title": "Apprentice Plumber", "source": "Indeed", "posted_days_ago": 14}
  ],
  "recent_news": ["Featured in Buffalo Business First 4/2026 for downtown restaurant project"],
  "primary_angle": "hiring",        // computed: hiring if active_job_postings.length > 0 else compliance
  "secondary_angle": "compliance",  // always the opposite of primary
  "primary_url": "hire.waymarkhrgroup.com",
  "secondary_url": "protect.waymarkhrgroup.com",
  "best_anchor": "2 active service tech roles on Indeed, posted in the last 2 weeks"
}
```

The `best_anchor` field is the SINGLE most specific detail to use in the email hook. If multiple anchors exist, prioritize in this order:
1. Active job posting in last 30 days (strongest hiring signal)
2. Recent news mention in last 90 days (timely, conversational)
3. Specific year count + trade ("38 years running HVAC in Buffalo")
4. Employee count range ("running a 22-person crew in Buffalo")
5. Specific service or specialty pulled from the website

If enrichment fails completely (website unreachable, no data found):
- Label thread `ENRICHMENT_FAILED`
- Alert Jamie via push notification
- Do not send

### Anchor specificity check
Before passing to the email generator, the engine self-checks: would this anchor be true of any random WNY HVAC company, or is it specific to THIS company? If the answer is "any random company," the engine MUST search deeper or fail-safe to `ENRICHMENT_FAILED`. Generic anchors = deleted emails. That's the whole problem we're solving.

---

## SECTION 7 — EMAIL GENERATION (ANTHROPIC API)

### Model
Use `claude-sonnet-4-6` or whatever the latest Sonnet is at build time. Sonnet, not Haiku. Quality > cost at 25/day.

### System prompt
Pass the full contents of `/mnt/project/WAYMARK_COLD_EMAIL_SKILL.md` verbatim, followed by this appendix:

```
You are generating ONE email for the Waymark HR Group cold outreach engine.

The skill above describes a 3-touch sequence. THIS ENGINE USES 4 TOUCHES. Use the skill for content rules but follow these touch-specific rules:

- TOUCH 1: First contact. Reply-generating question CTA. NO LINKS. Primary angle.
- TOUCH 2: Follow-up. Lighter tone. INCLUDE primary URL. Primary angle reinforced.
- TOUCH 3: PIVOT to the OPPOSITE angle. Open with "One more thought before I close this out — " then deliver the secondary angle value. INCLUDE secondary URL. CTA = question relevant to secondary angle.
- TOUCH 4: Breakup. Subject: "closing the loop, {first_name}". Mention BOTH angles briefly in one line. Include primary URL once, casually. No CTA question.

Output ONLY a JSON object — no preamble, no markdown fences, no explanation:

{
  "subject": "...",
  "body": "...",
  "touch_number": N
}

The body must end with:
Jamie Wahler
Waymark HR Group | SHRM-Certified
716-225-6347

P.S. (one line — real scarcity or credential, never fake urgency)

Word counts:
- T1: 80–130 words body (signature/PS not counted)
- T2: 60–100 words
- T3: 80–110 words
- T4: 60–90 words

Subject: 2–5 words, lowercase, no exclamation points, no numbers.
```

### User prompt (per send)
```
Generate Touch {touch_number} for this lead. Follow every rule in the skill above and the touch-specific rules in the appendix.

LEAD DATA (from enrichment):
- First name: {first_name}
- Company: {company_name}
- Trade: {trade}
- City: {city}
- Years in business: {years_in_business}
- Employee count: {employee_count_range}
- Active job postings: {active_job_postings}
- Recent news: {recent_news}
- BEST ANCHOR (use in hook): {best_anchor}

ANGLE FOR THIS TOUCH: {angle_for_this_touch}
- T1/T2 use primary angle: {primary_angle}
- T3 uses secondary angle: {secondary_angle}
- T4 mentions both briefly

URL FOR THIS TOUCH: {url_for_this_touch}
- T1: no URL
- T2: primary URL = {primary_url}
- T3: secondary URL = {secondary_url}
- T4: primary URL = {primary_url}, casual placement

Output the JSON object now.
```

### Response handling
- Parse the JSON. If parse fails, retry once with stricter prompt. If still fails, label `GENERATION_FAILED` and alert.
- Word-count check: body within touch-specific range (excluding signature/PS). If outside, regenerate once with violation called out.
- Banned-word scan: scan body and subject. If any banned word found, regenerate once.
- Link check on Touch 1: scan for `http`/`https`. If found, regenerate once.
- Link check on T2/T3/T4: confirm the correct URL is present. If wrong URL or missing, regenerate once.
- After 2 failed regenerations, label `GENERATION_FAILED` and alert Jamie.

---

## SECTION 8 — THE SEND ENGINE

### Scheduling loop
- Cron runs every 15 minutes between 9:00 AM and 4:30 PM ET, M–F (skip holidays).
- On each tick, in order:
  1. Count sends in last 24 hours. If ≥ 25, exit.
  2. Count sends in last 60 minutes. If ≥ 4, exit.
  3. Compute time since last send. If < 12 minutes, exit.
  4. Generate random number in [12, 28]. If time since last send < that number, exit.
  5. Find next eligible thread, using send-order priority (Section 3): T4 ▸ T3 ▸ T2 ▸ T1.
  6. If thread is `01_QUEUED`: run enrichment (Section 6), then generate (Section 7), then send T1, then move to `02_SENT_T1`, then store send timestamp.
  7. If thread is `02_SENT_T1` eligible for T2: generate T2 with stored enrichment data, send as reply on the thread, move to `03_SENT_T2`, store send timestamp.
  8. If thread is `03_SENT_T2` eligible for T3: generate T3 (pivot angle), send as reply on the thread, move to `04_SENT_T3`, store send timestamp.
  9. If thread is `04_SENT_T3` eligible for T4: generate T4 (breakup), send as reply on the thread, move to `05_SENT_T4`, store send timestamp.

### Follow-up eligibility logic
- T2 eligible when: current date ≥ T1 send date + 3 business days, AND no reply detected.
- T3 eligible when: current date ≥ T2 send date + 5 business days, AND no reply detected.
- T4 eligible when: current date ≥ T3 send date + 4 business days, AND no reply detected.
- Business days = M–F, excluding US federal holidays.

### Send mechanics
- For T1: use Gmail API `users.drafts.send` (the lead arrived as a draft).
- For T2/T3/T4: use Gmail API `users.messages.send` with `threadId` set to the original thread so the reply nests properly.
- Set `In-Reply-To` and `References` headers on T2/T3/T4 using the message-id of the previous touch in that thread.
- Subject for T2: `re: {T1 subject}`. Subject for T3: engine-generated, see Section 2. Subject for T4: `closing the loop, {first_name}`.

### Enrichment caching
- Store enrichment results in local SQLite keyed by thread-id, so T2/T3/T4 don't re-enrich. Enrichment only runs once per thread, at T1 time.
- If enrichment data is older than 30 days and a follow-up is about to fire, optionally refresh active-job-postings only (everything else is stable enough).

---

## SECTION 9 — REPLY DETECTION

### Polling approach (recommended for v1)
- Cron every 2 minutes during business hours, every 15 minutes outside.
- Query Gmail for threads with labels `02_SENT_T1`, `03_SENT_T2`, `04_SENT_T3`, or `05_SENT_T4` where `historyId` changed since last check.
- For each changed thread, check if the most recent message is from someone OTHER than `jamie.wahler@waymarkhrgroup.com` (or whatever Jamie's exact sending address is).
- If yes, this is a reply candidate. Run OOO filter before treating as real.

### Out-of-office filter
Before flagging a reply as real, check the reply body (case-insensitive) against these patterns. If ANY match, do NOT flag — keep sequence going:
- "out of office", "ooo", "out of the office", "away from the office"
- "automatic reply", "auto-reply", "auto reply", "this is an automated"
- "I am currently away", "I'm currently away", "currently out"
- "will return on", "will be back on", "back in the office on"
- "for immediate assistance" + "please contact"
- "I am out", "I'm out", combined with a date pattern

### When a real reply is detected
1. Immediately move thread label to `06_REPLIED 🔥`. Remove the previous Waymark Outbound label.
2. Cancel all pending follow-ups for that thread (delete cached schedule rows for that thread-id).
3. Send Jamie a notification within 5 minutes:
   - **Primary:** push via Pushover or ntfy.sh (Claude Code picks one, documents the setup).
   - **Backup:** email to `jamie.wahler+alerts@waymarkhrgroup.com` (Gmail's + addressing works natively).
   - Subject of alert: `🔥 REPLY: {company_name} — {first_name}`. Body: the reply content + the original outbound email it replied to + a one-click link to the thread in Gmail.
4. Log the reply in the daily report.

### Unsubscribe / opt-out handling
If the reply body contains any of: `unsubscribe`, `remove me`, `take me off`, `stop emailing`, `do not contact`, `not interested` (combined with strong language), `fuck off`, `leave me alone`:
- Move thread to `00_DO_NOT_CONTACT` instead of `06_REPLIED 🔥`.
- Permanently add the email address to a `do_not_contact.db` SQLite table.
- All future queue intakes are checked against this table.
- Do not send Jamie a notification — silent.

---

## SECTION 10 — DAILY REPORT

Every business day at 5:30 PM ET, the engine emails Jamie a one-screen daily report from a dedicated address (`engine@waymarkhrgroup.com` or via Gmail filter to a `Reports` label).

### Subject: `Waymark engine — {weekday}, {date}`

### Report contents (plain text, scannable in 30 seconds)
```
SENT TODAY
  Touch 1 (new):       X
  Touch 2 (3d FU):     Y
  Touch 3 (pivot):     Z
  Touch 4 (breakup):   W
  Total today:         X+Y+Z+W / 25

REPLIES TODAY
  Real replies:        N   ← Handle in 06_REPLIED 🔥
  Out-of-office:       M
  Unsubscribes:        U
  Bounces:             B

PIPELINE SNAPSHOT (live label counts)
  01_QUEUED:           ___
  02_SENT_T1:          ___
  03_SENT_T2:          ___
  04_SENT_T3:          ___
  05_SENT_T4:          ___
  06_REPLIED 🔥:       ___  ← Jamie's action items

THIS WEEK (M–F rolling)
  Sent total:          ___
  Real replies:        ___
  Reply rate:          ___%
  Booked sessions:     ___  (count of moves from 06 → 07)
  Closed won:          ___  (count of moves from 07 → 08)

ALERTS
  - Domain reputation:  GREEN / YELLOW / RED
  - Daily cap reached:  YES / NO
  - Enrichment failures today:  ___
  - Generation failures today:  ___
  - Errors (last 24h):  none / list

TOMORROW'S QUEUE PREVIEW
  01_QUEUED waiting: ___
  T2 eligible at next send window: ___
  T3 eligible: ___
  T4 eligible: ___
```

---

## SECTION 11 — LOCAL STORAGE

Gmail labels are the primary database. Local SQLite is ONLY for operational state that doesn't belong in Gmail.

### `waymark_engine.db` tables
- `enrichment_cache(thread_id, enrichment_json, captured_at)` — one row per thread, populated at T1
- `send_log(thread_id, touch_number, sent_at, message_id)` — one row per send for pacing + follow-up timing
- `bounce_history(email_address, bounced_at, bounce_type)` — never send to a bounced address again
- `do_not_contact(email_address, added_at, source)` — hard exclude list
- `holiday_calendar(date, name)` — pre-loaded US federal holidays + Thanksgiving/Christmas adjacencies
- `errors(timestamp, severity, thread_id, message)` — surfaces in daily report

No customer data, no PII beyond email + first name. Backup the DB nightly to a separate location.

---

## SECTION 12 — SAFETY RAILS (NEVER DO)

These are not preferences. Code defensively to make them impossible.

1. **Never send to the same recipient twice in the same sequence.** Dedupe on email address across `02–05` labels.
2. **Never send if Workspace bounce rate over the last 7 days exceeds 5%.** Pause and alert.
3. **Never send if spam complaint rate exceeds 0.1%.** Pause and alert.
4. **Never send to anyone in `00_DO_NOT_CONTACT` or `do_not_contact.db`.**
5. **Never send to consumer domains** (gmail.com, yahoo.com, hotmail.com, outlook.com, aol.com, icloud.com, me.com).
6. **Never modify or delete a `06_REPLIED 🔥` thread.** That's Jamie's.
7. **Never include a tracking pixel.** Plain text only.
8. **Never use URL shorteners.** Raw domain only.
9. **Never CC or BCC anyone.** Every send is 1:1.
10. **Never send outside the 9:00 AM – 4:30 PM ET M–F window.**
11. **Never send to an email that has previously bounced** (bounce cache check on every send).
12. **Never send during US federal holidays** or the business day before/after Thanksgiving and Christmas.
13. **Never resend a touch that already sent successfully** (idempotency check by thread-id + touch-number).
14. **Never let the engine "improve" the email content beyond what the skill file allows.** No "enhancement" passes. The skill file is the ceiling.

---

## SECTION 13 — BUILD ORDER (MVP → V2)

Do NOT try to build everything at once. Each phase must be tested with real sends before moving on.

### Phase 1 — MVP: T1 only end-to-end (Goal: 25 T1 emails sent this week)
1. Workspace OAuth + Gmail API scopes (`gmail.modify`, `gmail.send`, `gmail.labels`)
2. Create the 11 labels from Section 4
3. Build the draft-intake parser (Section 5)
4. Build the auto-enrichment module (Section 6) using web_fetch + web_search
5. Build the email generator (Anthropic API + skill file)
6. Build the basic send loop for T1 only (no follow-ups yet)
7. Queue 3 test leads (Jamie's own email + 2 friendly contacts). Verify end-to-end.
8. Send the first real 25 in a single business day. Check delivery to inbox (not spam).

### Phase 2 — Follow-up engine: T2 + T3 + T4
1. Build the business-day calculator (M–F minus holidays)
2. Build T2 generator (primary angle reinforced, primary URL)
3. Build T3 generator (PIVOT to secondary angle, secondary URL)
4. Build T4 generator (breakup, both angles mentioned briefly)
5. Build the eligibility checker. Run on cron with send-order priority.
6. Test with Phase 1 leads — confirm T2 fires day +3, T3 fires day +8, T4 fires day +12.

### Phase 3 — Reply detection: 5-minute alert when a real human replies
1. Build the polling loop
2. Build the OOO filter
3. Build the unsubscribe handler
4. Build the notification layer (Pushover or ntfy.sh + email backup)
5. Test by having a friendly contact reply. Confirm alert in <5 minutes.

### Phase 4 — Daily report + safety rails: engine runs unsupervised
1. Build the daily report
2. Wire bounce monitoring (parse bounce messages from `mailer-daemon@`)
3. Wire all rate limiters, holiday calendar, weekend skip
4. Run one full week unsupervised. Watch daily reports. Tune.

---

## SECTION 14 — STACK

Recommended (Claude Code may override with reason):

- **Language:** Python 3.11+
- **Gmail:** `google-api-python-client`, `google-auth-oauthlib`
- **Anthropic:** `anthropic` Python SDK
- **Scheduler:** APScheduler (in-process) or systemd timers
- **Storage:** Gmail labels for state; local SQLite for ops (Section 11)
- **Notifications:** Pushover (paid, $5 one-time) or ntfy.sh (free, self-hostable)
- **Logs:** Rotating file logger; ERROR-level events surface in daily report

Engine runs on Jamie's local machine OR a dedicated small VPS. Never on a shared cron service that could miss runs.

---

## SECTION 15 — WHAT NOT TO BUILD

Claude Code: I see you reaching for these. Don't.

- ❌ A web dashboard. Gmail labels ARE the dashboard.
- ❌ External enrichment services (Apollo, Clay, Hunter, Manus via Zapier). Native `web_fetch` + `web_search` is sufficient and free.
- ❌ A "lead scoring" system at this volume. Statistically meaningless at 25/day.
- ❌ A/B testing infrastructure. Not enough volume.
- ❌ Multi-mailbox support. One sender, one voice, one identity.
- ❌ Open tracking pixels. Plain text only.
- ❌ Click tracking via redirected URLs. Raw domain only.
- ❌ A "smart reply" or auto-reply feature. Humans close humans.
- ❌ Anything that writes to `06_REPLIED 🔥` after the initial move. That label is Jamie's.
- ❌ Slack integration / Discord integration / Teams integration. Phone push is enough.
- ❌ A web form for lead intake. Gmail drafts are the intake.

---

## SECTION 16 — HANDOFF CHECKLIST FOR JAMIE

Before the engine sends a single real email:

- [ ] Workspace DKIM, SPF, and DMARC all verified (`dig` or mxtoolbox.com)
- [ ] Sender display name set to "Jamie Wahler" — not "Waymark HR Group" and not "Outreach"
- [ ] `protect.waymarkhrgroup.com` is live, scorecard PDF delivers via MailerLite on opt-in
- [ ] `hire.waymarkhrgroup.com` is live, AI Hiring Kit delivers on opt-in
- [ ] Calendly link is live: `https://calendly.com/jamie-wahler-waymarkhrgroup/30min`
- [ ] Phone 716-225-6347 is on Jamie's person during all send windows
- [ ] Push notification app (Pushover or ntfy.sh) installed and tested
- [ ] `jamie.wahler+alerts@waymarkhrgroup.com` filter set up in Gmail for backup alerts
- [ ] First 25 leads queued as drafts with the 3-line format (Section 5) and labeled `01_QUEUED`

---

## SECTION 17 — METRICS THAT MATTER

### The only three numbers Jamie watches
1. **Sent per day** (target: 25)
2. **Reply rate** (industry cold: 1–3%. Hormozi-grade with auto-enrichment: target 3–6%. Below 1% = anchors too generic OR list too cold)
3. **Booked Game Plan sessions per week** (this is the dollar)

### Vanity metrics to ignore
- Open rate (no tracking pixels by design)
- Click rate (T1 has no link by design)
- "Engagement score"
- Any colorful dashboard widget

### Diagnostic thresholds
- 25/day for 5 straight days, replies < 1% → enrichment anchors are too generic. Audit `best_anchor` outputs.
- 25/day for 5 straight days, replies ≥ 3% but bookings = 0 → reply handling is wrong. Audit Jamie's responses in `06_REPLIED 🔥`.
- Bookings ≥ 2/week but close rate < 20% → the Game Plan session itself is the problem.
- Reply rate > 5% AND bounce rate > 3% → list quality issue. Validate emails before queuing.

---

## FINAL WORD TO CLAUDE CODE

This engine exists to manufacture conversations with WNY blue-collar business owners — not to send beautiful emails to nobody who matters. Every architectural decision answers one question: **does this make Jamie's emails more likely to get a reply from a real WNY business owner?**

If yes, build it.
If no, delete it.

Jamie has 9 active customers, two grand slam offers that close on Game Plan calls, and a hard target of $25K profit by 12/31/26. The math at 25/day with a 3% reply rate and a 30% Game Plan close rate gets him there — and then some — before the calendar runs out.

Build the engine that gets him to those conversations. Nothing more. Nothing less.

---

*Spec prepared by: Hormozi-mode Claude*
*Version: 2.0*
*Date: June 9, 2026*
*Changes from v1: 4-touch sequence (was 3), Touch 3 pivots to secondary angle, simplified 3-line intake (no YAML), automatic enrichment via Claude Code native tools (no Manus/Apollo/Clay), corrected sender pronouns (Jamie is he/him)*
*Authoritative source for email content: `/mnt/project/WAYMARK_COLD_EMAIL_SKILL.md`*
