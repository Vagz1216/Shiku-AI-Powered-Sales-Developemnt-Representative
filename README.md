# Shiku: AI-Powered Sales Development Representative (SDR) Platform

Shiku is a production-grade, multi-tenant AI sales outreach platform that solves a critical bottleneck: scaling **personalized, omnichannel outbound sales** without overwhelming your sales team. By intelligently automating lead discovery, multi-step campaign outreach, inbound reply handling, and meeting coordination — all with human-in-the-loop approval checkpoints — Shiku lets sales teams focus exclusively on high-value conversations.

---

## 🎯 Problem Statement & Scope

**The Problem:** Traditional SDR work is highly manual, repetitive, and prone to poor personalization at scale. AI solutions often hallucinate, lack context, and cannot integrate safely with real business systems.

**The Scope:** Shiku strictly bounds each AI agent to a specific, highly-structured task (drafting, reviewing, intent classification, response generation). It enforces constraints via Pydantic schema validation and isolates external system mutations (database writes, email sends, calendar bookings) behind deterministic, non-AI control layers.

**Trade-offs:** An Orchestrator-Worker multi-agent pattern was deliberately chosen over a monolithic LLM prompt. This trades slight latency for significantly higher reliability, debuggability, and per-stage quality control.

---

## 🚀 Key Features

### 🤖 AI & Orchestration
- **Orchestrator-Worker Multi-Agent Pattern**: Two orchestrators (Outreach + Email Monitor) coordinate specialized worker agents — each with a focused role and Pydantic-validated outputs.
- **Chain-of-Thought Structured Outputs**: All agents include a `rationale` field that forces reasoning before action. Pydantic JSON schemas guarantee deterministic, production-ready outputs.
- **Multi-Provider AI Fallback**: Automatic failover across Azure OpenAI → OpenAI → Groq → Cerebras → Gemini → OpenRouter, with capability-aware routing (skips Groq for structured outputs, skips Cerebras for tool-calling) and per-provider blacklisting on quota failures.
- **Llama Guard Security**: All inbound email webhooks pass through Llama Guard validation before any LLM processing — protecting against prompt injection and malicious payloads.

### 🔍 Lead Scout
- **AI-Driven ICP Generation**: LLM generates Ideal Customer Profile (ICP) parameters from campaign value propositions before any API call.
- **Multi-Provider Discovery**: Sequential fallback across Apollo.io and People Data Labs (PDL), with Tavily for signal enrichment and a configurable Mock discoverer for local testing.
- **Provider Resilience**: Per-provider cooldown tracking with classified error handling (`ProviderFailure`) prevents wasted API credits during outages.
- **Human Review Before Import**: Discovered candidates are returned for human review — leads are not auto-imported.

### 📤 Omnichannel Outreach
- **Multi-Step Sequence Engine**: Campaigns define sequences of `email`, `linkedin`, and `whatsapp` steps with configurable delays. The orchestrator respects sequence order and delay windows, preventing duplicate sends.
- **Human-in-the-Loop Drafts**: By default, all generated outreach is saved as a DRAFT for human approval before sending. Auto-approve mode is available per campaign.
- **Three-Draft Generation + Reviewer Agent**: For email steps, the Drafter generates 3 variants; the Reviewer Agent selects the best and provides rationale.
- **LinkedIn & WhatsApp Content Tools**: Dedicated AI tools generate channel-appropriate connection notes and WhatsApp messages with automatic deep-link generation.

### 📥 Inbound Reply Monitoring
- **Multi-Source Reply Ingestion**: Supports AgentMail webhooks, Resend webhooks, SMTP/IMAP polling, Gmail OAuth polling, and Microsoft Outlook OAuth polling.
- **Intent Extraction**: Classifies inbound emails into: `meeting_request`, `meeting_confirmation`, `interest`, `question`, `unsubscribe`, `opt_out`, `other`.
- **Response Generation + Evaluation Loop**: Generates a context-aware response, evaluates it for quality, and retries (up to 2 times) if rejected before sending.
- **Smart Meeting Coordination**: For meeting intents, the EmailSenderAgent fetches real staff availability from the database and proposes a mathematically aligned time. Staff receive internal notification emails with action items. The AI explicitly avoids claiming calendar invites were sent — a human creates the invite.

