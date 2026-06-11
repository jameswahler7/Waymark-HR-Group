# WAYMARK HR GROUP — ENGINE OPERATIONS MANUAL
## Master Context Document for Claude Sessions

**Last updated:** June 11, 2026
**Status:** LIVE — engine running in production
**Owner:** Jamie Wahler · Waymark HR Group LLC · Jamie.wahler@waymarkhrgroup.com

---

## WHAT THIS DOCUMENT IS

This document tells any Claude session (Claude.ai chat or Claude Code) exactly what was built, how it works, where everything lives, and how to operate or modify it. Read this before touching anything.

---

## THE ENGINE IN ONE PARAGRAPH

The Waymark Cold Email Engine is a fully automated outbound cold email system running on Jamie's MacBook Air. Jamie queues leads by creating Gmail drafts in a 3-line format and applying a Gmail label. The engine researches each company automatically (website, Indeed job postings, LinkedIn, news), picks the right offer angle, writes a personalized Hormozi-grade email, sends it, and follows up automatically over 12 business days with 4 total touches. If a prospect replies, the engine detects it within 5 minutes, moves the thread to a priority label, and sends a push notification to Jamie's iPhone. A daily report arrives in Jamie's inbox every weekday at 5:30 PM ET.

---

## THE TWO OFFERS

| Offer | Price | Landing Page | Angle |
|---|---|---|---|
| Bulletproof Business System | $3,500 | protect.waymarkhrgroup.com | NY compliance protection |
| AI Hiring Accelerator | $997 | hire.waymarkhrgroup.com | Hiring speed, eliminating recruiter fees |

**Auto-angle logic:** if enrichment finds active job postings on Indeed/ZipRecruiter/careers page → PRIMARY = Hiring. No hiring signal found → PRIMARY = Compliance. T3 always pivots to the OPPOSITE (secondary) angle.

---

## THE 4-TOUCH SEQUENCE

| Touch | Timing | Angle | URL | Word Count |
|---|---|---|---|---|
| T1 | Day 0 | Primary | NONE | 80–130 |
| T2 | +3 business days from T1 | Primary (same) | Primary URL | 60–100 |
| T3 | +5 business days from T2 | **SECONDARY (pivot)** | Secondary URL | 80–110 |
| T4 | +4 business days from T3 | Both briefly | Primary URL only | 60–90 |

After T4: thread auto-closes to `10_CLOSED_LOST` after 14 calendar days of silence.

**Send priority when multiple threads are eligible:** T4 first → T3 → T2 → T1 last.

---

## GMAIL LABEL STATE MACHINE

Labels ARE the database. No external CRM.

```
00_DO_NOT_CONTACT      Hard exclude — engine never touches
01_QUEUED              Jamie created the draft — engine picks up here
02_SENT_T1             T1 sent, waiting for reply or +3 business days
03_SENT_T2             T2 sent, waiting for reply or +5 business days
04_SENT_T3             T3 sent, waiting for reply or +4 business days
05_SENT_T4             T4 sent — sequence complete, waiting to close
06_REPLIED 🔥          REAL reply — Jamie's job now, engine won't touch
07_BOOKED              Game Plan session booked
08_CLOSED_WON          Became paying customer
09_NOT_INTERESTED      Polite no
10_CLOSED_LOST         Sequence ended without conversion
ENRICHMENT_FAILED      Engine couldn't research the company — Jamie's attention needed
GENERATION_FAILED      Email generation failed after 3 attempts — Jamie's attention needed
INVALID_INPUT          Draft was malformed (bad URL, missing name, consumer domain)
```

---

## JAMIE'S DAILY WORKFLOW (the ONLY thing Jamie does)

**Every morning, create up to 25 Gmail drafts in this format:**

```
TO:  prospect@theircompany.com
SUBJECT: (leave blank)
BODY:
FirstName
https://theirwebsite.com
(optional notes for Jamie's reference — engine ignores anything after line 2)
```

**Apply label `Waymark Outbound/01_QUEUED` to the draft.**

That's it. The engine picks it up on the next 15-minute tick, researches the company, writes the email, sends it, and runs the full follow-up sequence automatically.

**Jamie's other job:** when his phone buzzes with a `🔥 REPLY` notification, respond to that prospect within 5 minutes. The reply is already labeled `06_REPLIED 🔥` in Gmail.

---

## FILE STRUCTURE

### Source-of-truth docs (project root)

**Location:** `/Users/jamie/Documents/waymark-hr-group/`

| File | Purpose |
|---|---|
| `WAYMARK_COLD_EMAIL_SKILL.md` | SOURCE OF TRUTH for all email content rules — loaded verbatim as the system prompt by `email_generator.py` |
| `WAYMARK_GMAIL_COLD_EMAIL_ENGINE_v2_MASTER_PROMPT.md` | Full v2 build spec (architecture, sections 1–17) |
| `WAYMARK_ENGINE_OPERATIONS_MANUAL.md` | This file |

