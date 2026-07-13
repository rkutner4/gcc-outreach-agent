# GCC Institutional Wealth Outreach Agent

Automated discovery and outreach for senior contacts at holding companies in **UAE (Abu Dhabi, Dubai), KSA, Kuwait, and Bahrain**.

## What this does

1. Discovers holding companies (ZoomInfo + seed list + optional Sales Navigator CSV import)
2. Finds top executives at those companies
3. Enriches email/phone via ZoomInfo
4. Auto-sends **business-casual email** (Gmail) and **personal WhatsApp** (your number)
5. Detects replies and shows them in a web dashboard — **you reply manually** from Gmail/WhatsApp on your phone

## Step status

- Step 1: scaffold + dashboard
- Step 2: company/contact discovery (seed + ZoomInfo mock/API + Sales Nav CSV)
- Step 3: enrich + compose + Gmail/WhatsApp senders (dry-run by default) + inbound poll stub

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

### Useful commands

```powershell
python cli.py prospect "CIOs at sovereign wealth holding companies in UAE"
python cli.py list-companies
python cli.py whatsapp-login
python cli.py poll-inbound
```

## GitHub

Remote: https://github.com/rkutner4/gcc-outreach-agent

## Safety defaults

- `DRY_RUN=true` by default — nothing is truly sent until you turn it off in the dashboard/DB
- No LinkedIn automation (CSV import only)
- Auto-reply permanently disabled
- Personal WhatsApp live protocol is scaffolded; dry-run writes `wa.me` drafts until neonize is wired