### 🏢 Multi-Tenant Platform
- **Organization & Role Management**: Full org hierarchy with roles: `system_owner`, `org_admin`, `sales_manager`, `sales_user`, `viewer`.
- **Subscription Plans & Metering**: Configurable plans with limits on users, campaigns, leads, emails, and AI credits. Per-action AI credit tracking with overage controls.
- **BYOK (Bring Your Own Keys)**: Tenants on eligible plans can connect their own LLM API keys with configurable routing modes (`platform_first`, `organization_first`, `organization_only`).
- **LLM Routing Modes**: Per-campaign and per-plan routing controls: `quality_first`, `balanced`, `cost_optimized`.

### 📬 Mailbox Transport
- **Provider-Agnostic Sending**: Unified mailbox layer supporting **SMTP/IMAP**, **Resend API**, **Google Gmail OAuth**, and **Microsoft Outlook OAuth**.
- **Daily Send Limits**: Per-mailbox daily limit enforcement prevents accidental bulk sending.
- **Deduplication**: Inbound IMAP polling deduplicates by `external_message_id` to prevent double-processing.

### 🔒 Security & Observability
- **Clerk Authentication**: JWT-based auth with JWKS endpoint verification. Role-based API access enforcement throughout.
- **Encrypted Secrets**: Mailbox credentials (SMTP passwords, OAuth tokens, API keys) encrypted at rest using Fernet.
- **Langfuse Integration**: Full trace observability for all multi-agent pipelines via `@observe` decorators and `gen_trace_id`.
- **Structured JSON Logging**: Rotating log files with contextual fields for every pipeline stage.
- **SSE Real-Time Streaming**: Frontend receives live progress events during outreach runs via Server-Sent Events.

---

## 🏗️ System Architecture

```mermaid
graph TB
    User[User / Webhook / Cron] -->|Trigger| API[FastAPI / main.py]

    API -->|Campaign Request| Orch[🧠 Outreach Orchestrator]
    API -->|Email Reply Webhook| Monitor[🕵️ Email Monitor Orchestrator]
    API -->|Lead Discovery Job| Scout[🔍 Lead Scout Agent]

    subgraph DataLayer [Data Layer - Adapter Pattern]
        DB[(PostgreSQL / SQLite)]
        CRM[CRM API HubSpot / Salesforce]
    end

    Orch --> DataLayer
    Monitor --> DataLayer
    Scout --> DataLayer

    subgraph OutboundWorkers [Outbound Workers]
        Drafter[📝 Drafter Agent - 3 Variants]
        Reviewer[⚖️ Reviewer Agent]
        LinkedIn[🔗 LinkedIn Content Tool]
        WhatsApp[💬 WhatsApp Content Tool]
    end

    subgraph InboundWorkers [Inbound Workers]
        Guard[🛡️ Llama Guard]
        Intent[🏷️ Intent Extractor]
        Response[💬 Response Agent]
        Evaluator[✅ Response Evaluator]
        Sender[📨 Email Sender Agent]
    end

    subgraph LeadScout [Lead Scout]
        ICP[🎯 ICP Generator]
        Apollo[Apollo Discoverer]
        PDL[PDL Discoverer]
        Tavily[Tavily Enricher]
        Mock[Mock Discoverer]
    end

    subgraph MailboxTransport [Mailbox Transport]
        SMTP[SMTP / IMAP]
        Resend[Resend API]
        Gmail[Gmail OAuth]
        Microsoft[Outlook OAuth]
        AgentMail[AgentMail API]
    end

    Orch --> OutboundWorkers
    Monitor --> InboundWorkers
    Scout --> LeadScout

    Orch --> MailboxTransport
    Monitor --> MailboxTransport

    style Orch fill:#FFD700,color:#000
    style Monitor fill:#90EE90,color:#000
    style Scout fill:#FFA07A,color:#000
```

