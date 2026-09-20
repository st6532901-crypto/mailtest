# SIH Inbound Mail Receiver (demo / prototype)

Shows that a **real** email sent from Gmail or Outlook is received through **Resend Inbound**
and appears on a public dashboard hosted on Vercel. There is no email simulator and no
database. Every entry on the dashboard is an email Resend actually received.

```
Gmail / Outlook
      │  SMTP
      ▼
Resend Inbound   (<anything>@<id>.resend.app)
      │  HTTPS POST  "email.received"   (signed)
      ▼
FastAPI on Vercel  ── POST /api/webhook/resend
      │   verifies the signature on the raw body, validates, keeps a copy in memory
      ▼
Dashboard  GET /   →  polls  GET /api/emails  every 5 s
                          ├─ Resend "List Received Emails" API   (durable, reliable)
                          └─ in-memory webhook events            (fast, temporary)
```

## Where is mail stored? (read this)

**This app does not store email permanently. It has no database.**

| Copy | Lives in | Persistent? | Reliable on Vercel? |
|---|---|---|---|
| Resend's own record of the mail | Resend | Yes (Resend keeps received mail) | Yes |
| Webhook events kept by this app | Python memory of one server instance (last 50) | **No**, lost on restart / cold start / redeploy | **No**, each Vercel request may hit a different instance |

Because of that, the dashboard's source of truth is **Resend's Receiving API**, called
server-side with `RESEND_API_KEY`. The in-memory webhook copy only makes new mail appear a
moment sooner when the same instance happens to serve both requests. Both are merged and
de-duplicated by email id.

- **With `RESEND_API_KEY`:** reliable on Vercel. Recommended for the demo.
- **Without it:** the app still runs, but the dashboard only shows webhook events held by the
  instance that served the request, so mail can "disappear". The dashboard says so on screen.

If a later version needs permanent storage, replace `inbound/store.py`. Nothing else knows how mail
is kept.

## Project structure

```
sih-inbound-mail/
├── api/index.py               # Vercel entrypoint (exports `app`)
├── inbound/
│   ├── main.py                # FastAPI app, security headers, router wiring
│   ├── config.py              # env vars + logging
│   ├── security.py            # Resend/Svix webhook signature verification (stdlib only)
│   ├── schemas.py             # webhook payload validation + API models
│   ├── timeutil.py            # tolerant timestamp parsing (stdlib only)
│   ├── store.py               # TEMPORARY in-memory store (last 50 emails)
│   ├── resend_client.py       # read-only client for GET /emails/receiving (stdlib only)
│   ├── inbox.py               # merges Resend API + memory for the dashboard
│   ├── routes/
│   │   ├── webhook.py         # POST /api/webhook/resend
│   │   ├── emails.py          # GET  /api/emails
│   │   ├── health.py          # GET  /api/health
│   │   └── dashboard.py       # GET  /
│   └── templates/dashboard.html
├── tests/                     # pytest
├── requirements.txt           # fastapi, python-dotenv
├── requirements-dev.txt       # + uvicorn, pytest, httpx
├── vercel.json
├── .env.example
└── .gitignore
```

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `RESEND_WEBHOOK_SECRET` | **Yes** | Signing secret (`whsec_…`) from your Resend webhook. Verifies webhooks really come from Resend. |
| `RESEND_API_KEY` | **Strongly recommended** | Lets the dashboard read received mail from Resend's API so it works across serverless instances. Use a **Full access** key (the permission Resend's inbound guide uses; a sending-only key will likely be rejected with HTTP 403). Server-side only. |
| `LOG_LEVEL` | No | Default `INFO`. |
| `WEBHOOK_TOLERANCE_SECONDS` | No | Default `300`. Max clock difference allowed on webhook timestamps. |

There is **no `DATABASE_URL`** and nothing to set up beyond Resend.

## Local development

```bash
cd sih-inbound-mail
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env                   # then edit .env with your real values
uvicorn inbound.main:app --reload --port 8000
```

Open <http://localhost:8000> and <http://localhost:8000/api/health>. Run the tests with `pytest`.

With `RESEND_API_KEY` set, mail you send to your Resend address shows up locally even without the
webhook, because the dashboard reads Resend's API. To exercise the **webhook** locally, Resend
must be able to reach you, so tunnel your port and register the tunnel URL as the webhook:

```bash
ngrok http 8000          # or: cloudflared tunnel --url http://localhost:8000
# webhook URL: https://<random>.ngrok-free.app/api/webhook/resend
```

## Deploy to Vercel

```bash
npm i -g vercel
vercel login
vercel link

vercel env add RESEND_API_KEY production          # paste your re_… key
vercel env add RESEND_WEBHOOK_SECRET production   # paste "whsec_placeholder" for now

vercel --prod                                     # note the production URL
```