### Engine code

**Location:** `/Users/jamie/Documents/waymark-hr-group/followup_engine/`

| File | Purpose |
|---|---|
| `followup_engine.py` | Main orchestrator — runs every 15 min via cron |
| `reply_detector.py` | Reply detection — runs every 2 min via cron |
| `daily_report.py` | Daily report — runs weekdays at 5:30 PM via cron |
| `enrichment.py` | Auto-enrichment using web_fetch + web_search |
| `email_generator.py` | Generates T1/T2/T3/T4 using Anthropic API + skill file |
| `send_engine.py` | Gmail API send with pacing rules |
| `label_manager.py` | Creates + manages all Gmail labels |
| `intake_parser.py` | Reads the 3-line draft format |
| `reply_classifier.py` | Classifies replies as real/OOO/unsubscribe/bounce |
| `notifier.py` | Pushover push notifications + email backup alerts |
| `business_day_calc.py` | Business day math (M–F minus US federal holidays) |
| `db_v2.py` | SQLite database helpers |
| `gmail_auth.py` | Google OAuth helper |
| `.env` | API keys (Anthropic, Pushover, Google OAuth) |
| `waymark_engine.db` | SQLite database |
| `logs/waymark_engine.log` | Full run log |
| `launchd_templates/` | Cron job plist files |
| `followup_engine_v1_legacy.py` | Old 2-touch engine — preserved, not used |

---

## CRON SCHEDULE (3 launchd jobs)

| Job | Schedule | What it does |
|---|---|---|
| `com.waymark.followupengine` | Every 15 min, 9 AM–4:30 PM ET, M–F | Sends up to 1 email per tick, 25/day cap |
| `com.waymark.replydetector` | Every 2 min | Scans active threads for replies |
| `com.waymark.dailyreport` | Weekdays at 5:30 PM | Emails Jamie the daily report |

**To check if jobs are running:**
```bash
launchctl list | grep waymark
```
Three rows = healthy. Empty = jobs not loaded.

**To restart all jobs after a reboot:**
```bash
launchctl load ~/Library/LaunchAgents/com.waymark.followupengine.plist
launchctl load ~/Library/LaunchAgents/com.waymark.replydetector.plist
launchctl load ~/Library/LaunchAgents/com.waymark.dailyreport.plist
```

---

## KEY CONFIGURATION

**All secrets live in:** `/Users/jamie/Documents/waymark-hr-group/followup_engine/.env`

```
ANTHROPIC_API_KEY=sk-ant-api03-...      # Anthropic API — email generation + enrichment
PUSHOVER_USER_KEY=...                   # Pushover user key — reply notifications
PUSHOVER_API_TOKEN=...                  # Pushover app token — reply notifications
```

**Google OAuth token:** `token.json` in the followup_engine folder. If it expires, delete it and run `python3 followup_engine.py --list-only` to re-authorize.

---

## SEND PACING RULES (hardcoded, cannot be overridden)

- 25 sends/day maximum (all touches combined)
- 9:00 AM – 4:30 PM ET only, Monday–Friday
- 12–28 minute randomized gap between sends
- Never more than 4 sends in any rolling 60-minute window
- No sends on US federal holidays
- Never sends to consumer domains (gmail.com, yahoo.com, hotmail.com, etc.)
- Never sends to anyone in `00_DO_NOT_CONTACT`
- Never resends a touch already successfully sent (idempotent)

---

## EMAIL CONTENT RULES (source of truth: WAYMARK_COLD_EMAIL_SKILL.md)

**Subject:** 2–5 words, lowercase, no exclamation points
**Body:** plain text only, no HTML, no images, no tracking pixels
**Links:** no links in T1; raw domain URLs only in T2/T3/T4 (no bit.ly, no tracking redirects)
**Signature:** Jamie Wahler / Waymark HR Group | SHRM-Certified / 716-225-6347
**PS lines:**
- T1: scarcity formula ("I take 3 new clients per month. Currently have one opening for [Month].")
- T2/T3/T4: hardcoded — "P.S. Last WNY shop I audited had 3 handbook gaps that would've cost $50K+ to defend. They had no idea."

**Banned words:** scale, double, triple, guarantee, risk-free, game-changer, partnership, opportunity, exciting, revolutionary, cutting-edge, synergy, leverage, skyrocket, explode, crush, dominate
**Banned phrases:** "I hope this email finds you well", "I came across your company", "circling back", "just following up", "touching base"

---

## HOW TO MAKE COMMON CHANGES