---

## 🔄 Current Workflows

### Outbound Campaign Flow

1. Load an active campaign and its sequence definition from the database.
2. Resolve eligible leads respecting sequence step, delay windows, opt-out flags, and response/meeting status.
3. Claim the next sequence step atomically (prevents duplicate sends across concurrent runs).
4. Route to the correct channel handler:
   - **Email**: Run Drafter Agent (3 variants) → Reviewer Agent (selects best) → Save as DRAFT or auto-send.
   - **LinkedIn**: Generate a personalized connection note → Save as DRAFT with LinkedIn deep-link.
   - **WhatsApp**: Generate a channel-appropriate message → Save as DRAFT with `wa.me` deep-link.
5. Human reviews and approves drafts in the dashboard (unless `auto_approve_drafts` is enabled).
6. Approved drafts are sent via the connected mailbox transport.

### Lead Discovery Flow

1. Campaign admin triggers a discovery job from the frontend.
2. `LeadScoutAgent` generates ICP parameters via LLM from the campaign's value proposition and CTA.
3. Sequentially tries Apollo → PDL (with provider cooldown and fallback).
4. Optionally enriches candidates with Tavily web signals.
5. Returns candidates for human review — import is a deliberate manual step.

### Inbound Reply Monitoring Flow

1. A webhook arrives at `POST /webhook` (AgentMail or Resend), or SMTP/IMAP polling detects unread mail.
2. Llama Guard validates the content for safety — fail-closed on policy violations.
3. `IntentExtractorAgent` classifies intent with a confidence score.
4. `EmailResponseAgent` generates a context-aware reply using conversation history.
5. `ResponseEvaluator` approves the response (up to 2 retry cycles on rejection).
6. For `meeting_request`/`meeting_confirmation` intents, `EmailSenderAgent` orchestrates a 4-tool sequence:
   - Fetch staff availability from database
   - Generate mathematically aligned proposed meeting time
   - Send reply to lead with proposed time
   - Notify staff with action-required heads-up (staff creates the calendar invite manually)
7. Lead status updates automatically: `WARM` → `MEETING_PROPOSED` → `MEETING_BOOKED`.

---

## 🗂️ Repo Layout

```
main.py                  # FastAPI app — all API routes, scheduled workers, SSE endpoints
frontend/                # Next.js app (Clerk auth, static export for Azure Static Web Apps / Vercel)
config/                  # AppConfig (Pydantic Settings), logging, LLM pricing
outreach/                # Outbound orchestrator + workers
  marketing_agent.py     # OutreachOrchestrator — campaign execution, sequence routing
  workers.py             # DrafterAgent, ReviewerAgent
  lead_scout/            # LeadScoutAgent, ICP generator, discoverers (Apollo, PDL, Tavily, Mock)
email_monitor/           # Inbound monitoring pipeline
  monitor.py             # EmailMonitorSystem — full inbound orchestrator
  security.py            # Llama Guard integration
  intent_extractor.py    # IntentExtractorAgent
  email_response.py      # EmailResponseAgent
  response_evaluator.py  # ResponseEvaluator
  email_sender.py        # EmailSenderAgent — LLM-driven tool orchestrator
tools/                   # Agent-callable tools (send email, get staff, meeting details, notify staff)
services/                # Business logic & data layer
  mailbox_transport.py   # Unified SMTP/IMAP / Resend / Gmail / Outlook send & polling
  mailbox_oauth_service.py # Google & Microsoft OAuth flow
  resend_email.py        # Resend HTTP API transport
  tenant_service.py      # Organizations, roles, plans, subscriptions, mailbox management
  lead_service.py        # Lead CRUD and eligibility logic
  sequence_service.py    # Campaign sequence step management and follow-up drafts
  draft_service.py       # Draft approval queue management
  metering_service.py    # AI credit tracking and platform usage events
  llm_credential_service.py # BYOK tenant LLM credential management
schema/                  # Shared Pydantic models (EmailIntent, DraftsResponse, ReviewResponse, etc.)
utils/                   # Cross-cutting concerns
  model_fallback.py      # Multi-provider fallback chain with blacklisting
  db_connection.py       # SQLite / PostgreSQL connection routing
  llama_guard.py         # Llama Guard safety check wrapper
db/                      # schema_pg.sql, seed_pg.sql (PostgreSQL schema for production)
migrations/              # Migration scripts
scripts/                 # apply_postgres_schema.py, apply_postgres_migrations.py
terraform/               # IaC for AWS (App Runner, Aurora, S3/CloudFront) — reference only
docs/                    # DEPLOY_AZURE.md, DEPLOY_AWS.md, DEPLOY_VERCEL_RENDER.md
```

