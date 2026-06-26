# Shiku: Enterprise AI-Powered Sales Development Representative (SDR) Platform

Shiku is a production-grade, AI-assisted sales outreach platform designed to solve a critical business bottleneck: scaling personalized outbound sales without sacrificing quality or overwhelming human sales teams. By intelligently automating database-backed email campaigns, monitoring inbound replies, extracting lead intent, and coordinating follow-up meetings based on real staff availability, Shiku allows sales teams to focus strictly on high-value human interactions.

This repository has been architected from the ground up to demonstrate deep domain understanding, strict AI framing, and enterprise-grade engineering practices. It transitions a conceptual AI workflow into a robust, deployable system with strict data contracts, observability, and security guardrails.

## 🎯 Problem Statement & Scope
**The Problem:** Traditional SDR work is highly manual, repetitive, and prone to poor personalization. AI solutions often struggle with hallucinations, lack of context, and inability to integrate safely with real-world databases and calendars.
**The Scope:** Shiku strictly bounds its AI agents to specific, highly structured tasks (drafting, reviewing, intent extraction). It enforces constraints through strict schema validation and isolates external system mutations (like database writes or calendar bookings) behind deterministic, non-AI control layers. 
**Trade-offs:** We deliberately chose an Orchestrator-Worker multi-agent pattern over a single monolithic LLM prompt to ensure reliability and debuggability, trading slight latency for significantly higher output quality and safety.

## 🚀 Key Features & Engineering Practices

*   **Advanced Orchestration & Control Flow**: Employs an Orchestrator-Worker multi-agent pattern with dynamic routing, robust error handling, and graceful fallbacks.
*   **Sophisticated Prompting & Model Interaction**: Uses advanced prompt engineering including Chain of Thought (`rationale` field generation before answers) and strictly enforced Pydantic JSON schemas to guarantee deterministic, production-ready outputs.
*   **Data Access Layer (Adapter Pattern)**: Modular architecture allowing seamless switching between local SQLite (for rapid development) and AWS Aurora Serverless v2 PostgreSQL (for production) via `DATA_SOURCE` environment variables.
*   **Smart Calendar Scheduling**: Fetches real staff availability from the database and mathematically aligns proposed times, completely eliminating AI hallucinations and double-booking risks.
*   **Enterprise Security & Guardrails**: Integrates Llama Guard to validate inbound email webhooks, protecting the system against prompt injection attacks and malicious payloads before they reach the core LLM logic.
*   **Comprehensive Observability & Logging**: Features structured logging across all components, surfacing meaningful context for errors, and ensuring full traceability of multi-agent interactions and system health.
*   **Production-Ready Deployment**: Fully automated, production-grade deployment pipeline using Terraform (IaC) to AWS (App Runner for API, Aurora PostgreSQL for DB, S3 + CloudFront for Frontend), ensuring environment parity and scalable performance.

## 🏗️ System Architecture

Our upgraded architecture implements the Orchestrator-Worker pattern, robust data layers, and structured AI outputs.

```mermaid
graph TB
    User[User / Webhook] -->|Trigger| API[FastAPI / main.py]
    
    API -->|Campaign Request| Orchestrator[🧠 Senior Marketing<br/>Orchestrator]
    API -->|Email Reply| Monitor[🕵️ Email Monitor<br/>Orchestrator]
    
    subgraph DataLayer [Data Access Layer - Adapter Pattern]
        DataRouter[Data Provider Interface]
        DB[(Aurora Serverless<br/>SQLite fallback)]
        CRM[External CRM API<br/>HubSpot/Salesforce]
        DataRouter -.->|Internal| DB
        DataRouter -.->|External| CRM
    end
    
    Orchestrator -->|Get Context| DataRouter
    
    subgraph Workers [Worker Agents - Structured Outputs]
        Drafter[📝 Drafter Agent]
        Reviewer[⚖️ Reviewer Agent]
        Intent[🏷️ Intent Agent]
    end
    
    Orchestrator -->|Delegate| Drafter
    Orchestrator -->|Delegate| Reviewer
    Monitor -->|Delegate| Intent
    
    Drafter -->|Pydantic JSON| Orchestrator
    Reviewer -->|Pydantic JSON| Orchestrator
    Intent -->|Pydantic JSON| Monitor
    
    Orchestrator -->|Send via AgentMail| EmailOut[AgentMail API]
    Monitor -->|Book Meeting| Calendar[Composio Google Cal]
    
    style Orchestrator fill:#FFD700,color:#000
    style Monitor fill:#90EE90,color:#000
    style Drafter fill:#87CEEB,color:#000
    style Reviewer fill:#87CEEB,color:#000
    style Intent fill:#87CEEB,color:#000
    style DataRouter fill:#DDA0DD,color:#000
```

