# Deploying SDR on Azure

This guide is for the Azure production shape of Shiku/SDR.

It assumes:

- The backend runs as a Docker image from the repo root `Dockerfile`.
- The frontend runs as a static Next.js export from `frontend/out`.
- Production persistence uses Azure Database for PostgreSQL Flexible Server.
- GitHub Actions deploys updates without requiring the developer to have a human Azure portal/RBAC account.

## Current Repo Readiness

The repo now supports three database modes:

| Mode | Trigger | Use |
| --- | --- | --- |
| SQLite | `DATABASE_URL=sqlite:///...` | Local development and single-instance demos |
| Aurora Data API | `DB_CLUSTER_ARN` + `DB_SECRET_ARN` | Existing AWS path |
| Standard PostgreSQL | `DATABASE_URL=postgresql://...` or `postgres://...` | Azure Database for PostgreSQL and other managed Postgres providers |

For Azure, use the standard PostgreSQL path. Do not set `DB_CLUSTER_ARN` or `DB_SECRET_ARN` on Azure.

## Azure Resource Map

| Need | Azure resource |
| --- | --- |
| Backend runtime | Azure Container Apps |
| Backend image registry | Azure Container Registry |
| Database | Azure Database for PostgreSQL Flexible Server |
| Frontend static app | Azure Static Web Apps |
| Secrets | Container Apps secrets and/or Azure Key Vault |
| Logs and metrics | Azure Monitor / Application Insights |
| CI/CD identity | GitHub Actions OIDC federated credential |
| Scheduler | Azure Container Apps Job or Azure Function timer |

## Backend Runtime Variables

Use `.env.azure.example` as the handoff template for the Azure owner.

Minimum required backend runtime values:

```env
APP_NAME=Shiku SDR
DEBUG=false
LOG_LEVEL=info
PORT=8000
DATABASE_URL=postgresql://DB_USER:DB_PASSWORD@DB_HOST:5432/DB_NAME?sslmode=require
CORS_ORIGINS=https://YOUR_STATIC_WEB_APP.azurestaticapps.net
RATE_LIMIT_REQUESTS_PER_MINUTE=60
CLERK_SECRET_KEY=...
CLERK_JWKS_URL=https://YOUR_CLERK_DOMAIN/.well-known/jwks.json
PLATFORM_OWNER_EMAILS=owner@example.com
WEBHOOK_SECRET=...
CRON_SECRET=...
MAILBOX_ENCRYPTION_KEY=...
REQUIRE_HUMAN_APPROVAL=true
SCHEDULED_SENDER_ENABLED=false
MAILBOX_SYNC_DEFAULT_LIMIT=10
MAILBOX_SYNC_ENABLED=false
MAILBOX_SYNC_MARK_SEEN=true
MAILBOX_SYNC_WAIT=false
MAILBOX_SYNC_INTERVAL_SECONDS=300
MAILBOX_CONNECTION_TIMEOUT_SECONDS=15
```

Add one AI provider path:

```env
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://YOUR_AZURE_OPENAI_RESOURCE.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=...
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_WIRE_API=chat_completions
```

Add one email provider path:

```env
EMAIL_PROVIDER=agentmail
AGENTMAIL_API_KEY=...
AGENTMAIL_INBOX_ID=...
```

or:

```env
EMAIL_PROVIDER=resend
RESEND_API_KEY=...
RESEND_FROM_EMAIL=Shiku <sdr@yourdomain.com>
RESEND_REPLY_TO=sdr@yourdomain.com
RESEND_WEBHOOK_SECRET=...
```

or, for connected tenant mailboxes:

```env
EMAIL_PROVIDER=mailbox
MAILBOX_ENCRYPTION_KEY=...
DEFAULT_MAILBOX_ID=
REQUIRE_EMAIL_MONITOR_HUMAN_APPROVAL=true
```

## Database Setup

1. Create Azure Database for PostgreSQL Flexible Server.
2. Create the app database, for example `sdr`.
3. Allow the deployment/runtime network path:
   - public access with restricted firewall rules for a demo, or
   - private access through a virtual network for production.
4. Apply the schema from the repo root:

```bash
export DATABASE_URL="postgresql://DB_USER:DB_PASSWORD@DB_HOST:5432/DB_NAME?sslmode=require"
uv run scripts/apply_postgres_schema.py
```

For existing production databases, apply tracked incremental migrations after pulling new code:

```bash
uv run scripts/apply_postgres_migrations.py
```

Optional demo seed:

```bash
uv run scripts/apply_postgres_schema.py --seed
```

The Azure deployment should use `db/schema_pg.sql` for first-time bootstrap and `scripts/apply_postgres_migrations.py` for existing databases. Do not rely on the SQLite bootstrap path for managed PostgreSQL.

## Backend Container App

The backend image is built from the root `Dockerfile`.

The Container App should:

- expose port `8000`
- use `/health` for health checks
- set minimum replicas to `1` initially
- use Container Apps secrets or Key Vault references for sensitive values
- set `SCHEDULED_SENDER_ENABLED=false` if more than one replica may run

