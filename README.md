# Agent-Driven Outreach Platform

AI-assisted sales outreach platform for running database-backed email campaigns, monitoring inbound replies, and optionally coordinating follow-up meetings.

## What This Repo Does Now

This repository currently centers on one deployable application in [main.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/main.py):

- Outbound outreach campaigns driven by an OpenAI Agents workflow
- A Gradio UI mounted inside FastAPI at `/outreach`
- AgentMail webhook processing for inbound email replies
- Intent classification, response drafting, evaluation, and reply sending
- Optional meeting coordination through Composio + Google Calendar tools
- SQLite bootstrap with sample campaigns, leads, and staff records

The previous README described an older `packages/`-based structure. That layout is not present in this checkout, so this document reflects the current code in the repo root.

## Current Workflow

### Outbound campaign flow

1. Load an active campaign from the database.
2. Select an eligible lead.
3. Generate three email variants.
4. Let the agent choose the strongest draft.
5. Send one outbound email through AgentMail.

Primary files:

- [outreach/marketing_agent.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/outreach/marketing_agent.py)
- [outreach/gradio_interface.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/outreach/gradio_interface.py)
- [tools/campaign_tools.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/tools/campaign_tools.py)
- [tools/lead_tools.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/tools/lead_tools.py)
- [tools/send_email.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/tools/send_email.py)

### Inbound monitoring flow

1. AgentMail sends a webhook to `POST /webhook`.
2. The app validates the event and applies loop prevention.
3. The monitor extracts intent from the inbound message.
4. A response is generated and evaluated.
5. The system sends a reply and, for meeting requests, can create a calendar event and notify staff.

Primary files:

- [email_monitor/monitor.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/email_monitor/monitor.py)
- [email_monitor/email_sender.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/email_monitor/email_sender.py)
- [email_monitor/webhook_utils.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/email_monitor/webhook_utils.py)
- [tools/google_calendar.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/tools/google_calendar.py)
- [tools/notify_staff.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/tools/notify_staff.py)

## Repo Layout

- [main.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/main.py): FastAPI app and Gradio mount
- [config/](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/tree/main/config): environment settings and logging
- [outreach/](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/tree/main/outreach): campaign agent and UI
- [email_monitor/](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/tree/main/email_monitor): inbound monitoring pipeline
- [tools/](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/tree/main/tools): agent-callable tools for campaigns, email, staff, and meetings
- [services/](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/tree/main/services): database-oriented service layer
- [schema/](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/tree/main/schema): shared Pydantic models
- [db/](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/tree/main/db): SQLite schema and seed data
- [utils/db_connection.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/utils/db_connection.py): auto-creates schema and seeds sample data

## Requirements

- Python 3.12+
- `uv`
- OpenAI API key
- AgentMail inbox and API key for real email delivery
- Optional Composio credentials if you want automatic Google Calendar meeting creation

## Environment Setup

1. Copy the sample env file:

```bash
cp .env.example .env
```

2. Fill in the required values in `.env`:

- `OPENAI_API_KEY`
- `AGENTMAIL_API_KEY`
- `AGENTMAIL_INBOX_ID`

3. Optional values:

- `DATABASE_URL`
- `OPENROUTER_API_KEY`
- `CEREBRAS_API_KEY`
- `GROQ_API_KEY`
- `COMPOSIO_API_KEY`
- `COMPOSIO_USER_ID`

Important:

- `DEBUG` must be a real boolean such as `true` or `false`
- the default database is `sqlite:///./db/sdr.sqlite3`
- logs are written to `logs/squad3.log`

Reference files:

- [.env.example](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/.env.example)
- [config/settings.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/config/settings.py)

## Local Development

Install dependencies:

```bash
uv sync
```

Start the app in development mode:

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Alternative startup script:

```bash
./start.sh
```

Once running:

- API root: `http://localhost:8000/`
- Health check: `http://localhost:8000/health`
- Outreach UI: `http://localhost:8000/outreach`

If you use `./start.sh` or Docker, the default port is `7860`.

## Database Bootstrap

The SQLite database is created automatically on first access.

- Schema file: [db/schema.sql](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/db/schema.sql)
- Seed data: [db/seed.sql](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/db/seed.sql)

The seed includes:

- active and paused campaigns
- sample leads
- campaign-to-lead links
- staff records for meeting routing

You can verify campaign loading from the app because the Gradio dropdown is populated from the database.

## API Endpoints

- `GET /`: service overview
- `GET /health`: global health check
- `GET /email-monitor/health`: monitor health check
- `POST /outreach/campaign`: run a campaign, optional `campaign_name` query param
- `POST /webhook`: AgentMail inbound email webhook
- `GET /outreach`: Gradio campaign UI

Example campaign trigger:

```bash
curl -X POST "http://localhost:8000/outreach/campaign?campaign_name=Outbound%20Outreach%20-%20Q2"
```

## Docker

Build and run:

```bash
docker build -t squad3 .
docker run --rm -p 7860:7860 --env-file .env squad3
```

Or with Compose:

```bash
docker-compose up --build
```

The container image is set up for port `7860`, which also fits Hugging Face Spaces style deployment.

## Operational Notes

- Outbound sending uses AgentMail through [tools/send_email.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/tools/send_email.py).
- Inbound replies depend on AgentMail webhook delivery to `POST /webhook`.
- Meeting creation is only attempted for `meeting_request` intents.
- Google Calendar creation depends on Composio being configured correctly.
- Logging is configured once at startup and rotates to `logs/squad3.log`.

## Known Caveats

- Some scripts and tests still reference an older `packages.*` module layout that is not present in this checkout.
- In particular, [scripts/run_outreach.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/scripts/run_outreach.py), [scripts/seed_contacts.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/scripts/seed_contacts.py), and [tests/test_guardrails.py](https://github.com/Andela-AI-Engineering-Bootcamp/euclid_squad_3_sales_rep/blob/main/tests/test_guardrails.py) currently point at missing modules.
- Because of that, the most reliable paths today are the FastAPI app, the mounted Gradio UI, and the webhook monitor flow described above.

## Recommended Next Cleanup

- restore or remove the legacy `packages/`-based scripts and tests
- add a lightweight smoke test for `main.py`
- document the expected AgentMail webhook payload and local tunneling workflow
- add an end-to-end demo script for running one campaign against seed data