## Current Workflow

### Outbound Campaign Flow
1. Load an active campaign from the database (via Data Adapter).
2. Select an eligible lead.
3. Generate three email variants utilizing Pydantic structured outputs.
4. Evaluate and select the strongest draft.
5. Send one outbound email through AgentMail.

### Inbound Monitoring Flow
1. AgentMail sends a webhook to `POST /webhook`.
2. The app validates the event against **Llama Guard** for prompt injection.
3. The monitor extracts intent from the inbound message.
4. A response is generated and evaluated.
5. The system sends a reply. For `meeting_request` intents, it pulls the assigned SDR's actual availability JSON from the database and proposes a mathematically aligned time via Google Calendar (Composio).

## Repo Layout

*   `main.py`: FastAPI app (API + optional Gradio legacy routes)
*   `frontend/`: Next.js 16 app (Clerk + static export for S3/Azure Static Web Apps hosting)
*   `config/`: Environment settings and logging configuration
*   `outreach/`: Campaign orchestration agent
*   `email_monitor/`: Inbound monitoring pipeline, intent extraction, and Llama Guard security
*   `tools/`: Agent-callable tools for campaigns, email, staff availability, and meetings
*   `services/`: Data Adapter Pattern implementation (SQLite/CRM routing)
*   `schema/`: Shared Pydantic models enforcing Structured Outputs
*   `db/`: SQLite and PostgreSQL schema/seed (`schema_pg.sql`, `seed_pg.sql` for Aurora/Azure PostgreSQL)
*   `utils/db_connection.py`: SQLite locally; **Aurora Data API** when `DB_CLUSTER_ARN` / `DB_SECRET_ARN` are set; standard PostgreSQL when `DATABASE_URL=postgresql://...`
*   `terraform/`: IaC for database, backend (ECR + App Runner), frontend (S3 + CloudFront)
*   `docs/DEPLOY_AWS.md`: Step-by-step AWS deploy and operations
*   `docs/DEPLOY_AZURE.md`: Azure Container Apps, Azure PostgreSQL, Static Web Apps, and GitHub OIDC deploy guide
*   `implementation.md`: Architecture notes and checklist

## Requirements

*   Python 3.12+
*   `uv` package manager
*   At least one AI provider API key (see Multi-Provider Fallback below)
*   AgentMail inbox and API key for real email delivery
*   Optional: Composio credentials for automatic Google Calendar meeting creation

### Multi-Provider AI Fallback

The system supports automatic failover across multiple AI providers. Configure one or more in your `.env`:

| Priority | Provider | Env Var(s) | Notes |
|----------|----------|-----------|-------|
| 1 | Azure OpenAI | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT` | Enterprise primary |
| 2 | OpenAI | `OPENAI_API_KEY` | Direct OpenAI API |
| 3 | Groq | `GROQ_API_KEY` | Fast; skipped for JSON-schema tasks |
| 4 | Cerebras | `CEREBRAS_API_KEY` | Fast; skipped for tool-calling tasks |
| 5 | Google Gemini | `GEMINI_API_KEY` | Native Gemini API via OpenAI-compatible endpoint |
| 6 | OpenRouter | `OPENROUTER_API_KEY` | Aggregator with multiple free model fallbacks |

## Environment Setup

1. Copy the sample env file:
   ```bash
   cp .env.example .env
   ```
2. Fill in the required values in `.env`:
*   At least one AI provider key: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `OPENROUTER_API_KEY`, or Azure OpenAI settings (`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`)
   *   `AGENTMAIL_API_KEY`
   *   `AGENTMAIL_INBOX_ID`
   *   `DATA_SOURCE` (Optional: set to `CRM` to test the Adapter Pattern dummy logic)
   *   **Frontend static build**: `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` (Clerk Dashboard → API Keys) and optional `NEXT_PUBLIC_API_URL` for production (see `frontend/.env.example`). Root `.env` is loaded automatically when you run `npm run build` in `frontend/`.

## Local Development

Install dependencies:
```bash
uv sync
```

Start the app in development mode:
```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Once running:
*   API root: `http://localhost:8000/`
*   Health check: `http://localhost:8000/health`
*   Legacy UI: `http://localhost:8000/outreach`

## API Endpoints

*   `GET /`: Service overview
*   `GET /health`: Global health check
*   `POST /outreach/campaign`: Run a campaign (optional `campaign_name` query param)
*   `POST /webhook`: AgentMail inbound email webhook

Example campaign trigger:
```bash
curl -X POST "http://localhost:8000/outreach/campaign?campaign_name=Outbound%20Outreach%20-%20Q2"
```

## Docker