After deploy, verify:

```bash
curl https://YOUR_BACKEND_DOMAIN/health
curl https://YOUR_BACKEND_DOMAIN/health/db
curl https://YOUR_BACKEND_DOMAIN/health/ai
```

## Frontend Static Web App

The frontend is a static export. Production build variables:

```env
NEXT_PUBLIC_API_URL=https://YOUR_BACKEND_DOMAIN
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_live_...
```

These are browser-visible build-time values. Changing them requires a frontend rebuild/redeploy.

## GitHub Actions Without Human Azure Access

The tracked workflow `.github/workflows/deploy-azure.yml` supports:

- backend Docker build and push to Azure Container Registry
- Azure Container Apps image update
- frontend deploy to Azure Static Web Apps

The Azure owner should create a GitHub OIDC federated identity scoped to the SDR resources, then configure the GitHub environment `azure-production`.

Required GitHub environment secrets:

```text
AZURE_CLIENT_ID
AZURE_TENANT_ID
AZURE_SUBSCRIPTION_ID
AZURE_STATIC_WEB_APPS_API_TOKEN
```

Required GitHub environment variables:

```text
AZURE_RESOURCE_GROUP
AZURE_CONTAINER_REGISTRY_NAME
AZURE_CONTAINER_REGISTRY_LOGIN_SERVER
AZURE_CONTAINER_APP_NAME
NEXT_PUBLIC_API_URL
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
```

Recommended Azure RBAC scope for the GitHub identity:

- `AcrPush` on the Azure Container Registry
- permission to update only the target Container App, ideally scoped to the resource group or app
- no broad Owner access

Recommended GitHub controls:

- protect `main`
- require pull request review before merge
- require approval for the `azure-production` environment
- restrict who can edit workflow files

## Scheduler

The app has an in-process scheduled sender for local development and simple single-replica deployments.

For production, prefer:

- `SCHEDULED_SENDER_ENABLED=false`
- Azure Container Apps Job or Azure Function timer calling due-work endpoints with `X-Cron-Secret`

This prevents duplicate sends when multiple backend replicas are running. The GitHub deployment workflow deploys the backend and frontend; it does not create or own the Azure timer/job. Create the timer/job in Azure and point it at the deployed backend.

Scheduled outbound email sender:

```bash
curl -X POST "https://YOUR_BACKEND_DOMAIN/api/scheduled-emails/send-due" \
  -H "Content-Type: application/json" \
  -H "X-Cron-Secret: YOUR_CRON_SECRET" \
  -d '{"limit":50}'
```

SMTP/IMAP mailbox monitoring:

```bash
curl -X POST "https://YOUR_BACKEND_DOMAIN/api/mailboxes/sync-due" \
  -H "Content-Type: application/json" \
  -H "X-Cron-Secret: YOUR_CRON_SECRET" \
  -d '{"wait":false,"mark_seen":true,"limit":10}'
```

Recommended mailbox scheduler cadence is every 5 minutes. Configure the same cadence in Azure and in `MAILBOX_SYNC_INTERVAL_SECONDS=300` so the runtime settings document what the scheduler is expected to do. In production, keep `MAILBOX_SYNC_MARK_SEEN=true` so already processed IMAP messages do not remain unread forever. The app also stores inbound `external_message_id` values and skips duplicates before LLM processing as a second protection against repeated drafts.

For local development or a simple single-replica demo, you can set `MAILBOX_SYNC_ENABLED=true` to run an in-process mailbox poller while `uvicorn` is running. Keep it `false` in Azure multi-replica production so only the external scheduler polls mailboxes.

## Webhooks

Configure email provider webhooks to call the backend API domain:

```text
https://YOUR_BACKEND_DOMAIN/webhook
```

For Resend:

```text
https://YOUR_BACKEND_DOMAIN/webhooks/email/resend
```

For tenant-owned Resend mailboxes:

```text
https://YOUR_BACKEND_DOMAIN/webhooks/email/resend/{mailbox_id}
```

Keep provider webhook signing secrets aligned with `WEBHOOK_SECRET` or `RESEND_WEBHOOK_SECRET`, depending on the provider.

## Handoff Checklist For Azure Owner

1. Create resource group.
2. Create Azure Container Registry.
3. Create Azure Database for PostgreSQL Flexible Server.
4. Apply `db/schema_pg.sql` with `scripts/apply_postgres_schema.py`.
5. Create Azure Container App from the backend image.
6. Set backend secrets/env from `.env.azure.example`.
7. Create Azure Static Web App.
8. Configure GitHub OIDC federated credential for `.github/workflows/deploy-azure.yml`.
9. Configure `azure-production` GitHub environment secrets/vars.
   - Add `DATABASE_URL` as an environment secret if GitHub Actions should apply migrations before backend rollout.
10. Point DNS/custom domains after `/health`, `/health/db`, sign-in, and draft approval are verified.
