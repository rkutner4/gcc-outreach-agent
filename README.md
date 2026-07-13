# GCC Institutional Wealth Outreach Agent

Automated discovery and outreach for senior contacts at holding companies in **UAE (Abu Dhabi, Dubai), KSA, Kuwait, and Bahrain**.

## What this does

1. Discovers holding companies (ZoomInfo + seed list + optional Sales Navigator CSV import)
2. Finds top executives at those companies
3. Enriches email/phone via ZoomInfo
4. Auto-sends **business-casual email** (Gmail) and **personal WhatsApp** (your number)
5. Detects replies and shows them in a web dashboard — **you reply manually** from Gmail/WhatsApp on your phone

## Step 1 status (current)

Scaffold only:
- FastAPI dashboard shell
- SQLAlchemy models + SQLite
- Config via `.env`
- CLI helpers
- Tone templates

Discovery, ZoomInfo, Gmail, and WhatsApp senders land in later steps.

## Setup

```powershell
cd "C:\Users\renak\OneDrive\Documents\GitHub\gcc-outreach-agent"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python cli.py init
python cli.py serve
```

Open http://127.0.0.1:8000

## GitHub

Remote: https://github.com/rkutner4/gcc-outreach-agent

## Safety defaults

- `DRY_RUN=true` by default — nothing is sent until you turn it off
- No LinkedIn automation (CSV import only)
- Auto-reply permanently disabled
