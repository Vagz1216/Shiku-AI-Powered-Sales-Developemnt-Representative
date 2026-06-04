# Design Decisions

## Architecture Decision Records

### ADR-001 - OpenAI Agents SDK For Orchestration

**Context:** The system needs multiple LLM-backed steps for outreach drafting, inbound intent classification, response generation, evaluation, and tool-mediated sending.
**Decision:** Use the OpenAI Agents SDK as the orchestration layer, with explicit worker functions around each agent.
**Rationale:** The SDK provides structured outputs, tool calling, and trace integration while keeping the application code relatively small.
**Trade-offs:** The app is coupled to the Agents SDK execution model, so tests must mock agent calls instead of treating LLM calls as ordinary HTTP clients.

### ADR-002 - Multi-Provider LLM Fallback

**Context:** A sales workflow should not fail completely when one LLM provider is unavailable, quota-limited, or missing a capability.
**Decision:** Route agent calls through `utils.model_fallback.run_agent_with_fallback`, preferring Azure OpenAI when configured, then OpenAI, then compatible fallback providers.
**Rationale:** A single provider is a reliability and quota risk. Centralizing fallback keeps provider ordering, retries, and capability filtering in one place.
**Trade-offs:** Provider behavior differs, so structured-output and tool-calling support must be filtered per request.

### ADR-003 - SQLite Locally, Aurora Data API In Production

**Context:** Local development needs a simple database, while deployment needs managed persistence on AWS.
**Decision:** Use SQLite for local development and Aurora Serverless PostgreSQL through the RDS Data API when AWS database environment variables are set.
**Rationale:** This gives fast local setup and a production path without maintaining separate application code for the two modes.
**Trade-offs:** SQL compatibility must be managed carefully. Any new query pattern should be tested against the adapter layer.

### ADR-004 - Clerk JWT Authentication

**Context:** The frontend needs user authentication, and the backend needs to verify browser requests.
**Decision:** Use Clerk on the frontend and verify Clerk JWTs in FastAPI via JWKS.
**Rationale:** Clerk provides a hosted auth surface and JWTs suitable for API authorization checks.
**Trade-offs:** Backend availability depends on JWKS refresh behavior, so cached keys and auth tests are required.

### ADR-005 - Human-In-The-Loop Meeting Scheduling

**Context:** Calendar creation is externally visible and can create false commitments if automated incorrectly.
**Decision:** The AI proposes meeting details and notifies staff. Staff create the actual calendar invite manually.
**Rationale:** This avoids false “invite sent” claims and keeps business commitments under human control.
**Trade-offs:** The workflow is less automated, but safer and easier to explain in demos and operations.

### ADR-006 - AWS Deployment Target

**Context:** The project needs a reproducible deployment path for backend, database, and static frontend.
**Decision:** Use Terraform for Aurora, App Runner/ECR, and S3/CloudFront.
**Rationale:** Infrastructure as Code makes deployment repeatable and auditable.
**Trade-offs:** Terraform state and secrets management require discipline before production use.

### ADR-007 - Local LLM Usage Ledger

**Context:** Operators need to understand token consumption, fallback behavior, latency, and estimated costs across multiple model providers.
**Decision:** Record every successful agent call in `llm_usage_events` from the central `run_agent_with_fallback` path, and estimate costs from an editable pricing file.
**Rationale:** Central instrumentation avoids per-agent drift and gives the UI enough data for model, provider, and recent-call rollups.
**Trade-offs:** Costs are estimates until reconciled against provider billing exports, and provider pricing must be reviewed when models or rates change.

### ADR-008 - Resend Email Provider Adapter

**Context:** Production outreach needs branded-domain sending and inbound reply webhooks without depending on AgentMail premium custom domains.
**Decision:** Add Resend as a selectable email provider behind `EMAIL_PROVIDER`, keeping AgentMail as the default fallback while DNS, webhooks, and deliverability are validated.
**Rationale:** A provider adapter lets outbound outreach, monitor replies, and inbound webhook processing move to `outreach.markethacks.co.ke` without rewriting the AI monitor pipeline.
**Trade-offs:** Resend reply threading is best-effort through email headers, and inbound webhooks require an extra API fetch because Resend webhook events carry metadata rather than full message content.

