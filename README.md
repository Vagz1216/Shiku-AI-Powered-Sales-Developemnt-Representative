# Agent-Driven Outreach Platform

Automated email outreach with AI response monitoring and lead qualification.

## Project structure

Main areas:

- apps/api: FastAPI entry for outreach (health, POST outreach/run).
- packages/agents: Outbound generation, guardrails, batch pipeline.
- packages/db: SQLAlchemy models, session, eligibility and persistence helpers.
- packages/email: Calls shared AgentMail send in tools/.
- packages/schema: Outreach Pydantic types (drafts, run records).
- packages/shared: Re-exports config.settings for imports from packages.
- config: One AppConfig from environment (keys, DATABASE_URL, monitor and outreach tuning).
- db: schema.sql and seed.sql for local SQLite bootstrap.
- email_monitor: Inbound webhook, intent, reply agents.
- schema (repo root): Shared Pydantic for monitor and SendEmailResult.
- tools: send_plain_email, send_agent_email tool, send_reply_email.
- scripts: seed_contacts.py, run_outreach.py.

Adopted from the merged monitor work: config, root schema, tools, email_monitor. Outbound-specific code lives under packages/ and apps/api.

Outbound does not duplicate AgentMail retries: packages/email/outreach_send.py calls tools.send_plain_email.

## Quick start

1. Copy .env.example to .env and set OPENAI_API_KEY and AGENTMAIL variables.
2. Install: uv sync
3. First database open applies db/schema.sql and db/seed.sql if empty. Optional: uv run python scripts/seed_contacts.py
4. Outbound batch: uv run python scripts/run_outreach.py --limit 5
5. API (optional): from repo root, uv run uvicorn apps.api.main:app --reload then POST /outreach/run?limit=5
6. Inbound monitor: uv run run-email-monitor (see email_monitor/server.py; webhook helper: uv run setup-webhook if you use it).

## Outbound review checklist

Use this to sanity-check the outbound path before demo or PR.

Eligible leads: not opted out, active campaign, campaign_leads.emails_sent below cap, lead status not OPTED_OUT or COLD. Implemented in packages/db/outreach_queries.py (fetch_eligible_targets).

Per lead: load campaign name, value proposition, and CTA from the database; generate subject and body JSON via OpenAI Agents SDK (outreach_generator.py, outreach_pipeline.py).

Guardrails: tone, length, forbidden phrases, opt-out footer in packages/agents/guardrails.py.

Send: tools/send_plain_email, wrapped by packages/email/outreach_send.py.

After a successful send: update lead touch fields, increment campaign_leads.emails_sent, insert outbound email_messages, append events (persist_outbound_success).

Local schema reference: db/schema.sql and packages/db/models.py. Reconcile with the official database PR when it lands.

## Docker Deployment

### Quick Start

Build and run with Docker:
```bash
docker build -t squad3 .
docker run -p 7860:7860 -e OPENAI_API_KEY=your_key squad3
```

Or use Docker Compose:
```bash
# Set environment variables in .env file first
docker-compose up --build
```

### Hugging Face Spaces

Simply push your code - the Dockerfile handles deployment automatically.

Set these environment variables in your Space settings:
- `OPENAI_API_KEY`
- `AGENTMAIL_API_KEY`
- `AGENTMAIL_INBOX_ID`
- `COMPOSIO_API_KEY`
- `COMPOSIO_USER_ID`

Safe review (no real sends, still uses OpenAI):

    uv run python scripts/seed_contacts.py
    uv run python scripts/run_outreach.py --limit 1 --dry-run

Dry-run does not call AgentMail or write send-related database updates. For full body in JSON locally, add --full-body-preview (avoid pasting into public channels).

Eligible leads need a row in campaign_leads for an active campaign (see db/seed.sql). scripts/seed_contacts.py can add more linked leads.

Full send (real mail):

    uv run python scripts/run_outreach.py --limit 1

Use test inboxes and people who agreed to receive mail.

Guardrail unit tests only:

    uv sync --extra dev
    uv run pytest tests/test_guardrails.py -q

## Core features

- Email outreach agent for personalized campaigns.
- Response monitoring and intent handling.
- Lead qualification and notifications (as the platform grows).
- Google Meet style scheduling (planned / integrations).

## Architecture

Config: single AppConfig in config/settings.py; .env and .env.example drive behavior. Outreach reads the same settings via packages.shared.settings.

API: apps/api for outbound trigger; inbound uses email_monitor and run-email-monitor.

Packages hold database access and outbound orchestration; AgentMail send stays in tools/.

Schemas: root schema/ for monitor and tool results; packages/schema/ for outreach-only payloads.
