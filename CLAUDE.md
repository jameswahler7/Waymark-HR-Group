# CLAUDE.md — Waymark HR Group LLC

This file defines how Claude should behave when working in this project.

---

## Company Overview

**Waymark HR Group LLC** is an HR consulting firm that helps businesses build better workplaces. Core service areas include:

- **Employee Onboarding** — designing onboarding programs, checklists, and workflows
- **HR Policy Creation** — drafting, reviewing, and updating employee handbooks and policies
- **Workforce Analytics** — analyzing HR data, headcount, turnover, compensation, and engagement
- **Client Reporting** — producing professional deliverables and presentations for clients

---

## Tone & Content Standards

All content produced in this project must be:

- **Professional and business-appropriate** — this work is delivered to HR leaders and business executives
- **Clear and precise** — avoid jargon where plain language serves better; define acronyms on first use
- **Compliant-minded** — flag any content that may have legal or regulatory HR implications (e.g., employment law, EEOC, FLSA, ADA)
- **Client-ready** — assume any document or report may be shared directly with a client without further editing

Do not use casual language, slang, humor, or informal tone in any document, report, policy, or client-facing content.

---

## Project Structure

```
src/python/         # Data processing, automation, and reporting scripts
src/javascript/     # Web tools, dashboards, and integrations
docs/reports/       # Client-facing reports and analysis (Word, PDF)
docs/templates/     # Reusable document templates
docs/policies/      # HR policy documents and compliance materials
data/spreadsheets/  # Workforce data, compensation, and tracking spreadsheets
data/exports/       # Script-generated output files
config/             # Environment and configuration settings
tests/              # Automated tests for source code
scripts/            # Utility and pipeline automation scripts
```

---

## Code Guidelines

### General
- Write clean, well-structured code with meaningful variable and function names
- Add comments for any non-obvious logic, especially in data transformation or reporting code
- Never hardcode client names, employee data, or sensitive values — use config files or environment variables

### Python (`src/python/`)
- Use Python 3.10+
- Follow PEP 8 style conventions
- Use `pandas` for data manipulation, `openpyxl` for Excel, and `python-docx` for Word documents
- Place reusable logic in modules; keep scripts in `scripts/`
- Write tests for all modules in `tests/`

### JavaScript (`src/javascript/`)
- Use modern ES6+ syntax
- Prefer `async/await` over raw Promise chains
- Keep client-side and server-side code clearly separated

---

## Document Guidelines

- **Reports** go in `docs/reports/` — include client name and date in the filename (e.g., `AcmeCorp_TurnoverAnalysis_2026-03.docx`)
- **Templates** go in `docs/templates/` — keep them generic with placeholder text (e.g., `[CLIENT NAME]`, `[DATE]`)
- **Policies** go in `docs/policies/` — follow standard HR policy structure: Purpose, Scope, Policy, Procedure, Definitions
- **Spreadsheets** go in `data/spreadsheets/` — include a README tab or header row explaining each column

---

## Data & Privacy

- Never include real employee PII (names, SSNs, salaries, addresses) in code, comments, or example data
- Use anonymized or synthetic data for testing and development
- Do not commit `.env` files or any file containing credentials or API keys

---

## Sensitive Areas

When working on content involving the following topics, flag any potential legal risk and recommend client review by legal counsel before finalizing:

- Termination procedures
- Discrimination, harassment, or EEO policies
- Leave policies (FMLA, ADA accommodations)
- Compensation and classification (exempt vs. non-exempt, FLSA)
- Background check and hiring screening policies