---

## 📋 Requirements

- Python 3.12+
- `uv` package manager
- At least one AI provider API key (see Multi-Provider AI Fallback below)
- A connected sending mailbox: **SMTP/IMAP credentials**, **Resend API key**, **AgentMail API key**, or **Gmail/Outlook OAuth**
- Optional: Apollo, PDL, or Tavily API keys for Lead Scout
- Optional: Langfuse account for trace observability

### Multi-Provider AI Fallback

The system supports automatic failover. Configure one or more providers in `.env`:

| Priority | Provider      | Env Var(s)                                                                  | Notes                                              |
|----------|---------------|-----------------------------------------------------------------------------|----------------------------------------------------|
| 1        | Azure OpenAI  | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`  | Enterprise primary; preferred for Azure production |
| 2        | OpenAI        | `OPENAI_API_KEY`                                                            | Direct OpenAI API                                  |
| 3        | Groq          | `GROQ_API_KEY`                                                              | Fast; skipped for JSON-schema structured outputs   |
| 4        | Cerebras      | `CEREBRAS_API_KEY`                                                          | Fast; skipped for tool-calling tasks               |
| 5        | Google Gemini | `GEMINI_API_KEY`                                                            | Via OpenAI-compatible endpoint                     |
| 6        | OpenRouter    | `OPENROUTER_API_KEY`                                                        | Aggregator with multiple free model fallbacks      |

---

## ⚙️ Environment Setup

```bash
cp .env.example .env
```

Minimum required values in `.env`:

- At least one AI provider key (Azure OpenAI preferred for production)
- A sending mailbox: `AGENTMAIL_API_KEY` + `AGENTMAIL_INBOX_ID`, **or** `RESEND_API_KEY` + `RESEND_FROM_EMAIL`, **or** SMTP/IMAP credentials configured via the UI
- `CLERK_SECRET_KEY` + `CLERK_JWKS_URL` + `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`
- `MAILBOX_ENCRYPTION_KEY` (generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
- `PLATFORM_OWNER_EMAILS` (comma-separated admin email addresses)

Optional enhancements:
- `APOLLO_API_KEY` / `PDL_API_KEY` / `TAVILY_API_KEY` — for Lead Scout
- `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` — for trace observability
- `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` — for Gmail OAuth mailbox
- `MICROSOFT_OAUTH_CLIENT_ID` / `MICROSOFT_OAUTH_CLIENT_SECRET` — for Outlook OAuth mailbox

---

## 🛠️ Local Development

```bash
uv sync
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Once running:
- API root: `http://localhost:8000/`
- Health check: `http://localhost:8000/health`

**Frontend:**
```bash
cd frontend
npm install
npm run dev   # http://localhost:3000
```

**Webhook tunnel (for inbound email testing):**
```bash
./ngrok http 8000
# Set ngrok URL as webhook target in AgentMail or Resend dashboard
```