Build and run locally (image tag is your choice; Terraform/App Runner expects ECR repo **`sdr-backend`** with tag **`latest`** in AWS):
```bash
docker build -t sdr-backend .
docker run --rm -p 8000:8000 --env-file .env sdr-backend
```

Compose:
```bash
docker compose up --build
```

## Frontend (Next.js)

Static export (`output: "export"`) for hosting on S3. Clerk uses **`@clerk/clerk-react`** (no Next middleware on static hosting).

```bash
cd frontend
cp .env.example .env.local   # optional; or set vars in repo root .env
npm install
npm run build                # produces frontend/out/
```

Set `NEXT_PUBLIC_API_URL` to your production API URL (CloudFront/App Runner on AWS, or Azure Container Apps/Front Door on Azure) so the browser calls the deployed backend.

## Production Deployment (Coolify + Neon Postgres + Azure OpenAI)

The recommended production deployment path uses Coolify for the FastAPI backend, Vercel/Static hosting for the Next.js frontend, and Neon for serverless PostgreSQL.

1. **Database (Neon PostgreSQL)**
   * Create a Neon project and get your pooled connection string.
   * Add the connection string to your environment: `DATABASE_URL=postgresql://user:password@ep-name.region.aws.neon.tech/neondb?sslmode=require`
   * Run migrations using the script: `uv run scripts/apply_postgres_schema.py`

2. **Backend (Coolify)**
   * Deploy the repository (`https://github.com/Vagz1216/Shiku-AI-Powered-Sales-Developemnt-Representative`) via Coolify as a Docker container.
   * Copy the required variables from `.env.example` to Coolify's Environment Variables section.
   * Ensure `PORT=8000` is exposed and mapped correctly.
   * For Azure OpenAI, set:
     ```env
     AZURE_OPENAI_API_KEY=your_key
     AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
     AZURE_OPENAI_DEPLOYMENT=your_deployment_name
     AZURE_OPENAI_API_VERSION=2024-10-21
     AZURE_OPENAI_WIRE_API=chat_completions
     ```

3. **Frontend (Vercel or Coolify Static)**
   * The Next.js frontend can be deployed statically.
   * Set `NEXT_PUBLIC_API_URL` to point to your Coolify backend domain.
   * Run `npm run build` and serve the `out/` directory.

4. **Webhooks**
   * Configure AgentMail or Resend webhooks to point to your Coolify backend domain: `https://your-coolify-domain.com/webhook`

## AWS deployment (summary)

1. **`terraform/database`** — Aurora + secret (see `terraform/README.md`).
2. **`scripts/apply_aurora_schema.py`** — apply `db/schema_pg.sql` via Data API (env: `DB_CLUSTER_ARN`, `DB_SECRET_ARN`, `DB_NAME`, `AWS_REGION`).
3. **`terraform/backend`** — ECR + App Runner; push **`sdr-backend:latest`** to ECR **before** the first successful App Runner create (see `docs/DEPLOY_AWS.md`).
4. **`terraform/frontend`** — S3 website + CloudFront (API paths forwarded to App Runner).
5. Build frontend with `NEXT_PUBLIC_API_URL`, sync `frontend/out/` to the bucket, invalidate CloudFront.

Inbound webhooks (e.g. AgentMail) should target **`POST https://<your-cloudfront-domain>/webhook`**.

Full detail: **`docs/DEPLOY_AWS.md`**.

## Azure deployment (summary)

1. **Azure Database for PostgreSQL Flexible Server** — set `DATABASE_URL=postgresql://...?...sslmode=require`.
2. **`scripts/apply_postgres_schema.py`** — apply `db/schema_pg.sql` to the Azure PostgreSQL database.
3. **Azure Container Registry** — store the backend Docker image built from the root `Dockerfile`.
4. **Azure Container Apps** — run the FastAPI backend container on port `8000`.
5. **Azure Static Web Apps** — host the static `frontend/out/` dashboard.
6. **GitHub Actions OIDC** — deploy from `.github/workflows/deploy-azure.yml` without requiring a human Azure login.

Use **`.env.azure.example`** as the production environment handoff template. Full detail: **`docs/DEPLOY_AZURE.md`**.

## GitHub and secrets

Do **not** commit:

*   `.env`, `frontend/.env.local`, or any file containing API keys  
*   `terraform/**/*.tfvars` (only `*.tfvars.example` is tracked)  
*   `*.tfstate` or `.terraform/` (local Terraform state and provider cache)

Commit **`terraform/*/.terraform.lock.hcl`** so provider versions stay consistent. After cloning, copy `*.tfvars.example` → `terraform.tfvars` locally and fill in secrets.

### Confirm local matches `origin`

```bash
git fetch origin
git status
```