(Or import the repo at <https://vercel.com/new> and add the variables under **Settings → Environment
Variables**.) You need the URL before you can create the webhook, and the webhook gives you the real
secret, so after step 3 below **update `RESEND_WEBHOOK_SECRET` and redeploy** (`vercel --prod`).
Vercel applies environment variable changes only to new deployments.

Check <https://YOUR-VERCEL-DOMAIN/api/health>: both `webhook_secret_configured` and
`api_key_configured` should be `true`.

Use your **production** domain for the webhook. If Vercel Deployment Protection covers the URL, Resend
gets an HTML 401 page instead of your endpoint.

## Configure Resend

1. **Receiving address:** Resend dashboard → **Emails** → **Receiving** tab → ⋯ → **Receiving address**.
   It looks like `anything@<id>.resend.app`; any local part works.
2. **API key:** **API Keys** → **Create API Key** → **Full access** → set as `RESEND_API_KEY`.
3. **Webhook:** **Webhooks** → **Add Webhook**
   - Endpoint URL: `https://YOUR-VERCEL-DOMAIN/api/webhook/resend`
   - Event: **`email.received`**
   - Copy the **Signing Secret** → set as `RESEND_WEBHOOK_SECRET` → redeploy.

## Test with a REAL Gmail email

1. Open `https://YOUR-VERCEL-DOMAIN/`. It shows **Waiting for incoming email…**
2. In Gmail (or Outlook) write a message **To:** your `…@….resend.app` address, **Subject:** `Test Email`,
   and send it.
3. Within a few seconds the dashboard shows:

```
🟢 Mail Received                 Received 20 Sep 2026, 3:41:07 pm (just now)
From     you@gmail.com
To       anything@abc123.resend.app
Subject  Test Email
```

**Prove the webhook path worked** (the dashboard alone can't tell you, since it can also read Resend's API):

| Where | Expect |
|---|---|
| Resend → **Webhooks** → your endpoint → attempts | `email.received` with HTTP **200** |
| Vercel → **Logs** | `Received inbound email email_id=… delivery=msg_…` |

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| Dashboard notice "RESEND_API_KEY is not set…" | Add the key in Vercel and redeploy. |
| Notice "Couldn't read Resend's Receiving API (HTTP 401/403)" | Wrong key, or a sending-only key. Create a Full access key. |
| Webhook attempts show **400** | Wrong/old `RESEND_WEBHOOK_SECRET` (did you redeploy?). Logs say `Webhook rejected: …`. |
| Webhook attempts show **500** | `RESEND_WEBHOOK_SECRET` not set/invalid. |
| Webhook attempts show **401 / HTML** | Vercel Deployment Protection is blocking the URL. |
| Webhook attempts show **404** | URL typo. It must end in `/api/webhook/resend`. |
| Mail sent but nothing shows | Check it appears in Resend → Emails → Receiving. If not, the address is wrong. |

## API

| Method & path | Purpose |
|---|---|
| `GET /` | Dashboard (polls every 5 s, pauses when the tab is hidden). |
| `GET /api/emails?limit=50` | Latest emails, newest first (max 50), plus `sources` describing where the list came from. |
| `POST /api/webhook/resend` | Resend `email.received` webhook. Responses: `200 accepted / duplicate / ignored`, `400` bad signature or payload, `413` oversized, `500` webhook secret missing. |
| `GET /api/health` | Always 200 while the app runs. Reports whether the Resend secret and API key are configured. Never shows their values. |
| `GET /api/docs` | Swagger UI. |

```json
{
  "count": 1,
  "emails": [{
    "email_id": "56761188-7520-42d8-8898-ff6fc54ce618",
    "message_id": "<CAF=abc@mail.gmail.com>",
    "sender": "you@gmail.com",
    "recipients": ["anything@abc123.resend.app"],
    "subject": "Test Email",
    "received_at": "2026-09-20T10:00:00Z",
    "status": "received"
  }],
  "sources": { "resend_api": "ok", "resend_api_detail": null, "memory_count": 1 }
}
```

## Security

- **Webhook signatures are verified** on the raw request bytes (HMAC-SHA256, constant-time compare,
  5-minute replay window) before anything is parsed. Invalid → HTTP 400. Tested against Svix's published vectors.
- **Secrets stay on the server.** `RESEND_API_KEY` and `RESEND_WEBHOOK_SECRET` are read from the environment,
  never sent to the browser, never logged, and never included in error messages. `.env` is git-ignored.
- **Logs contain ids only:** no bodies, no secrets, no subjects.
- **Attacker-controlled text** (sender, subject) is rendered with `textContent` under a strict
  nonce-based Content-Security-Policy.
- **The dashboard is public by design**, and addresses and subjects are personal data. Don't publish it with
  real people's mail beyond a demo.
- The Resend API key has broad (Full access) permissions. Treat it like a password and rotate it in Resend if leaked.

## Scope

Only inbound receiving and display. There is no phishing detection, AI analysis, attachment analysis,
authentication, or email simulation.
