# Waymark HR Group LLC — Project Repository

Waymark HR Group LLC is an HR consulting company. This repository contains the tools, documents, reports, and data assets used to support HR consulting engagements and internal operations.

---

## Folder Structure

```
waymark-hr-group/
├── src/                    # Source code
│   ├── python/             # Python scripts and modules (data processing, automation, reporting)
│   └── javascript/         # JavaScript code (web tools, dashboards, integrations)
│
├── docs/                   # Documents and written deliverables
│   ├── reports/            # Client reports and analysis documents (Word, PDF)
│   ├── templates/          # Reusable document templates
│   └── policies/           # HR policy documents and compliance materials
│
├── data/                   # Data assets
│   ├── spreadsheets/       # Excel/CSV spreadsheets (workforce data, compensation, tracking)
│   └── exports/            # Exported outputs from scripts or tools
│
├── config/                 # Configuration files (environment settings, API keys references)
├── tests/                  # Automated tests for source code
└── scripts/                # Utility and automation scripts (setup, deployment, data pipeline)
```

---

## Getting Started

1. Clone or download this repository.
2. See `config/` for environment setup instructions.
3. Python dependencies are listed in `requirements.txt` (when added to `src/python/`).
4. JavaScript dependencies are managed via `package.json` (when added to `src/javascript/`).

---

## Project Scope

This repository supports the following functions for Waymark HR Group LLC:

- **Client Reporting** — automated and manual report generation for HR engagements
- **Data Analysis** — workforce analytics, compensation benchmarking, and HR metrics
- **Document Management** — templates and finalized deliverables for client-facing work
- **Policy & Compliance** — HR policy documentation and regulatory reference materials
- **Internal Tools** — scripts and web tools to streamline consulting workflows

---

## GitHub Actions Automation

Every push to `main` automatically triggers the **Waymark Automation** workflow, which runs three jobs:

| Job | What it does |
|-----|-------------|
| **Auto-Backup** | Backs up all files in `docs/reports/` as a downloadable artifact, retained for 30 days |
| **Document Checker** | Scans any new `.docx` files added in the push and verifies required Waymark branding and contact info |
| **Project Summary** | Counts documents generated this month, lists new files in the push, and displays a full inventory log |

### How to view automation results

1. Go to the repository on GitHub: [github.com/jameswahler7/Waymark-HR-Group](https://github.com/jameswahler7/Waymark-HR-Group)
2. Click the **Actions** tab at the top
3. Click any workflow run titled **Waymark HR Group — Automation** to open it
4. Expand each job (**Auto-Backup**, **Document Checker**, **Project Summary**) to view detailed logs

### How to download a report backup

1. Open any completed workflow run in the **Actions** tab
2. Scroll to the **Artifacts** section at the bottom of the run page
3. Click **waymark-reports-backup-YYYY-MM-DD_HH-MM-SS** to download a `.zip` of all reports at that point in time
4. Backups are available for **30 days** from the date of the push

---

## Contact

**Waymark HR Group LLC**
For internal use. Contact the project owner for access or contribution guidelines.