### ADR-009 - Organization-Owned Mailbox Connections

**Context:** A commercial version needs a system owner who can onboard customer organizations, and each customer needs admins who connect their own sending/receiving email identities.
**Decision:** Add platform users, organizations, organization user roles, and mailbox connections. Start with `smtp_imap` mailbox records and connectivity tests, while preserving Resend, Gmail, and Microsoft as provider types for later adapters.
**Rationale:** Existing cPanel/webhost mailboxes are common for target SMEs, so SMTP/IMAP is the simplest first integration for customer-owned addresses like `info@company.com`.
**Trade-offs:** SMTP/IMAP passwords must be protected with an app encryption key and this first step only validates mailbox connectivity; routing campaigns through a selected mailbox and polling IMAP are follow-up integration steps.

### ADR-010 - First-Party Subscription Plans

**Context:** The platform owner needs to define commercial plans, and customer organizations need a simple way to select a plan before using outreach workflows.
**Decision:** Store a system-owner-managed `subscription_plans` catalog and one current `organization_subscriptions` row per organization. Workflow mutations require an active subscription or unexpired trial, while organization and plan-management routes remain available.
**Rationale:** This keeps billing state deterministic and testable without adding a payment provider before the plan-selection workflow exists.
**Trade-offs:** The first version does not process payments or enforce numeric plan limits at write time; those can be added after the commercial limits are finalized.

### ADR-011 - Pre-AWS Deployment Target

**Context:** The project needs a lower-friction deployment path before committing to AWS or Azure infrastructure.
**Decision:** Deploy the static Next.js frontend to Vercel and the Dockerized FastAPI backend to Render, using a Render persistent disk for interim SQLite persistence.
**Rationale:** Vercel is a strong fit for the static dashboard, while Render can run the long-lived API container, webhooks, and scheduled sender without forcing the backend into serverless constraints.
**Trade-offs:** SQLite on a persistent disk is an interim single-instance choice. Move to managed Postgres before real customer traffic or multi-instance scaling.

## Prompt Engineering Log

### Drafter Agent

**Problem:** Early drafts could repeat the same opener across follow-ups or include bracketed placeholders.
**Change:** Added sequence-stage guidance and explicit placeholder replacement rules.
**Outcome:** Drafts are more usable for first-touch and follow-up outreach.

### Reviewer Agent

**Problem:** The reviewer could select a draft without explaining the business reason.
**Change:** Required a concise rationale and explicit selected draft type.
**Outcome:** The chosen draft is auditable in logs and saved records.

### Intent Extractor

**Problem:** Meeting requests and meeting confirmations can be confused when thread history contains earlier proposed times.
**Change:** Added a specific distinction between first-time meeting requests and confirmations.
**Outcome:** Downstream sender behavior can route to tentative versus confirmed staff notifications.

### Response Agent

**Problem:** Generated replies could imply that calendar invites were already sent.
**Change:** Prompt rules now require careful scheduling language and the sender layer also rewrites false invite-sent claims.
**Outcome:** The workflow avoids creating false external commitments.

### Response Evaluator

**Problem:** Generated responses could be incomplete or inappropriate for the classified intent.
**Change:** Added checks for tone, completeness, signature, and intent-specific scheduling language.
**Outcome:** Rejected responses are retried with feedback before sending.

### Email Sender Agent

**Problem:** Tool ordering matters for meeting flows.
**Change:** Sender instructions define a strict one-tool-at-a-time workflow for meeting proposal and confirmation paths.
**Outcome:** Staff lookup, meeting detail generation, client reply, and staff notification happen in a predictable order.

### Safety Agent

**Problem:** Inbound emails can contain prompt-injection or tool-hijacking attempts.
**Change:** Llama Guard style safety check runs before LLM intent extraction and fails closed on errors.
**Outcome:** Unsafe messages are rejected before normal pipeline processing.
