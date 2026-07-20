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

### Gmail OAuth (live email)

Dry-run is on by default. To send real email:

1. **Google Cloud Console** (https://console.cloud.google.com)
   - Create or select a project
   - **APIs & Services → Library** → enable **Gmail API**
   - **OAuth consent screen** → External → add your Google account as a **Test user**
   - **Credentials → Create credentials → OAuth client ID → Desktop app**
   - Download the JSON and save it as `credentials/gmail_client_secret.json`

2. **`.env`**
   ```env
   SENDER_EMAIL=you@gmail.com
   GMAIL_CREDENTIALS_PATH=credentials/gmail_client_secret.json
   GMAIL_TOKEN_PATH=credentials/gmail_token.json
   ```

3. **Authorize locally** (opens browser once; refresh token is saved):
   ```powershell
   python cli.py gmail-login
   ```
   Confirms the linked mailbox via the Gmail profile API. Re-run anytime to refresh an expired token.

4. **Send a rehearsal**, then go live:
   ```powershell
   python cli.py status          # check gmail.client_secret_exists + token_exists
   python cli.py prospect "..."  # still dry-run until you flip it
   ```
   Disable dry-run in the dashboard (**Disable dry-run**) or set `DRY_RUN=false` in `.env`, then run `prospect` again.

Credential files under `credentials/` are gitignored. Never commit OAuth JSON or tokens.

### Useful commands

```powershell
python cli.py prospect "CIOs at sovereign wealth holding companies in UAE"
python cli.py list-companies
python cli.py gmail-login
python cli.py whatsapp-login
python cli.py poll-inbound
python cli.py status
```

## GitHub

Remote: https://github.com/rkutner4/gcc-outreach-agent

## Safety defaults

- `DRY_RUN=true` by default — nothing is truly sent until you turn it off in the dashboard/DB
- No LinkedIn automation (CSV import only)
- Auto-reply permanently disabled
- **One message per person, ever.** The agent sends a single initial email and then
  stops; all follow-up is human. Enforced at send time by `already_emailed()`, keyed
  on the normalized recipient address rather than the contact row — re-discovery
  routinely creates a second row for the same person, and that row is exactly what
  would otherwise earn them a second "initial" email. Because there is no sequence,
  there is no unsubscribe mechanism and outbound must never offer one.
- Personal WhatsApp live protocol is scaffolded; dry-run writes `wa.me` drafts until neonize is wired