---

## 🔌 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Service overview |
| `GET` | `/health` | Global health check |
| `POST` | `/outreach/campaign` | Run an outreach campaign |
| `GET` | `/api/outreach/stream` | SSE stream of live campaign progress |
| `POST` | `/webhook` | Inbound email webhook (AgentMail or Resend) |
| `POST` | `/api/mailboxes/sync` | Trigger SMTP/IMAP unread poll |
| `POST` | `/api/lead-scout/run` | Trigger lead discovery job for a campaign |
| `GET` | `/api/drafts` | List draft messages awaiting approval |
| `POST` | `/api/drafts/{id}/approve` | Approve and send a draft |
| `GET` | `/api/campaigns` | List campaigns |
| `POST` | `/api/campaigns` | Create a campaign |

---

## 🐳 Docker

```bash
docker build -t sdr-backend .
docker run --rm -p 8000:8000 --env-file .env sdr-backend
```

Or with Compose:
```bash
docker compose up --build
```

---

## 🌐 Frontend (Next.js)

Static export (`output: "export"`) for hosting on Azure Static Web Apps or Vercel. Uses Clerk's `@clerk/clerk-react` (no Next.js middleware — compatible with static hosting).

```bash
cd frontend
npm install
npm run build   # produces frontend/out/
```

Set `NEXT_PUBLIC_API_URL` to your production API URL before building.

---

## 🚀 Production Deployment (Primary: Azure)

The primary deployment path uses **Azure Container Apps** for the backend, **Azure Database for PostgreSQL Flexible Server** for the database, and **Azure Static Web Apps** for the frontend.

### 1. Database (Azure PostgreSQL)
```bash
# Set connection string in .env:
DATABASE_URL=postgresql://user:password@host.postgres.database.azure.com/sdr?sslmode=require

# Apply schema:
uv run scripts/apply_postgres_schema.py
```

### 2. Backend (Azure Container Apps)
- Build and push Docker image to **Azure Container Registry (ACR)**.
- Deploy container to **Azure Container Apps** on port `8000`.
- Set all environment variables from `.env.azure.example` in the Container App's environment configuration.

### 3. Frontend (Azure Static Web Apps)
- Build with `npm run build` after setting `NEXT_PUBLIC_API_URL`.
- Deploy `frontend/out/` to Azure Static Web Apps.

### 4. CI/CD (GitHub Actions OIDC)
- See `.github/workflows/deploy-azure.yml` — deploys backend and frontend without storing Azure credentials in GitHub secrets.

### 5. Webhooks
- Configure AgentMail or Resend webhooks to point to: `https://<your-container-app-domain>/webhook`

Full deployment guide: **`docs/DEPLOY_AZURE.md`**

---

## ☁️ Alternative: Coolify + Neon PostgreSQL

For self-hosted or lower-cost deployments:

1. **Database**: Create a Neon project → set `DATABASE_URL=postgresql://...neon.tech/neondb?sslmode=require`
2. **Backend**: Deploy via Coolify as a Docker container; copy variables from `.env.example`
3. **Frontend**: Deploy statically via Vercel or Coolify Static

---

## ☁️ Alternative: AWS

Reference Terraform IaC in `terraform/` for:
- **Aurora Serverless v2 PostgreSQL** (database)
- **App Runner** (backend API)
- **S3 + CloudFront** (frontend)

Full guide: **`docs/DEPLOY_AWS.md`**

---

## 🔐 GitHub & Secrets

**Never commit:**
- `.env`, `frontend/.env.local`, or any file with API keys
- `terraform/**/*.tfvars` (only `*.tfvars.example` is tracked)
- `*.tfstate` or `.terraform/`

**Do commit:** `terraform/*/.terraform.lock.hcl` (pin provider versions).

```bash
git fetch origin
git status  # confirm nothing sensitive is staged
```