### Change email content rules
Edit `WAYMARK_COLD_EMAIL_SKILL.md`. That file is passed verbatim as the system prompt to the Anthropic API. Changes take effect on the next send.

### Change the T2/T3/T4 PS line
It's hardcoded as `T234_PS_LINE` constant in `email_generator.py`. Find that constant, replace the string. Claude Code can do this in seconds.

### Change follow-up timing
Edit the business day values in `followup_engine.py` — look for `T2_DELAY_DAYS`, `T3_DELAY_DAYS`, `T4_DELAY_DAYS`.

### Change daily send cap
Edit `MAX_DAILY_SENDS` in `followup_engine.py`. Do NOT increase above 50 without warming the domain first.

### Change send window hours
Edit `SEND_WINDOW_START` and `SEND_WINDOW_END` in `send_engine.py`.

### Add a new offer/angle
1. Add the new angle to `WAYMARK_COLD_EMAIL_SKILL.md`
2. Update the angle picker logic in `enrichment.py`
3. Add the new URL to the email generator prompts in `email_generator.py`

### View the log
```bash
tail -f /Users/jamie/Documents/waymark-hr-group/followup_engine/logs/waymark_engine.log
```

### Manually move a thread label
Just click the label in Gmail. The engine respects whatever label state it finds.

### Pause the engine entirely
```bash
launchctl unload ~/Library/LaunchAgents/com.waymark.followupengine.plist
```

### Restart the engine
```bash
launchctl load ~/Library/LaunchAgents/com.waymark.followupengine.plist
```

---

## ICP (IDEAL CUSTOMER PROFILE)

**Who Jamie emails:** Blue-collar business owners in Western New York (Buffalo/Niagara region). Trades: plumbing, HVAC, electrical, construction, fabrication, manufacturing, powder coating. Employee count: 5–100. Decision maker: the owner directly.

**What they care about (compliance angle):** NY State DOL enforcement, wrongful termination exposure ($75K–$150K in legal defense), missing employee handbooks, I-9 compliance, WTPA/LS-54 pay notices.

**What they care about (hiring angle):** Can't find good tradespeople, spending $8K–$15K on recruiters, Indeed black hole, roles open for 60+ days, losing candidates to faster shops.

---

## METRICS JAMIE WATCHES

1. **Sent per day** — target 25
2. **Reply rate** — target 3–6% (below 1% = anchors too generic, audit enrichment)
3. **Booked Game Plan sessions per week** — this is the revenue metric

**Diagnostic thresholds:**
- Reply rate < 1% for 5 days → enrichment anchors too generic. Run `--dry-run` on a few leads and audit the `best_anchor` field.
- Reply rate ≥ 3% but no bookings → audit Jamie's reply handling in `06_REPLIED 🔥`
- Bookings but close rate < 20% → the Game Plan session itself needs work

---

## REVENUE MATH

25 sends/day × 22 business days/month = 550 sends/month
550 × 3% reply rate = ~17 replies/month
17 × 30% Game Plan close rate = ~5 new clients/month
5 clients × $997 avg ticket = ~$5,000/month minimum
5 clients × $3,500 avg ticket = ~$17,500/month if compliance closes

**$25K profit target by 12/31/26 = ~5–7 months of consistent 25/day sending.**

---

## HOW TO BRIEF A NEW CLAUDE SESSION

### For Claude.ai chat sessions
Say: *"I'm working on the Waymark cold email engine. The Operations Manual is in this project. Read it before we start."* Claude will find this document automatically.

### For Claude Code sessions
Say: *"Read the GitHub repo for the waymark-hr-group project, specifically the followup_engine folder. Then read WAYMARK_COLD_EMAIL_SKILL.md and WAYMARK_ENGINE_OPERATIONS_MANUAL.md. Tell me what you understand about the system before we make any changes."*

### Before asking Claude Code to change anything
Always say: *"Before you change any code, tell me which files you'll modify and which you'll leave alone. Wait for my green light."* This prevents accidental breaks.

---

## CURRENT STATUS (as of June 11, 2026)

- ✅ Phase 1 (T1 sends + enrichment + labels): built and tested
- ✅ Phase 2 (T2/T3/T4 follow-up sequence): built and tested
- ✅ Phase 3 (reply detection + Pushover notifications): built and tested
- ✅ Phase 4 (daily report + safety rails + cron activation): built and tested
- ✅ Engine live — 3 cron jobs running on Jamie's MacBook Air
- ✅ GitHub: committed at v2.0-live tag
- ✅ 9 active customers as of June 2026

**Next action:** Queue first 25 real prospects as Gmail drafts. Engine picks them up automatically during the 9 AM–4:30 PM send window.

---

*This document lives in the Waymark HR Group Claude.ai project and in the GitHub repo. Update it whenever a significant change is made to the engine.*
