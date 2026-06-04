# Deploy Without AWS/Azure

This is the recommended pre-AWS/Azure deployment shape for Shiku:

- **Frontend:** Vercel, deployed from `frontend/`.
- **Backend API:** Render web service, built from the root `Dockerfile`.
- **Database for this interim stage:** SQLite on a Render persistent disk.
- **Database before serious production traffic:** move to managed Postgres, such as Neon, Supabase, Render Postgres, or later Aurora/Postgres on AWS.

Vercel is a good fit for the static Next.js dashboard. The FastAPI API should not be forced into Vercel serverless right now because this app has webhook handling, scheduled/background sender behavior, and persistent database requirements.

## GitHub Actions

Two workflows are configured:

- `.github/workflows/test.yml` runs backend tests plus frontend lint/build.
- `.github/workflows/deploy.yml` deploys on pushes to `main`.

The deploy workflow skips deployment until the required repository secrets exist, so the first push will not leak secrets or fail because the platform accounts are not connected yet.

## Vercel Setup

Create a Vercel project with:

- **Root Directory:** `frontend`
- **Framework:** Next.js
- **Build Command:** `npm run build`
- **Output Directory:** `out`

Add these GitHub repository secrets:

- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`
- `NEXT_PUBLIC_API_URL` set to the Render API URL, for example `https://shiku-api.onrender.com`
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`

To get the Vercel IDs locally after linking the project:

```bash
cd frontend
npx vercel link
cat .vercel/project.json
```

Do not commit `.vercel/`.

## Render API Setup

Create the Render service from `render.yaml` or create a Docker web service manually:

- **Dockerfile:** `./Dockerfile`
- **Docker context:** `.`
- **Health check path:** `/health`
- **Disk mount:** `/app/db`
- **Database URL:** `sqlite:////app/db/sdr.sqlite3`

Set these Render environment variables:

- `CORS_ORIGINS`: your Vercel production URL and preview URL patterns you intentionally allow.
- `OPENAI_API_KEY`
- `AGENTMAIL_API_KEY`
- `AGENTMAIL_INBOX_ID`
- `CLERK_SECRET_KEY`
- `CLERK_JWKS_URL`
- `MAILBOX_ENCRYPTION_KEY`
- `PLATFORM_OWNER_EMAILS`
- `CRON_SECRET`

If using Resend or CRM imports, also set the matching provider variables from `.env.example`.

Then create a Render deploy hook for the API service and add it as:

- `RENDER_DEPLOY_HOOK_URL`

## Cutover Checklist

1. Push `main`.
2. Confirm CI passes.
3. Configure Vercel and Render secrets.
4. Trigger the Deploy workflow manually by pushing a no-op commit or using the Render deploy hook.
5. Set backend `CORS_ORIGINS` to the Vercel domain.
6. Point AgentMail or Resend inbound webhooks to `https://<api-domain>/webhook`.
7. Test `/health`, sign-in, campaign list, draft approval, and a safe webhook event.

## Before Azure Or AWS

Stay with Vercel + Render until the app has stable usage and the team knows its real traffic, mailbox, and data-retention needs. Move the database to managed Postgres before onboarding real customers. Move to Azure or AWS when you need private networking, mature IAM, managed queues, regional controls, or infrastructure that must be reproduced across environments with Terraform.
